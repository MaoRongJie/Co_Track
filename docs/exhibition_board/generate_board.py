from __future__ import annotations

import argparse
from pathlib import Path
from typing import Iterable, Sequence

from PIL import Image, ImageDraw, ImageFilter, ImageFont


BASE_TEMPLATE = Path(
    r"d:\大学\4\毕业设计\2026展版版头90×200CM\2026展版版头90×200CM\展板1.jpg"
)
OUT_DIR = Path(__file__).resolve().parent

NAVY = "#13203A"
NAVY_2 = "#1E2B4A"
CYAN = "#00CFEA"
LIME = "#D7E90E"
BLUE = "#2563EB"
TEAL = "#0891B2"
GREEN = "#059669"
AMBER = "#F59E0B"
ROSE = "#E11D48"
PURPLE = "#7C3AED"
SLATE = "#334155"
MUTED = "#64748B"
LIGHT = "#F8FAFC"
BORDER = "#D9E2EE"


class Board:
    def __init__(self, template_path: Path, scale: int) -> None:
        self.scale = scale
        source = Image.open(template_path).convert("RGB")
        self.base_w, self.base_h = source.size
        self.img = source.resize((self.base_w * scale, self.base_h * scale), Image.Resampling.LANCZOS)
        self.draw = ImageDraw.Draw(self.img)
        self.font_cache: dict[tuple[int, bool], ImageFont.FreeTypeFont] = {}

    def s(self, value: float) -> int:
        return int(round(value * self.scale))

    def font(self, size: int, bold: bool = False) -> ImageFont.FreeTypeFont:
        key = (size, bold)
        if key in self.font_cache:
            return self.font_cache[key]

        candidates = [
            Path(r"C:\Windows\Fonts\msyhbd.ttc" if bold else r"C:\Windows\Fonts\msyh.ttc"),
            Path(r"C:\Windows\Fonts\simhei.ttf"),
            Path(r"C:\Windows\Fonts\Dengb.ttf" if bold else r"C:\Windows\Fonts\Deng.ttf"),
        ]
        for candidate in candidates:
            if candidate.exists():
                self.font_cache[key] = ImageFont.truetype(str(candidate), self.s(size))
                return self.font_cache[key]
        self.font_cache[key] = ImageFont.load_default()
        return self.font_cache[key]

    def text_len(self, text: str, font: ImageFont.FreeTypeFont) -> float:
        return self.draw.textlength(text, font=font)

    def xy(self, x: float, y: float) -> tuple[int, int]:
        return self.s(x), self.s(y)

    def box(self, x: float, y: float, w: float, h: float) -> tuple[int, int, int, int]:
        return self.s(x), self.s(y), self.s(x + w), self.s(y + h)

    def shadow_card(
        self,
        x: float,
        y: float,
        w: float,
        h: float,
        radius: float = 18,
        fill: str = "#FFFFFF",
        outline: str = BORDER,
        shadow: bool = True,
    ) -> None:
        if shadow:
            overlay = Image.new("RGBA", self.img.size, (0, 0, 0, 0))
            od = ImageDraw.Draw(overlay)
            od.rounded_rectangle(
                self.box(x + 4, y + 8, w, h),
                radius=self.s(radius),
                fill=(15, 23, 42, 28),
            )
            overlay = overlay.filter(ImageFilter.GaussianBlur(self.s(10)))
            self.img.paste(Image.alpha_composite(Image.new("RGBA", self.img.size), overlay).convert("RGB"), mask=overlay.split()[3])
        self.draw.rounded_rectangle(
            self.box(x, y, w, h),
            radius=self.s(radius),
            fill=fill,
            outline=outline,
            width=max(1, self.s(1.2)),
        )

    def line(self, points: Sequence[tuple[float, float]], fill: str = MUTED, width: float = 2) -> None:
        self.draw.line([(self.s(x), self.s(y)) for x, y in points], fill=fill, width=self.s(width), joint="curve")

    def arrow(self, x1: float, y1: float, x2: float, y2: float, fill: str = MUTED, width: float = 3) -> None:
        self.line([(x1, y1), (x2, y2)], fill=fill, width=width)
        dx = x2 - x1
        dy = y2 - y1
        length = max((dx * dx + dy * dy) ** 0.5, 1)
        ux, uy = dx / length, dy / length
        px, py = -uy, ux
        size = 13
        pts = [
            (self.s(x2), self.s(y2)),
            (self.s(x2 - ux * size + px * size * 0.52), self.s(y2 - uy * size + py * size * 0.52)),
            (self.s(x2 - ux * size - px * size * 0.52), self.s(y2 - uy * size - py * size * 0.52)),
        ]
        self.draw.polygon(pts, fill=fill)

    def wrapped_lines(self, text: str, font: ImageFont.FreeTypeFont, max_width: float) -> list[str]:
        max_px = self.s(max_width)
        lines: list[str] = []
        for para in text.split("\n"):
            current = ""
            for char in para:
                trial = current + char
                if current and self.text_len(trial, font) > max_px:
                    lines.append(current)
                    current = char
                else:
                    current = trial
            if current:
                lines.append(current)
        return lines

    def text(
        self,
        xy: tuple[float, float],
        content: str,
        size: int = 24,
        fill: str = SLATE,
        bold: bool = False,
        anchor: str | None = None,
    ) -> None:
        self.draw.text(self.xy(*xy), content, font=self.font(size, bold), fill=fill, anchor=anchor)

    def wrapped_text(
        self,
        x: float,
        y: float,
        text: str,
        max_width: float,
        size: int = 23,
        fill: str = SLATE,
        bold: bool = False,
        line_gap: float = 9,
    ) -> float:
        f = self.font(size, bold)
        yy = y
        for line in self.wrapped_lines(text, f, max_width):
            self.draw.text(self.xy(x, yy), line, font=f, fill=fill)
            yy += size + line_gap
        return yy

    def chip(self, x: float, y: float, text: str, fill: str, fg: str = "#FFFFFF", size: int = 18) -> float:
        f = self.font(size, True)
        pad_x = 18
        w = self.text_len(text, f) / self.scale + pad_x * 2
        h = size + 18
        self.draw.rounded_rectangle(self.box(x, y, w, h), radius=self.s(h / 2), fill=fill)
        self.draw.text(self.xy(x + pad_x, y + 9), text, font=f, fill=fg)
        return w

    def section_title(self, x: float, y: float, no: str, title: str, subtitle: str) -> None:
        self.draw.rounded_rectangle(self.box(x, y + 8, 10, 48), radius=self.s(4), fill=CYAN)
        self.text((x + 24, y), no, 19, CYAN, True)
        self.text((x + 24, y + 26), title, 34, NAVY, True)
        self.text((x + 24, y + 66), subtitle, 18, MUTED, False)

    def bullet_list(
        self,
        x: float,
        y: float,
        items: Iterable[str],
        max_width: float,
        color: str = BLUE,
        size: int = 20,
    ) -> float:
        yy = y
        for item in items:
            self.draw.ellipse(self.box(x, yy + 9, 8, 8), fill=color)
            yy = self.wrapped_text(x + 18, yy, item, max_width - 18, size=size, fill=SLATE, line_gap=7)
            yy += 7
        return yy


