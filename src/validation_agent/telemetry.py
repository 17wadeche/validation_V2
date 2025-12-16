from __future__ import annotations
import json
import os
import time
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional
DEFAULT_TELEMETRY_DIR = r"\\hcwda30449e\Validation-Tool\logs"
DEFAULT_TELEMETRY_FILE = "telemetry.jsonl"
def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()
def _safe_mkdir(p: Path) -> None:
    try:
        p.mkdir(parents=True, exist_ok=True)
    except Exception:
        pass
def _truncate(s: str, limit: int) -> str:
    if not s:
        return ""
    s = str(s)
    return s if len(s) <= limit else (s[:limit] + "\n...TRUNCATED...")
def _best_user(user_name: str) -> str:
    u = (user_name or "").strip()
    if u:
        return u
    return os.environ.get("USERNAME") or os.environ.get("USER") or "unknown"
@dataclass
class TelemetryConfig:
    dir_path: str = DEFAULT_TELEMETRY_DIR
    filename: str = DEFAULT_TELEMETRY_FILE
    max_payload_chars: int = 200_000  # keep logs reasonable
    split_by_user: bool = True
    fallback_dir: Path = Path.home() / ".validation_agent" / "telemetry_fallback"
    raise_on_error: bool = False
def log_event(
    event_type: str,
    *,
    user_name: str,
    app_version: str,
    action: str,
    model: str = "",
    duration_ms: Optional[int] = None,
    success: bool = True,
    error: str = "",
    payload: Optional[Dict[str, Any]] = None,
    config: Optional[TelemetryConfig] = None,
) -> None:
    cfg = config or TelemetryConfig()
    dir_path = Path(os.environ.get("TELEMETRY_DIR", cfg.dir_path))
    base_filename = os.environ.get("TELEMETRY_FILE", cfg.filename)
    user = _best_user(user_name)
    filename = base_filename
    if cfg.split_by_user:
        stem = Path(base_filename).stem
        suffix = Path(base_filename).suffix or ".jsonl"
        filename = f"{stem}.{user}{suffix}"  # e.g. telemetry.jdoe.jsonl
    record: Dict[str, Any] = {
        "id": str(uuid.uuid4()),
        "ts_utc": _utc_now_iso(),
        "event_type": event_type,
        "action": action,
        "user": user,
        "app_version": app_version,
        "model": model,
        "duration_ms": duration_ms,
        "success": bool(success),
    }
    if error:
        record["error"] = _truncate(error, 8_000)
    if payload:
        safe_payload: Dict[str, Any] = {}
        for k, v in payload.items():
            safe_payload[k] = _truncate(v, cfg.max_payload_chars) if isinstance(v, str) else v
        record["payload"] = safe_payload
    out_path = dir_path / filename
    try:
        _safe_mkdir(dir_path)
        with open(out_path, "a", encoding="utf-8", newline="\n") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
    except Exception as exc:
        try:
            _safe_mkdir(cfg.fallback_dir)
            fb_path = cfg.fallback_dir / filename
            record["telemetry_write_error"] = str(exc)
            with open(fb_path, "a", encoding="utf-8", newline="\n") as f:
                f.write(json.dumps(record, ensure_ascii=False) + "\n")
        except Exception:
            pass
        if cfg.raise_on_error:
            raise
class Timer:
    def __init__(self) -> None:
        self._t0 = time.perf_counter()
    def ms(self) -> int:
        return int((time.perf_counter() - self._t0) * 1000)