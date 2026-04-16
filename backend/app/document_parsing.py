from __future__ import annotations

import io
import re
import zlib
from typing import Iterable
from xml.etree import ElementTree as ET
from zipfile import BadZipFile, ZipFile


class DocumentParseError(RuntimeError):
    pass


def extract_document_text(*, filename: str, content: bytes) -> str:
    suffix = _normalized_suffix(filename)
    if suffix in {".txt", ".md"}:
        return _require_text(_decode_text_bytes(content), filename=filename)
    if suffix == ".docx":
        return _require_text(_extract_docx_text(content), filename=filename)
    if suffix == ".pdf":
        return _require_text(_extract_pdf_text(content), filename=filename)
    raise DocumentParseError("Unsupported document format. Please upload TXT, MD, PDF, or DOCX.")


def detect_image_mime_type(filename: str, content: bytes) -> str:
    suffix = _normalized_suffix(filename)
    if suffix in {".jpg", ".jpeg"}:
        return "image/jpeg"
    if suffix == ".png":
        return "image/png"
    if suffix == ".webp":
        return "image/webp"
    if suffix == ".gif":
        return "image/gif"
    if content.startswith(b"\xff\xd8"):
        return "image/jpeg"
    if content.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if content[:4] == b"RIFF" and content[8:12] == b"WEBP":
        return "image/webp"
    if content.startswith((b"GIF87a", b"GIF89a")):
        return "image/gif"
    raise DocumentParseError("Unsupported image format. Please upload PNG, JPG, WEBP, or GIF.")


def _require_text(text: str, *, filename: str) -> str:
    compact = " ".join((text or "").split())
    if compact:
        return compact
    raise DocumentParseError(f"No extractable text found in {filename}. Please paste the content manually.")


def _normalized_suffix(filename: str) -> str:
    dot = filename.rfind(".")
    if dot < 0:
        return ""
    return filename[dot:].strip().lower()


def _decode_text_bytes(content: bytes) -> str:
    for encoding in ("utf-8-sig", "utf-16", "utf-16-le", "utf-16-be", "gb18030", "latin-1"):
        try:
            return content.decode(encoding)
        except UnicodeDecodeError:
            continue
    return content.decode("utf-8", errors="ignore")


def _extract_docx_text(content: bytes) -> str:
    try:
        with ZipFile(io.BytesIO(content)) as archive:
            names = archive.namelist()
            candidate_names = [
                "word/document.xml",
                *sorted(name for name in names if name.startswith("word/header")),
                *sorted(name for name in names if name.startswith("word/footer")),
                *sorted(name for name in names if name.startswith("word/footnotes")),
                *sorted(name for name in names if name.startswith("word/endnotes")),
            ]
            texts: list[str] = []
            for name in candidate_names:
                if name not in names:
                    continue
                xml_text = archive.read(name)
                texts.extend(_extract_docx_xml_text(xml_text))
    except BadZipFile as exc:
        raise DocumentParseError("The DOCX file is invalid or corrupted.") from exc
    except KeyError as exc:
        raise DocumentParseError("The DOCX file does not contain readable document content.") from exc

    return "\n".join(texts)


def _extract_docx_xml_text(xml_blob: bytes) -> list[str]:
    namespace = {"w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main"}
    try:
        root = ET.fromstring(xml_blob)
    except ET.ParseError as exc:
        raise DocumentParseError("Failed to parse DOCX XML content.") from exc

    paragraphs: list[str] = []
    for paragraph in root.findall(".//w:p", namespace):
        parts: list[str] = []
        for node in paragraph.iter():
            tag = node.tag.split("}", 1)[-1] if "}" in node.tag else node.tag
            if tag == "t" and node.text:
                parts.append(node.text)
            elif tag == "tab":
                parts.append(" ")
            elif tag in {"br", "cr"}:
                parts.append("\n")
        text = "".join(parts).strip()
        if text:
            paragraphs.append(text)
    return paragraphs


def _extract_pdf_text(content: bytes) -> str:
    if b"%PDF" not in content[:1024]:
        raise DocumentParseError("The uploaded file is not a valid PDF.")

    texts: list[str] = []
    for header, stream in _iter_pdf_streams(content):
        decoded = _decode_pdf_stream(header, stream)
        if not decoded:
            continue
        extracted = _extract_pdf_text_from_stream(decoded)
        if extracted:
            texts.append(extracted)

    return "\n".join(texts)


def _iter_pdf_streams(content: bytes) -> Iterable[tuple[bytes, bytes]]:
    pattern = re.compile(rb"<<(.*?)>>\s*stream\r?\n(.*?)\r?\nendstream", re.DOTALL)
    for match in pattern.finditer(content):
        yield match.group(1), match.group(2)


def _decode_pdf_stream(header: bytes, stream: bytes) -> bytes:
    if b"FlateDecode" in header:
        for wbits in (zlib.MAX_WBITS, -zlib.MAX_WBITS):
            try:
                return zlib.decompress(stream, wbits)
            except zlib.error:
                continue
        return b""
    return stream


