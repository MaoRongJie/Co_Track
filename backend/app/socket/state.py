from dataclasses import dataclass, field


@dataclass
class PeerMediaState:
    user_id: int
    name: str
    role: str
    sid: str
    audio_enabled: bool
    video_enabled: bool
    hand_raised: bool = False
    speak_granted: bool = False

    def to_public(self) -> dict[str, object]:
        return {
            "user_id": self.user_id,
            "name": self.name,
            "role": self.role,
            "audio_enabled": self.audio_enabled,
            "video_enabled": self.video_enabled,
            "hand_raised": self.hand_raised,
            "speak_granted": self.speak_granted,
        }


@dataclass
class RoomState:
    peers: dict[int, PeerMediaState] = field(default_factory=dict)


class MeetingHub:
    def __init__(self, max_members: int = 6):
        self.max_members = max_members
        self.rooms: dict[int, RoomState] = {}
        self.sid_memberships: dict[str, set[int]] = {}

    def _ensure_room(self, session_id: int) -> RoomState:
        if session_id not in self.rooms:
            self.rooms[session_id] = RoomState()
        return self.rooms[session_id]

    def join(self, session_id: int, peer: PeerMediaState) -> tuple[bool, str | None, list[dict[str, object]]]:
        room = self._ensure_room(session_id)
        if peer.user_id not in room.peers and len(room.peers) >= self.max_members:
            return False, "ROOM_FULL", []

        existing_peers = [p.to_public() for uid, p in room.peers.items() if uid != peer.user_id]
        room.peers[peer.user_id] = peer
        self.sid_memberships.setdefault(peer.sid, set()).add(session_id)
        return True, None, existing_peers

    def leave(self, session_id: int, user_id: int) -> PeerMediaState | None:
        room = self.rooms.get(session_id)
        if room is None:
            return None
        peer = room.peers.pop(user_id, None)
        if peer is not None and peer.sid in self.sid_memberships:
            if session_id in self.sid_memberships[peer.sid]:
                self.sid_memberships[peer.sid].remove(session_id)
            if not self.sid_memberships[peer.sid]:
                self.sid_memberships.pop(peer.sid, None)
        if not room.peers:
            self.rooms.pop(session_id, None)
        return peer

    def leave_by_sid(self, sid: str) -> list[tuple[int, PeerMediaState]]:
        removed: list[tuple[int, PeerMediaState]] = []
        session_ids = list(self.sid_memberships.get(sid, set()))
        for session_id in session_ids:
            room = self.rooms.get(session_id)
            if room is None:
                continue
            for user_id, peer in list(room.peers.items()):
                if peer.sid == sid:
                    removed_peer = self.leave(session_id, user_id)
                    if removed_peer:
                        removed.append((session_id, removed_peer))
                    break
        return removed

    def get_peer(self, session_id: int, user_id: int) -> PeerMediaState | None:
        room = self.rooms.get(session_id)
        if room is None:
            return None
        return room.peers.get(user_id)

    def get_peer_by_sid(self, sid: str, session_id: int) -> PeerMediaState | None:
        room = self.rooms.get(session_id)
        if room is None:
            return None
        for peer in room.peers.values():
            if peer.sid == sid:
                return peer
        return None

    def get_target_sid(self, session_id: int, target_user_id: int) -> str | None:
        peer = self.get_peer(session_id, target_user_id)
        return peer.sid if peer else None

    def room_size(self, session_id: int) -> int:
        room = self.rooms.get(session_id)
        return len(room.peers) if room else 0

    def update_media(self, session_id: int, user_id: int, audio_enabled: bool, video_enabled: bool) -> PeerMediaState | None:
        peer = self.get_peer(session_id, user_id)
        if peer is None:
            return None
        peer.audio_enabled = audio_enabled
        peer.video_enabled = video_enabled
        return peer

    def set_hand_raised(self, session_id: int, user_id: int, hand_raised: bool) -> PeerMediaState | None:
        peer = self.get_peer(session_id, user_id)
        if peer is None:
            return None
        peer.hand_raised = hand_raised
        return peer

    def grant_speak(self, session_id: int, user_id: int) -> PeerMediaState | None:
        peer = self.get_peer(session_id, user_id)
        if peer is None:
            return None
        peer.speak_granted = True
        peer.hand_raised = False
        return peer

