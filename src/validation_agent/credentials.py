from __future__ import annotations
import json
from dataclasses import asdict, dataclass
from pathlib import Path
DEFAULT_STORE = Path.home() / ".validation_agent" / "credentials.json"
@dataclass
class StoredCredentials:
    subscription_key: str = ""
    api_token: str = ""
    refresh_token: str = ""
    api_version: str = "3.0"
    base_url: str = "https://api.gpt.medtronic.com"
    path_template: str = "/models/{model}"
    model: str = "gpt-41"
def load_credentials(store: Path = DEFAULT_STORE) -> StoredCredentials:
    if not store.exists():
        return StoredCredentials()
    try:
        data = json.loads(store.read_text(encoding="utf-8"))
        return StoredCredentials(**data)
    except Exception:
        return StoredCredentials()
def save_credentials(creds: StoredCredentials, store: Path = DEFAULT_STORE) -> None:
    store.parent.mkdir(parents=True, exist_ok=True)
    store.write_text(json.dumps(asdict(creds), indent=2), encoding="utf-8")