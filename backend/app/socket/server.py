from typing import Any

import socketio
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.security import decode_access_token
from app.db.models import SessionMember, User
from app.db.session import SessionLocal
from app.socket.state import MeetingHub, PeerMediaState

settings = get_settings()
hub = MeetingHub(max_members=6)
_socket_server: socketio.AsyncServer | None = None


def meeting_room(session_id: int) -> str:
    return f"meeting:{session_id}"


async def emit_session_event(event: str, session_id: int, payload: dict[str, Any]) -> None:
    if _socket_server is None:
        return
    data = {"session_id": session_id, **payload}
    try:
        await _socket_server.emit(event, data, room=meeting_room(session_id))
    except Exception:
        # Socket push failure should never break main REST workflow.
        return


def _fetch_member(db: Session, session_id: int, user_id: int) -> SessionMember | None:
    return db.execute(
        select(SessionMember).where(
            SessionMember.session_id == session_id,
            SessionMember.user_id == user_id,
        )
    ).scalar_one_or_none()


def _is_host(db: Session, session_id: int, user_id: int) -> bool:
    member = db.execute(
        select(SessionMember).where(
            SessionMember.session_id == session_id,
            SessionMember.user_id == user_id,
            SessionMember.role == "host",
        )
    ).scalar_one_or_none()
    return member is not None