def draw_train(board: Board, x: float, y: float, w: float, h: float) -> None:
    d = board.draw
    s = board.s
    body = [
        (x + 40, y + h * 0.62),
        (x + 95, y + h * 0.38),
        (x + w * 0.74, y + h * 0.32),
        (x + w - 95, y + h * 0.42),
        (x + w - 35, y + h * 0.58),
        (x + w - 100, y + h * 0.72),
        (x + 80, y + h * 0.75),
    ]
    d.polygon([(s(px), s(py)) for px, py in body], fill="#EAF6FF", outline="#7DB8E8")
    d.polygon(
        [(s(x + 108), s(y + h * 0.43)), (s(x + w * 0.38), s(y + h * 0.38)), (s(x + w * 0.34), s(y + h * 0.5)), (s(x + 92), s(y + h * 0.54))],
        fill="#14243F",
    )
    for i in range(7):
        xx = x + w * 0.4 + i * w * 0.055
        d.rounded_rectangle(board.box(xx, y + h * 0.39, w * 0.036, h * 0.078), radius=s(6), fill="#17365F")
    d.line([(s(x + 90), s(y + h * 0.64)), (s(x + w - 92), s(y + h * 0.54))], fill=CYAN, width=s(8))
    d.line([(s(x + 130), s(y + h * 0.68)), (s(x + w - 150), s(y + h * 0.68))], fill=LIME, width=s(6))
    for i in range(4):
        cx = x + 170 + i * 145
        d.ellipse(board.box(cx, y + h * 0.72, 34, 34), fill="#1E293B")
        d.ellipse(board.box(cx + 8, y + h * 0.72 + 8, 18, 18), fill="#94A3B8")


