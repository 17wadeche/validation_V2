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
@dataclass
class TelemetryConfig:
    dir_path: str = DEFAULT_TELEMETRY_DIR
    filename: str = DEFAULT_TELEMETRY_FILE
    max_payload_chars: int = 200_000  # keep logs reasonable
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
    dir_path = Path(cfg.dir_path)
    _safe_mkdir(dir_path)
    record: Dict[str, Any] = {
        "id": str(uuid.uuid4()),
        "ts_utc": _utc_now_iso(),
        "event_type": event_type,          # e.g. "gpt_call" / "feedback"
        "action": action,                  # "build" / "chat" / "refine"
        "user": user_name or "unknown",
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
            if isinstance(v, str):
                safe_payload[k] = _truncate(v, cfg.max_payload_chars)
            else:
                safe_payload[k] = v
        record["payload"] = safe_payload
    try:
        out_path = dir_path / cfg.filename
        with open(out_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
    except Exception:
        return
class Timer:
    def __init__(self) -> None:
        self._t0 = time.perf_counter()
    def ms(self) -> int:
        return int((time.perf_counter() - self._t0) * 1000)