def create_socket_server() -> socketio.AsyncServer:
    global _socket_server
    sio = socketio.AsyncServer(async_mode="asgi", cors_allowed_origins="*")
    _socket_server = sio

    @sio.event
    async def connect(sid: str, environ: dict[str, Any], auth: dict[str, Any] | None) -> bool:
        token = (auth or {}).get("token")
        if not token:
            raise ConnectionRefusedError("Missing token")

        try:
            payload = decode_access_token(token)
            user_id = int(payload.get("sub", "0"))
        except Exception as exc:  # noqa: BLE001
            raise ConnectionRefusedError("Invalid token") from exc

        with SessionLocal() as db:
            user = db.execute(select(User).where(User.id == user_id)).scalar_one_or_none()
            if user is None:
                raise ConnectionRefusedError("User not found")
            await sio.save_session(sid, {"user_id": user.id, "name": user.name, "email": user.email})
        return True

    @sio.event
    async def disconnect(sid: str) -> None:
        removed = hub.leave_by_sid(sid)
        for session_id, peer in removed:
            await sio.emit(
                "meeting:peer_left",
                {"session_id": session_id, "user_id": peer.user_id},
                room=meeting_room(session_id),
            )

    @sio.on("meeting:media_join")
    async def meeting_media_join(sid: str, data: dict[str, Any]) -> dict[str, Any]:
        session_data = await sio.get_session(sid)
        user_id = int(session_data["user_id"])
        name = str(session_data["name"])
        session_id = int(data.get("session_id", 0))
        audio_enabled = bool(data.get("audio_enabled", False))
        video_enabled = bool(data.get("video_enabled", False))

        with SessionLocal() as db:
            member = _fetch_member(db, session_id, user_id)
            if member is None:
                return {"ok": False, "error": "NOT_SESSION_MEMBER"}

            peer = PeerMediaState(
                user_id=user_id,
                name=name,
                role=member.role,
                sid=sid,
                audio_enabled=audio_enabled,
                video_enabled=video_enabled,
                speak_granted=member.role != "observer",
            )
            ok, error, peers = hub.join(session_id, peer)
            if not ok:
                return {"ok": False, "error": error}

        await sio.enter_room(sid, meeting_room(session_id))
        current_peer = hub.get_peer(session_id, user_id)
        if current_peer:
            await sio.emit(
                "meeting:peer_joined",
                {"session_id": session_id, "peer": current_peer.to_public()},
                room=meeting_room(session_id),
                skip_sid=sid,
            )

        return {
            "ok": True,
            "session_id": session_id,
            "self": current_peer.to_public() if current_peer else None,
            "peers": peers,
            "room_size": hub.room_size(session_id),
            "limit": hub.max_members,
            "ice_servers": settings.rtc_ice_servers,
        }

    @sio.on("meeting:media_leave")
    async def meeting_media_leave(sid: str, data: dict[str, Any]) -> dict[str, Any]:
        session_data = await sio.get_session(sid)
        user_id = int(session_data["user_id"])
        session_id = int(data.get("session_id", 0))
        peer = hub.leave(session_id, user_id)
        await sio.leave_room(sid, meeting_room(session_id))
        if peer:
            await sio.emit(
                "meeting:peer_left",
                {"session_id": session_id, "user_id": peer.user_id},
                room=meeting_room(session_id),
            )
        return {"ok": True}

    @sio.on("webrtc:offer")
    async def webrtc_offer(sid: str, data: dict[str, Any]) -> None:
        session_data = await sio.get_session(sid)
        from_user_id = int(session_data["user_id"])
        session_id = int(data.get("session_id", 0))
        target_user_id = int(data.get("to_user_id", 0))
        if hub.get_peer(session_id, from_user_id) is None:
            return
        target_sid = hub.get_target_sid(session_id, target_user_id)
        if target_sid is None:
            return
        await sio.emit(
            "webrtc:offer",
            {
                "session_id": session_id,
                "from_user_id": from_user_id,
                "sdp": data.get("sdp"),
            },
            room=target_sid,
        )

    @sio.on("webrtc:answer")
    async def webrtc_answer(sid: str, data: dict[str, Any]) -> None:
        session_data = await sio.get_session(sid)
        from_user_id = int(session_data["user_id"])
        session_id = int(data.get("session_id", 0))
        target_user_id = int(data.get("to_user_id", 0))
        if hub.get_peer(session_id, from_user_id) is None:
            return
        target_sid = hub.get_target_sid(session_id, target_user_id)
        if target_sid is None:
            return
        await sio.emit(
            "webrtc:answer",
            {
                "session_id": session_id,
                "from_user_id": from_user_id,
                "sdp": data.get("sdp"),
            },
            room=target_sid,
        )

    @sio.on("webrtc:ice_candidate")
    async def webrtc_ice_candidate(sid: str, data: dict[str, Any]) -> None:
        session_data = await sio.get_session(sid)
        from_user_id = int(session_data["user_id"])
        session_id = int(data.get("session_id", 0))
        target_user_id = int(data.get("to_user_id", 0))
        if hub.get_peer(session_id, from_user_id) is None:
            return
        target_sid = hub.get_target_sid(session_id, target_user_id)
        if target_sid is None:
            return
        await sio.emit(
            "webrtc:ice_candidate",
            {
                "session_id": session_id,
                "from_user_id": from_user_id,
                "candidate": data.get("candidate"),
            },
            room=target_sid,
        )

    @sio.on("media:toggle")
    async def media_toggle(sid: str, data: dict[str, Any]) -> dict[str, Any]:
        session_data = await sio.get_session(sid)
        user_id = int(session_data["user_id"])
        session_id = int(data.get("session_id", 0))
        peer = hub.update_media(
            session_id=session_id,
            user_id=user_id,
            audio_enabled=bool(data.get("audio_enabled", False)),
            video_enabled=bool(data.get("video_enabled", False)),
        )
        if peer is None:
            return {"ok": False, "error": "NOT_IN_MEETING"}
        await sio.emit(
            "media:peer_state",
            {"session_id": session_id, "peer": peer.to_public()},
            room=meeting_room(session_id),
        )
        return {"ok": True}

    @sio.on("media:speak_request")
    async def media_speak_request(sid: str, data: dict[str, Any]) -> dict[str, Any]:
        session_data = await sio.get_session(sid)
        user_id = int(session_data["user_id"])
        session_id = int(data.get("session_id", 0))
        peer = hub.set_hand_raised(session_id, user_id, True)
        if peer is None:
            return {"ok": False, "error": "NOT_IN_MEETING"}
        await sio.emit(
            "media:peer_state",
            {"session_id": session_id, "peer": peer.to_public()},
            room=meeting_room(session_id),
        )
        return {"ok": True}

    @sio.on("media:speak_approve")
    async def media_speak_approve(sid: str, data: dict[str, Any]) -> dict[str, Any]:
        session_data = await sio.get_session(sid)
        approver_id = int(session_data["user_id"])
        session_id = int(data.get("session_id", 0))
        target_user_id = int(data.get("target_user_id", 0))

        with SessionLocal() as db:
            if not _is_host(db, session_id, approver_id):
                return {"ok": False, "error": "FORBIDDEN"}

        peer = hub.grant_speak(session_id, target_user_id)
        if peer is None:
            return {"ok": False, "error": "TARGET_NOT_FOUND"}

        target_sid = hub.get_target_sid(session_id, target_user_id)
        if target_sid:
            await sio.emit(
                "media:speak_granted",
                {"session_id": session_id, "target_user_id": target_user_id},
                room=target_sid,
            )

        await sio.emit(
            "media:peer_state",
            {"session_id": session_id, "peer": peer.to_public()},
            room=meeting_room(session_id),
        )
        return {"ok": True}

    return sio