def draw_pain_card(board: Board, x: float, y: float, w: float, h: float, index: str, title: str, body: str, color: str) -> None:
    board.shadow_card(x, y, w, h, radius=16)
    board.draw.ellipse(board.box(x + 26, y + 26, 58, 58), fill=color)
    board.text((x + 55, y + 37), index, 22, "#FFFFFF", True, anchor="ma")
    board.text((x + 102, y + 28), title, 26, NAVY, True)
    board.wrapped_text(x + 30, y + 105, body, w - 60, size=21, fill=SLATE, line_gap=8)


def draw_stage_flow(board: Board, x: float, y: float, w: float, h: float) -> None:
    board.shadow_card(x, y, w, h, radius=20, fill="#FBFDFF")
    draw_train(board, x + 950, y + 24, 620, 170)
    board.text((x + 36, y + 30), "Co-Track：把远程外观设计组织成连续协作流程", 29, NAVY, True)
    board.wrapped_text(
        x + 36,
        y + 75,
        "以“设计目标与基准模型”为共同参照，让个人创作、公共共享、角色评审和成果导出在同一系统中衔接。",
        850,
        size=20,
        fill=MUTED,
        line_gap=7,
    )
    stages = [
        ("S1", "目标解析\n模型锁定", "结构化 Brief\n统一基准模型", BLUE),
        ("S2", "方案创作\n共享迭代", "2D 画布 / 3D 预览\nAI 纹理与图案", TEAL),
        ("S3", "集中评估\n角色评审", "方案墙 / 投票\n工程师与乘客 Agent", PURPLE),
        ("S4", "场景渲染\n成果导出", "渲染图 / 视频\n贴图与报告包", GREEN),
    ]
    card_w = (w - 110) / 4
    yy = y + 190
    for i, (code, title, desc, color) in enumerate(stages):
        xx = x + 36 + i * (card_w + 18)
        board.draw.rounded_rectangle(board.box(xx, yy, card_w, 170), radius=board.s(14), fill="#FFFFFF", outline=color, width=board.s(2))
        board.draw.rounded_rectangle(board.box(xx + 18, yy + 18, 70, 34), radius=board.s(17), fill=color)
        board.text((xx + 53, yy + 24), code, 18, "#FFFFFF", True, anchor="ma")
        title_y = yy + 65
        for line in title.split("\n"):
            board.text((xx + 20, title_y), line, 24, NAVY, True)
            title_y += 31
        desc_y = yy + 124
        for line in desc.split("\n"):
            board.text((xx + 20, desc_y), line, 17, MUTED, False)
            desc_y += 23
        if i < 3:
            board.arrow(xx + card_w + 3, yy + 85, xx + card_w + 17, yy + 85, fill="#94A3B8", width=3)

    board.draw.rounded_rectangle(board.box(x + 36, y + 385, w - 72, 48), radius=board.s(24), fill="#EFF6FF", outline="#BFDBFE")
    board.text((x + 64, y + 397), "信息链：目标 / 约束 / 基准模型 → 个人方案版本 → 公共方案区 → Agent 反馈与团队决策 → 可交付成果包", 20, BLUE, True)


def mock_window(board: Board, x: float, y: float, w: float, h: float, title: str, accent: str) -> None:
    board.shadow_card(x, y, w, h, radius=16, fill="#FFFFFF")
    board.draw.rounded_rectangle(board.box(x, y, w, 48), radius=board.s(16), fill="#F1F5F9", outline=BORDER)
    board.draw.rectangle(board.box(x, y + 32, w, 16), fill="#F1F5F9")
    for i, c in enumerate([ROSE, AMBER, GREEN]):
        board.draw.ellipse(board.box(x + 20 + i * 22, y + 17, 10, 10), fill=c)
    board.text((x + 92, y + 14), title, 18, NAVY, True)
    board.draw.rounded_rectangle(board.box(x + w - 135, y + 13, 92, 22), radius=board.s(11), fill=accent)
    board.text((x + w - 89, y + 16), "Agent", 12, "#FFFFFF", True, anchor="ma")