def _extract_pdf_text_from_stream(stream: bytes) -> str:
    blocks = re.findall(rb"BT(.*?)ET", stream, re.DOTALL)
    texts: list[str] = []
    for block in blocks:
        parts: list[str] = []
        parts.extend(_extract_pdf_strings_for_operator(block, operator=b"TJ", is_array=True))
        parts.extend(_extract_pdf_strings_for_operator(block, operator=b"Tj", is_array=False))
        parts.extend(_extract_pdf_strings_for_operator(block, operator=b"'", is_array=False))
        parts.extend(_extract_pdf_strings_for_operator(block, operator=b'"', is_array=False))
        cleaned = " ".join(part.strip() for part in parts if part.strip())
        if cleaned:
            texts.append(cleaned)
    return "\n".join(texts)


def _extract_pdf_strings_for_operator(block: bytes, *, operator: bytes, is_array: bool) -> list[str]:
    pattern = (
        re.compile(rb"\[(.*?)\]\s*" + re.escape(operator), re.DOTALL)
        if is_array
        else re.compile(rb"(\((?:\\.|[^\\)])*\)|<[^>]+>)\s*" + re.escape(operator), re.DOTALL)
    )
    results: list[str] = []
    for match in pattern.finditer(block):
        target = match.group(1)
        for item in _extract_pdf_string_tokens(target):
            text = _decode_pdf_string_token(item)
            if text:
                results.append(text)
    return results


def _extract_pdf_string_tokens(blob: bytes) -> list[bytes]:
    tokens: list[bytes] = []
    idx = 0
    while idx < len(blob):
        char = blob[idx : idx + 1]
        if char == b"(":
            token, idx = _read_pdf_literal_string(blob, idx)
            tokens.append(token)
            continue
        if char == b"<":
            end = blob.find(b">", idx + 1)
            if end > idx:
                tokens.append(blob[idx : end + 1])
                idx = end + 1
                continue
        idx += 1
    return tokens


def _read_pdf_literal_string(blob: bytes, start: int) -> tuple[bytes, int]:
    depth = 0
    idx = start
    escaped = False
    while idx < len(blob):
        char = blob[idx : idx + 1]
        if escaped:
            escaped = False
        elif char == b"\\":
            escaped = True
        elif char == b"(":
            depth += 1
        elif char == b")":
            depth -= 1
            if depth == 0:
                return blob[start : idx + 1], idx + 1
        idx += 1
    return blob[start:], len(blob)


def _decode_pdf_string_token(token: bytes) -> str:
    if token.startswith(b"(") and token.endswith(b")"):
        return _decode_pdf_literal(token[1:-1])
    if token.startswith(b"<") and token.endswith(b">"):
        return _decode_pdf_hex(token[1:-1])
    return ""


def _decode_pdf_literal(raw: bytes) -> str:
    output = bytearray()
    idx = 0
    while idx < len(raw):
        byte = raw[idx]
        if byte != 0x5C:
            output.append(byte)
            idx += 1
            continue

        idx += 1
        if idx >= len(raw):
            break
        escaped = raw[idx]
        mapping = {
            ord("n"): b"\n",
            ord("r"): b"\r",
            ord("t"): b"\t",
            ord("b"): b"\b",
            ord("f"): b"\f",
            ord("("): b"(",
            ord(")"): b")",
            ord("\\"): b"\\",
        }
        if escaped in mapping:
            output.extend(mapping[escaped])
            idx += 1
            continue
        if escaped in (ord("\n"), ord("\r")):
            idx += 1
            continue
        if 48 <= escaped <= 55:
            octal = bytes([escaped])
            idx += 1
            for _ in range(2):
                if idx < len(raw) and 48 <= raw[idx] <= 55:
                    octal += bytes([raw[idx]])
                    idx += 1
                else:
                    break
            output.append(int(octal, 8))
            continue
        output.append(escaped)
        idx += 1

    return _decode_pdf_text_bytes(bytes(output))


def _decode_pdf_hex(raw: bytes) -> str:
    compact = re.sub(rb"\s+", b"", raw)
    if len(compact) % 2 == 1:
        compact += b"0"
    try:
        decoded = bytes.fromhex(compact.decode("ascii"))
    except ValueError:
        return ""
    return _decode_pdf_text_bytes(decoded)


def _decode_pdf_text_bytes(raw: bytes) -> str:
    if raw.startswith((b"\xfe\xff", b"\xff\xfe")):
        for encoding in ("utf-16", "utf-16-be", "utf-16-le"):
            try:
                return raw.decode(encoding)
            except UnicodeDecodeError:
                continue
    for encoding in ("utf-8", "latin-1", "utf-16-be"):
        try:
            return raw.decode(encoding)
        except UnicodeDecodeError:
            continue
    return raw.decode("latin-1", errors="ignore")
