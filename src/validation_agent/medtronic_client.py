from __future__ import annotations
import json
import logging
from dataclasses import dataclass, field
from urllib import error, parse, request
from typing import List
logger = logging.getLogger(__name__)
class MedtronicGPTError(Exception):
    """Raised when the MedtronicGPT service cannot return a completion."""
@dataclass
class MedtronicGPTClient:
    subscription_key: str
    api_token: str
    refresh_token: str
    base_url: str = "https://api.gpt.medtronic.com"
    api_version: str = "3.0"
    path_template: str = "/models/{model}"
    refresh_path: str = "/tokens/refresh"
    temperature: float | None = 0.0
    max_completion_tokens: int | None = None
    last_refresh: bool = field(default=False, init=False)
    DEFAULT_BASE_URL = "https://api.gpt.medtronic.com"
    DEFAULT_API_VERSION = "3.0"
    DEFAULT_PATH_TEMPLATE = "/models/{model}"
    DEFAULT_TEMPERATURE = 0.0
    DEFAULT_MAX_COMPLETION_TOKENS = 32768
    @staticmethod
    def _infer_max_completion_tokens_for_model(model: str) -> int | None:
        if not model:
            return MedtronicGPTClient.DEFAULT_MAX_COMPLETION_TOKENS
        m = model.lower().strip()
        if (
            m.startswith("gpt-5")
            or m.startswith("gpt-4.1")
            or m.startswith("gpt-41")
        ):
            return 32768
        if (
            m == "o3"
            or m.startswith("o3-")
            or m.startswith("o3-mini")
            or m.startswith("o4-mini")
        ):
            return 100_000
        if m.startswith("gpt-4o"):
            return 16_384
        if (
            m.startswith("anthropic.")
            or m.startswith("claude-sonnet")
            or m.startswith("deepseek")
            or m.startswith("pixtral")
            or m.startswith("mistral.")
            or m.startswith("meta.llama4")
            or m.startswith("llama-maverick")
        ):
            return 4_096
        return MedtronicGPTClient.DEFAULT_MAX_COMPLETION_TOKENS
    def generate_completion(
        self,
        prompt: str | None = None,
        *,
        model: str = "gpt-41",
        messages: list[dict] | None = None,
        temperature: float | None = None,
        max_completion_tokens: int | None = None,
    ) -> str:
        self.last_refresh = False
        if messages is None:
            if not prompt or not prompt.strip():
                raise MedtronicGPTError(
                    "Prompt is empty; supply a template, examples, and code context."
                )
            payload_messages = [{"role": "user", "content": prompt}]
        else:
            if not messages:
                raise MedtronicGPTError(
                    "Message history is empty; provide at least one message."
                )
            payload_messages = messages
        def _compute_max_completion_tokens() -> int | None:
            if max_completion_tokens is not None:
                return int(max_completion_tokens)
            if self.max_completion_tokens is not None:
                return int(self.max_completion_tokens)
            inferred = self._infer_max_completion_tokens_for_model(model)
            return int(inferred) if inferred is not None else None
        def _send_once(
            current_api_token: str,
            *,
            include_temperature: bool = True,
            include_max_completion_tokens: bool = True,
        ) -> str:
            path = self.path_template.format(model=parse.quote(model, safe=""))
            if not path.startswith("/"):
                path = f"/{path}"
            url = f"{self.base_url.rstrip('/')}{path}"
            payload_body: dict = {"messages": payload_messages}
            if include_temperature:
                payload_temperature = (
                    temperature if temperature is not None else self.temperature
                )
                if payload_temperature is not None:
                    payload_body["temperature"] = float(payload_temperature)
            if include_max_completion_tokens:
                payload_max_completion_tokens = _compute_max_completion_tokens()
                if payload_max_completion_tokens is not None:
                    payload_body["max_completion_tokens"] = payload_max_completion_tokens
            payload = json.dumps(payload_body).encode("utf-8")
            headers = {
                "Content-Type": "application/json",
                "subscription-key": self.subscription_key,
                "api-token": current_api_token,
                "refresh-token": self.refresh_token,
                "api-version": self.api_version,
            }
            logger.debug(
                "MedtronicGPT request: url=%s include_temperature=%s "
                "include_max_completion_tokens=%s payload=%s",
                url,
                include_temperature,
                include_max_completion_tokens,
                payload_body,
            )
            req = request.Request(url, data=payload, headers=headers)
            with request.urlopen(req) as resp:  # nosec: B310
                body = resp.read().decode("utf-8")
            logger.debug("MedtronicGPT response body: %s", body)
            return self._extract_content(body)
        def _send_with_retry(current_api_token: str) -> str:
            try:
                return _send_once(
                    current_api_token,
                    include_temperature=True,
                    include_max_completion_tokens=True,
                )
            except error.HTTPError as exc1:
                if exc1.code != 400:
                    raise
                logger.warning(
                    "MedtronicGPT 400 with temperature+max_completion_tokens for model %s, "
                    "retrying without temperature...",
                    model,
                )
                try:
                    return _send_once(
                        current_api_token,
                        include_temperature=False,
                        include_max_completion_tokens=True,
                    )
                except error.HTTPError as exc2:
                    if exc2.code != 400:
                        raise exc2
                    logger.warning(
                        "MedtronicGPT 400 even without temperature for model %s, "
                        "retrying without temperature and max_completion_tokens...",
                        model,
                    )
                    try:
                        return _send_once(
                            current_api_token,
                            include_temperature=False,
                            include_max_completion_tokens=False,
                        )
                    except error.HTTPError:
                        raise exc1
        try:
            return _send_with_retry(self.api_token)
        except error.HTTPError as exc:
            if exc.code == 401 and self.refresh_token:
                try:
                    refresh_data = self.refresh_tokens()
                except MedtronicGPTError:
                    pass
                else:
                    new_token = refresh_data.get("apiToken") or refresh_data.get("api_token")
                    if new_token:
                        self.api_token = new_token
                    new_refresh = refresh_data.get("refreshToken") or refresh_data.get("refresh_token")
                    if new_refresh:
                        self.refresh_token = new_refresh
                    try:
                        return _send_with_retry(self.api_token)
                    except error.HTTPError as retry_exc:  # pragma: no cover - network
                        detail = self._safe_read_error_body(retry_exc)
                        raise MedtronicGPTError(
                            f"MedtronicGPT request failed after refresh "
                            f"({retry_exc.code}): {retry_exc.reason} "
                            f"(URL: {retry_exc.geturl()}){detail}"
                        ) from retry_exc
                    except error.URLError as retry_exc:  # pragma: no cover - network
                        raise MedtronicGPTError(
                            f"MedtronicGPT connection error after refresh: "
                            f"{retry_exc.reason}"
                        ) from retry_exc
            detail = self._safe_read_error_body(exc)
            raise MedtronicGPTError(
                f"MedtronicGPT request failed ({exc.code}): {exc.reason} "
                f"(URL: {exc.geturl()}){detail}"
            ) from exc
        except error.URLError as exc:  # pragma: no cover - network
            raise MedtronicGPTError(f"MedtronicGPT connection error: {exc.reason}") from exc
    def refresh_tokens(self) -> dict:
        if not self.refresh_token:
            raise MedtronicGPTError("No refresh token provided; cannot refresh API token.")
        path = self.refresh_path
        if not path.startswith("/"):
            path = f"/{path}"
        url = f"{self.base_url.rstrip('/')}{path}"
        headers = {
            "subscription-key": self.subscription_key,
            "api-token": self.api_token,
            "refresh-token": self.refresh_token,
            "api-version": self.api_version,
            "Content-Type": "application/json",
            "Accept": "application/json",
        }
        req = request.Request(url, data=json.dumps({}).encode("utf-8"), headers=headers)
        try:
            with request.urlopen(req) as resp:  # nosec: B310
                body = resp.read().decode("utf-8")
        except error.HTTPError as exc:  # pragma: no cover - network
            detail = self._safe_read_error_body(exc)
            raise MedtronicGPTError(
                f"Token refresh failed ({exc.code}): {exc.reason} (URL: {url}){detail}"
            ) from exc
        except error.URLError as exc:  # pragma: no cover - network
            raise MedtronicGPTError(
                f"MedtronicGPT connection error during refresh: {exc.reason}"
            ) from exc
        try:
            data = json.loads(body)
        except json.JSONDecodeError as exc:  # pragma: no cover - parsing
            raise MedtronicGPTError("Token refresh returned an invalid response.") from exc
        new_api_token = data.get("apiToken") or data.get("api_token")
        new_refresh_token = data.get("refreshToken") or data.get("refresh_token")
        if new_api_token:
            self.api_token = new_api_token
        if new_refresh_token:
            self.refresh_token = new_refresh_token
        self.last_refresh = True
        return data
    @staticmethod
    def _extract_content(body: str) -> str:
        try:
            data = json.loads(body)
            if "choices" in data and data["choices"]:
                message = data["choices"][0].get("message", {}).get("content")
                if message:
                    return message
            if "content" in data:
                return str(data["content"])
        except json.JSONDecodeError:
            pass
        raise MedtronicGPTError("Unexpected MedtronicGPT response format.")
    @staticmethod
    def _safe_read_error_body(exc: error.HTTPError) -> str:
        try:
            raw = exc.read()
        except Exception:
            return ""
        if not raw:
            return ""
        try:
            decoded = raw.decode("utf-8", errors="ignore")
        except Exception:
            return ""
        decoded = decoded.strip()
        if not decoded:
            return ""
        snippet = decoded[:500]
        return f" Response body: {snippet}"