def draw_stage1_mock(board: Board, x: float, y: float, w: float, h: float) -> None:
    mock_window(board, x, y, w, h, "阶段一：设计目标解析与基准模型确认", BLUE)
    board.draw.rounded_rectangle(board.box(x + 28, y + 72, w * 0.48, h - 102), radius=board.s(12), fill=LIGHT, outline=BORDER)
    board.text((x + 52, y + 94), "设计任务输入", 18, NAVY, True)
    board.draw.rounded_rectangle(board.box(x + 52, y + 128, w * 0.38, 82), radius=board.s(8), fill="#FFFFFF", outline="#CBD5E1")
    board.wrapped_text(x + 70, y + 145, "冬季主题，高铁外观涂装，蓝白配色，强调速度感与亲和力。", w * 0.34, 15, MUTED, line_gap=4)
    board.text((x + 52, y + 236), "解析结果", 17, NAVY, True)
    chips = [("设计意图", BLUE), ("视觉方向", TEAL), ("约束边界", AMBER)]
    for i, (label, color) in enumerate(chips):
        board.draw.rounded_rectangle(board.box(x + 52, y + 268 + i * 42, 150, 28), radius=board.s(14), fill=color)
        board.text((x + 127, y + 273 + i * 42), label, 13, "#FFFFFF", True, anchor="ma")
    board.draw.rounded_rectangle(board.box(x + w * 0.56, y + 72, w * 0.37, h - 102), radius=board.s(12), fill="#F8FAFC", outline=BORDER)
    board.text((x + w * 0.59, y + 94), "基准模型", 18, NAVY, True)
    draw_train(board, x + w * 0.6, y + 134, w * 0.29, 135)
    board.draw.rounded_rectangle(board.box(x + w * 0.61, y + 303, w * 0.25, 38), radius=board.s(19), fill="#DCFCE7")
    board.text((x + w * 0.735, y + 312), "已锁定 · 后续统一使用", 14, GREEN, True, anchor="ma")


def draw_stage2_mock(board: Board, x: float, y: float, w: float, h: float) -> None:
    mock_window(board, x, y, w, h, "阶段二：个人方案创作与公共区共享", TEAL)
    board.draw.rounded_rectangle(board.box(x + 24, y + 70, 170, h - 98), radius=board.s(12), fill="#ECFEFF", outline="#A5F3FC")
    board.text((x + 44, y + 94), "纹理生成", 16, NAVY, True)
    for i, text in enumerate(["主题提示", "参考图", "局部优化"]):
        board.draw.rounded_rectangle(board.box(x + 44, y + 128 + i * 54, 120, 32), radius=board.s(8), fill="#FFFFFF", outline="#BAE6FD")
        board.text((x + 104, y + 136 + i * 54), text, 13, TEAL, True, anchor="ma")
    board.draw.rounded_rectangle(board.box(x + 220, y + 70, 330, h - 98), radius=board.s(12), fill="#FFFFFF", outline="#CBD5E1")
    board.text((x + 242, y + 94), "二维涂装画布", 16, NAVY, True)
    board.draw.rectangle(board.box(x + 250, y + 134, 270, 170), fill="#EEF2FF", outline="#CBD5E1")
    board.line([(x + 270, y + 260), (x + 348, y + 174), (x + 452, y + 244), (x + 520, y + 170)], fill=CYAN, width=7)
    board.line([(x + 260, y + 294), (x + 505, y + 294)], fill=LIME, width=5)
    board.draw.rounded_rectangle(board.box(x + 584, y + 70, 170, 142), radius=board.s(12), fill="#F8FAFC", outline=BORDER)
    board.text((x + 610, y + 92), "3D 预览", 16, NAVY, True)
    draw_train(board, x + 604, y + 124, 120, 68)
    board.draw.rounded_rectangle(board.box(x + 584, y + 236, 170, 118), radius=board.s(12), fill="#F8FAFC", outline=BORDER)
    board.text((x + 610, y + 258), "公共方案区", 16, NAVY, True)
    for i in range(3):
        board.draw.rounded_rectangle(board.box(x + 610 + i * 42, y + 295, 30, 30), radius=board.s(6), fill=["#DBEAFE", "#DCFCE7", "#FEF3C7"][i], outline="#CBD5E1")


