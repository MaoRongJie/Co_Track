from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
from typing import Any


_TRANSIENT_TASKS: dict[int, dict[str, Any]] = {}
_TRANSIENT_MODELS: dict[int, dict[str, Any]] = {}
_TRANSIENT_TASK_SEQ = 0
_TRANSIENT_MODEL_SEQ = 0


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def next_transient_task_id() -> int:
    global _TRANSIENT_TASK_SEQ
    _TRANSIENT_TASK_SEQ -= 1
    return _TRANSIENT_TASK_SEQ


def next_transient_model_id() -> int:
    global _TRANSIENT_MODEL_SEQ
    _TRANSIENT_MODEL_SEQ -= 1
    return _TRANSIENT_MODEL_SEQ


def save_transient_task(task_id: int, payload: dict[str, Any]) -> None:
    _TRANSIENT_TASKS[task_id] = deepcopy(payload)


def update_transient_task(task_id: int, **updates: Any) -> dict[str, Any] | None:
    existing = _TRANSIENT_TASKS.get(task_id)
    if existing is None:
        return None
    existing.update(updates)
    existing["updated_at"] = utcnow()
    _TRANSIENT_TASKS[task_id] = existing
    return deepcopy(existing)


def get_transient_task(task_id: int) -> dict[str, Any] | None:
    payload = _TRANSIENT_TASKS.get(task_id)
    return deepcopy(payload) if payload is not None else None


def find_transient_task_by_model_id(model_id: int) -> dict[str, Any] | None:
    for payload in _TRANSIENT_TASKS.values():
        if int(payload.get("model_id") or 0) == model_id:
            return deepcopy(payload)
    return None


def save_transient_model(model_id: int, payload: dict[str, Any]) -> None:
    _TRANSIENT_MODELS[model_id] = deepcopy(payload)


def get_transient_model(model_id: int) -> dict[str, Any] | None:
    payload = _TRANSIENT_MODELS.get(model_id)
    return deepcopy(payload) if payload is not None else None


def clear_transient_session_artifacts(session_id: int) -> None:
    task_ids = [task_id for task_id, payload in _TRANSIENT_TASKS.items() if payload.get("session_id") == session_id]
    for task_id in task_ids:
        _TRANSIENT_TASKS.pop(task_id, None)

    model_ids = [model_id for model_id, payload in _TRANSIENT_MODELS.items() if payload.get("session_id") == session_id]
    for model_id in model_ids:
        _TRANSIENT_MODELS.pop(model_id, None)
