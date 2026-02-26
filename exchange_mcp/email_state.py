"""Email state management — JSON file persistence."""

import json
import time
from pathlib import Path
from typing import Any


def _state_dir() -> Path:
    d = Path.home() / ".nanobot" / "data" / "exchange" / "emails"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _safe_filename(email_id: str) -> str:
    safe = email_id.replace("/", "_").replace("\\", "_").replace(":", "_")
    if len(safe) > 200:
        import hashlib
        safe = hashlib.sha256(email_id.encode()).hexdigest()
    return safe


def read_state(email_id: str) -> dict[str, Any]:
    path = _state_dir() / f"{_safe_filename(email_id)}.json"
    if not path.exists():
        return {"status": "not_found", "email_id": email_id}
    return json.loads(path.read_text(encoding="utf-8"))


def write_state(email_id: str, status: str, **fields: Any) -> dict[str, Any]:
    path = _state_dir() / f"{_safe_filename(email_id)}.json"
    existing: dict[str, Any] = {}
    if path.exists():
        existing = json.loads(path.read_text(encoding="utf-8"))
    existing["email_id"] = email_id
    existing["status"] = status
    existing["updated_at"] = time.strftime("%Y-%m-%dT%H:%M:%S")
    if "created_at" not in existing:
        existing["created_at"] = existing["updated_at"]
    for k, v in fields.items():
        if v is not None:
            existing[k] = v
    path.write_text(json.dumps(existing, ensure_ascii=False, indent=2), encoding="utf-8")
    return {"ok": True, "email_id": email_id, "status": status}


def list_states(status_filter: str = "", limit: int = 20) -> list[dict[str, Any]]:
    results = []
    for p in sorted(_state_dir().glob("*.json"), key=lambda x: x.stat().st_mtime, reverse=True):
        if len(results) >= limit:
            break
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
            if status_filter and data.get("status") != status_filter:
                continue
            results.append({
                "email_id": data.get("email_id", ""),
                "status": data.get("status", "unknown"),
                "subject": data.get("subject", ""),
                "sender": data.get("sender", ""),
                "updated_at": data.get("updated_at", ""),
            })
        except Exception:
            continue
    return results