def draw_stage3_mock(board: Board, x: float, y: float, w: float, h: float) -> None:
    mock_window(board, x, y, w, h, "阶段三：集中评估与多角色 Agent 评审", PURPLE)
    for i in range(3):
        yy = y + 78 + i * 92
        board.draw.rounded_rectangle(board.box(x + 28, yy, 190, 70), radius=board.s(10), fill="#F8FAFC", outline=BORDER)
        board.draw.rounded_rectangle(board.box(x + 46, yy + 18, 44, 34), radius=board.s(6), fill=["#DBEAFE", "#DCFCE7", "#FFE4E6"][i])
        board.text((x + 106, yy + 18), f"方案 {i + 1}", 15, NAVY, True)
        board.text((x + 106, yy + 42), "版本 / 作者 / 评分", 12, MUTED, False)
    board.draw.rounded_rectangle(board.box(x + 250, y + 78, 260, 254), radius=board.s(12), fill="#FFFFFF", outline="#CBD5E1")
    draw_train(board, x + 282, y + 124, 200, 125)
    board.text((x + 286, y + 284), "统一载体下比较方案", 15, NAVY, True)
    board.draw.rounded_rectangle(board.box(x + 540, y + 78, 220, 254), radius=board.s(12), fill="#FAF5FF", outline="#DDD6FE")
    board.text((x + 566, y + 104), "角色反馈", 17, NAVY, True)
    board.bullet_list(x + 566, y + 142, ["工程可行性", "乘客视觉感受", "品牌识别度", "修改建议绑定方案"], 170, color=PURPLE, size=14)


def draw_stage4_mock(board: Board, x: float, y: float, w: float, h: float) -> None:
    mock_window(board, x, y, w, h, "阶段四：场景渲染与成果导出", GREEN)
    board.draw.rounded_rectangle(board.box(x + 34, y + 82, 438, 240), radius=board.s(14), fill="#E0F2FE", outline="#BAE6FD")
    board.draw.rectangle(board.box(x + 34, y + 250, 438, 72), fill="#CBD5E1")
    draw_train(board, x + 84, y + 154, 330, 145)
    board.text((x + 64, y + 104), "场景预览", 18, NAVY, True)
    board.draw.rounded_rectangle(board.box(x + 520, y + 82, 224, 55), radius=board.s(12), fill="#DCFCE7", outline="#BBF7D0")
    board.text((x + 632, y + 100), "渲染图 PNG", 15, GREEN, True, anchor="ma")
    board.draw.rounded_rectangle(board.box(x + 520, y + 158, 224, 55), radius=board.s(12), fill="#EFF6FF", outline="#BFDBFE")
    board.text((x + 632, y + 176), "模型 / 贴图", 15, BLUE, True, anchor="ma")
    board.draw.rounded_rectangle(board.box(x + 520, y + 234, 224, 55), radius=board.s(12), fill="#FEF3C7", outline="#FDE68A")
    board.text((x + 632, y + 252), "报告与成果包", 15, AMBER, True, anchor="ma")


def draw_agent_mechanism(board: Board, x: float, y: float, w: float, h: float) -> None:
    board.shadow_card(x, y, w, h, radius=18)
    board.text((x + 28, y + 28), "Agent 协作机制", 26, NAVY, True)
    board.text((x + 28, y + 66), "辅助参与，不替代团队判断", 17, MUTED, False)
    cx, cy = x + w * 0.5, y + h * 0.53
    board.draw.ellipse(board.box(cx - 70, cy - 70, 140, 140), fill=NAVY)
    board.text((cx, cy - 18), "设计团队", 20, "#FFFFFF", True, anchor="ma")
    board.text((cx, cy + 16), "采纳 / 修改 / 忽略", 13, "#BFEFFF", False, anchor="ma")
    nodes = [
        ("目标解析", BLUE, -150, -112),
        ("纹理规划", TEAL, 120, -112),
        ("图案生成", AMBER, 150, 55),
        ("角色评审", PURPLE, -146, 58),
        ("效果渲染", GREEN, 0, 148),
    ]
    for label, color, dx, dy in nodes:
        nx, ny = cx + dx, cy + dy
        board.line([(cx, cy), (nx, ny)], fill="#CBD5E1", width=2)
        board.draw.rounded_rectangle(board.box(nx - 62, ny - 24, 124, 48), radius=board.s(24), fill=color)
        board.text((nx, ny - 9), label, 16, "#FFFFFF", True, anchor="ma")


def draw_info_mechanism(board: Board, x: float, y: float, w: float, h: float) -> None:
    board.shadow_card(x, y, w, h, radius=18)
    board.text((x + 28, y + 28), "设计信息组织", 26, NAVY, True)
    board.text((x + 28, y + 66), "让信息在阶段之间可见、可比较、可追踪", 17, MUTED)
    lanes = [
        ("团队参照", "目标、约束、基准模型", BLUE),
        ("个人工作区", "二维画布、纹理、版本", TEAL),
        ("公共方案区", "共享、复制、评论、再创作", AMBER),
        ("评审记录", "角色意见与团队决策绑定方案", PURPLE),
        ("成果包", "贴图、渲染图、视频、报告", GREEN),
    ]
    yy = y + 120
    for i, (title, desc, color) in enumerate(lanes):
        board.draw.rounded_rectangle(board.box(x + 36, yy + i * 63, w - 72, 44), radius=board.s(10), fill="#F8FAFC", outline="#E2E8F0")
        board.draw.rounded_rectangle(board.box(x + 52, yy + 10 + i * 63, 80, 24), radius=board.s(12), fill=color)
        board.text((x + 92, yy + 13 + i * 63), title, 12, "#FFFFFF", True, anchor="ma")
        board.text((x + 150, yy + 11 + i * 63), desc, 16, SLATE, False)
        if i < len(lanes) - 1:
            board.arrow(x + w - 66, yy + 43 + i * 63, x + w - 66, yy + 58 + i * 63, fill="#94A3B8", width=2)


def draw_tech_stack(board: Board, x: float, y: float, w: float, h: float) -> None:
    board.shadow_card(x, y, w, h, radius=18)
    board.text((x + 28, y + 28), "系统实现", 26, NAVY, True)
    board.text((x + 28, y + 66), "前后端分离 + 实时协作 + 多模态 AI 服务", 17, MUTED)
    rows = [
        ("前端工作台", "React / TypeScript / Vite", BLUE),
        ("画布与预览", "Fabric.js / Three.js", TEAL),
        ("后端服务", "FastAPI / Socket.IO / SQLAlchemy", GREEN),
        ("资源管线", "GLB · UV 模板 · 贴图 · 渲染媒体", AMBER),
        ("AI Provider", "文本、图像、3D、角色评审统一适配", PURPLE),
    ]
    yy = y + 122
    for i, (label, desc, color) in enumerate(rows):
        board.draw.rounded_rectangle(board.box(x + 36, yy + i * 62, w - 72, 44), radius=board.s(11), fill="#FFFFFF", outline="#DDE7F3")
        board.draw.ellipse(board.box(x + 56, yy + 12 + i * 62, 20, 20), fill=color)
        board.text((x + 92, yy + 10 + i * 62), label, 16, NAVY, True)
        board.text((x + 220, yy + 10 + i * 62), desc, 15, MUTED, False)


def draw_metric_card(board: Board, x: float, y: float, w: float, h: float) -> None:
    board.shadow_card(x, y, w, h, radius=18)
    board.text((x + 30, y + 28), "系统评估与初步验证", 27, NAVY, True)
    board.text((x + 30, y + 66), "12 名设计相关背景参与者 · 3 组协作测试 · SUS + 自编量表 + 半结构化访谈", 17, MUTED)
    board.draw.rounded_rectangle(board.box(x + 32, y + 108, 190, 92), radius=board.s(14), fill=NAVY)
    board.text((x + 127, y + 124), "SUS", 18, "#BFEFFF", True, anchor="ma")
    board.text((x + 127, y + 150), "76.25", 34, "#FFFFFF", True, anchor="ma")
    board.text((x + 127, y + 184), "较好可用性", 13, "#D7E90E", True, anchor="ma")
    metrics = [
        ("流程连续性", 4.28, BLUE),
        ("信息表达共享", 4.06, TEAL),
        ("方案共享延续", 3.83, AMBER),
        ("Agent 反馈支持", 3.39, PURPLE),
    ]
    bx, by = x + 260, y + 126
    for i, (label, val, color) in enumerate(metrics):
        yy = by + i * 58
        board.text((bx, yy), label, 17, NAVY, True)
        board.draw.rounded_rectangle(board.box(bx + 155, yy + 4, 330, 18), radius=board.s(9), fill="#E2E8F0")
        board.draw.rounded_rectangle(board.box(bx + 155, yy + 4, 330 * (val / 5), 18), radius=board.s(9), fill=color)
        board.text((bx + 500, yy - 2), f"{val:.2f}/5", 18, color, True)
    board.text((x + 32, y + 344), "结论", 20, NAVY, True)
    board.bullet_list(
        x + 32,
        y + 382,
        [
            "阶段化流程帮助团队判断当前任务，降低多工具切换带来的协作成本。",
            "二维画布、三维预览、渲染媒体共同增强方案表达与团队理解。",
            "角色 Agent 能补充工程与用户视角，但反馈具体性仍需继续优化。",
        ],
        w - 70,
        color=GREEN,
        size=16,
    )


def draw_qualitative_card(board: Board, x: float, y: float, w: float, h: float) -> None:
    board.shadow_card(x, y, w, h, radius=18)
    board.text((x + 30, y + 28), "用户反馈摘要", 27, NAVY, True)
    quotes = [
        ("阶段清楚", "不用一直问现在是发散还是收敛，大家比较容易跟上流程。"),
        ("表达有序", "文字、二维、三维和渲染结果被组织在一起，更容易理解方案。"),
        ("边界明确", "Agent 提供提醒，但最终仍由团队决定是否修改。"),
    ]
    yy = y + 80
    for label, quote in quotes:
        board.draw.rounded_rectangle(board.box(x + 30, yy, w - 60, 86), radius=board.s(14), fill="#F8FAFC", outline="#E2E8F0")
        board.draw.rounded_rectangle(board.box(x + 50, yy + 18, 94, 28), radius=board.s(14), fill=NAVY_2)
        board.text((x + 97, yy + 24), label, 13, "#FFFFFF", True, anchor="ma")
        board.wrapped_text(x + 164, yy + 17, quote, w - 215, size=18, fill=SLATE, line_gap=5)
        yy += 106
    board.draw.rounded_rectangle(board.box(x + 30, y + 398, w - 60, 70), radius=board.s(13), fill="#FFF7ED", outline="#FED7AA")
    board.text((x + 58, y + 412), "创新点：场景创新 / 流程创新 / 表达创新 / 协同创新", 18, "#9A3412", True)
    board.text((x + 58, y + 442), "后续优化：版本差异可视化、角色模板引导、生成进度与质量控制。", 16, "#9A3412", False)


def draw_innovation(board: Board, x: float, y: float, w: float, h: float) -> None:
    items = [
        ("场景创新", "面向高铁等复杂工业产品外观涂装，而非普通平面或 UI 协作。", BLUE),
        ("流程创新", "将目标设定、创作、共享评审与成果输出组织为连续阶段。", TEAL),
        ("表达创新", "团队参照与个人方案并行管理，支持多模态信息延续。", AMBER),
        ("协同创新", "Agent 作为不在场角色提供反馈，辅助方案演化与收敛。", PURPLE),
    ]
    gap = 22
    card_w = (w - gap * 3) / 4
    for i, (title, desc, color) in enumerate(items):
        xx = x + i * (card_w + gap)
        board.shadow_card(xx, y, card_w, h, radius=16)
        board.draw.rounded_rectangle(board.box(xx + 24, y + 24, 108, 32), radius=board.s(16), fill=color)
        board.text((xx + 78, y + 31), title, 14, "#FFFFFF", True, anchor="ma")
        board.wrapped_text(xx + 24, y + 82, desc, card_w - 48, size=18, fill=SLATE, line_gap=7)


def draw_board(board: Board) -> None:
    left, right = 96, 1747
    width = right - left

    board.text((left, 286), "分布式场景下产品外观 Agent 协作设计平台研究", 52, NAVY, True)
    board.text((left, 354), "以高铁外观涂装设计为例 · Co-Track Integrated Agent Collaboration System", 24, MUTED)
    x_chip = 1210
    for label, color in [("连续流程", BLUE), ("多模态表达", TEAL), ("多角色反馈", PURPLE)]:
        used = board.chip(x_chip, 290, label, color, size=17)
        x_chip += used + 12
    board.draw.rounded_rectangle(board.box(left, 413, width, 58), radius=board.s(18), fill="#F8FAFC", outline="#E2E8F0")
    board.text((left + 28, 429), "核心命题：如何让分布式设计团队在同一协作空间中完成外观方案生成、协同演化与成果交付？", 23, NAVY, True)

    board.section_title(left, 520, "01", "研究痛点", "复杂工业产品外观设计中的远程协作断点")
    pain_y = 625
    card_w = (width - 36) / 3
    draw_pain_card(board, left, pain_y, card_w, 235, "1", "流程割裂", "会议、绘图、AI 生成、文档与评审分散在不同工具，目标与反馈难以持续作用于后续阶段。", BLUE)
    draw_pain_card(board, left + card_w + 18, pain_y, card_w, 235, "2", "表达不足", "外观方案同时涉及文字、二维纹理、三维载体与场景效果，零散材料难以被团队充分理解和比较。", TEAL)
    draw_pain_card(board, left + (card_w + 18) * 2, pain_y, card_w, 235, "3", "反馈滞后", "工程、用户、品牌等重要视角无法持续在场，问题常在方案成型后才被发现，增加返工成本。", ROSE)
    board.shadow_card(left, 890, width, 90, radius=18, fill=NAVY)
    board.text((left + 30, 915), "研究目标", 24, LIME, True)
    board.text((left + 160, 916), "构建面向交通工具外观涂装设计的集成式 Agent 协同系统，支持流程连续、信息延续与多角色反馈介入。", 22, "#FFFFFF", True)

    board.section_title(left, 1028, "02", "系统方案", "四阶段协作流程将目标、方案、反馈与成果串联起来")
    draw_stage_flow(board, left, 1132, width, 455)

    board.section_title(left, 1645, "03", "核心界面", "从任务解析到成果导出的功能闭环")
    mock_w = (width - 28) / 2
    draw_stage1_mock(board, left, 1750, mock_w, 392)
    draw_stage2_mock(board, left + mock_w + 28, 1750, mock_w, 392)
    draw_stage3_mock(board, left, 2172, mock_w, 392)
    draw_stage4_mock(board, left + mock_w + 28, 2172, mock_w, 392)

    board.section_title(left, 2618, "04", "关键机制", "Agent、信息组织与技术实现共同支撑协作")
    mech_y = 2722
    mech_w = (width - 44) / 3
    draw_agent_mechanism(board, left, mech_y, mech_w, 470)
    draw_info_mechanism(board, left + mech_w + 22, mech_y, mech_w, 470)
    draw_tech_stack(board, left + (mech_w + 22) * 2, mech_y, mech_w, 470)

    board.section_title(left, 3240, "05", "评估验证", "可用性、协作支持感知与访谈结果")
    eval_y = 3344
    draw_metric_card(board, left, eval_y, 820, 500)
    draw_qualitative_card(board, left + 850, eval_y, width - 850, 500)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--scale", type=int, default=1, choices=[1, 2])
    parser.add_argument("--template", type=Path, default=BASE_TEMPLATE)
    parser.add_argument("--out", type=Path, default=None)
    args = parser.parse_args()

    out = args.out or OUT_DIR / ("co_track_graduation_board@2x.png" if args.scale == 2 else "co_track_graduation_board.png")
    board = Board(args.template, args.scale)
    draw_board(board)
    board.img.save(out)
    print(out)
    print(f"{board.img.size[0]}x{board.img.size[1]}")


if __name__ == "__main__":
    main()
