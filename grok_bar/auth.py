"""Read Grok CLI credentials from ~/.grok/auth.json."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path


def default_auth_path() -> Path:
    return Path.home() / ".grok" / "auth.json"


@dataclass(frozen=True)
class GrokAuth:
    access_token: str
    user_id: str | None
    email: str | None
    expires_at: datetime | None
    source_key: str
    refresh_token: str | None = None

    @property
    def is_expired(self) -> bool:
        if self.expires_at is None:
            return False
        # Small skew so we don't use a token that expires mid-request.
        return datetime.now(timezone.utc) >= self.expires_at


def _parse_expires_at(raw: object) -> datetime | None:
    if not raw or not isinstance(raw, str):
        return None
    text = raw.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    # Truncate fractional seconds beyond microseconds if present.
    try:
        return datetime.fromisoformat(text).astimezone(timezone.utc)
    except ValueError:
        return None


def load_auth(path: Path | None = None) -> GrokAuth:
    """Load the most useful auth entry from Grok's auth.json."""
    auth_path = path or default_auth_path()
    if not auth_path.exists():
        raise FileNotFoundError(
            f"No Grok credentials found at {auth_path}. Run `grok login` first."
        )

    with auth_path.open("r", encoding="utf-8") as fh:
        data = json.load(fh)

    if not isinstance(data, dict) or not data:
        raise ValueError(f"Invalid auth file: {auth_path}")

    # Prefer OIDC / grok.com style entries that have a non-empty key.
    candidates: list[tuple[str, dict]] = []
    for key, value in data.items():
        if isinstance(value, dict) and value.get("key"):
            candidates.append((key, value))

    if not candidates:
        raise ValueError(
            f"No usable session token in {auth_path}. Run `grok login`."
        )

    # Prefer entries that look like interactive OIDC sessions.
    def score(item: tuple[str, dict]) -> tuple[int, str]:
        key, value = item
        mode = str(value.get("auth_mode") or "")
        preference = 0
        if mode == "oidc":
            preference += 2
        if "auth.x.ai" in key or "accounts.x.ai" in key or "grok.com" in key:
            preference += 1
        if value.get("refresh_token"):
            preference += 1
        return (preference, key)

    source_key, entry = max(candidates, key=score)
    token = str(entry["key"]).strip()
    if not token:
        raise ValueError("Access token is empty. Run `grok login`.")

    return GrokAuth(
        access_token=token,
        user_id=(str(entry["user_id"]) if entry.get("user_id") else None),
        email=(str(entry["email"]) if entry.get("email") else None),
        expires_at=_parse_expires_at(entry.get("expires_at")),
        source_key=source_key,
        refresh_token=(
            str(entry["refresh_token"]) if entry.get("refresh_token") else None
        ),
    )


def auth_path_from_env() -> Path:
    override = os.environ.get("GROK_AUTH_PATH") or os.environ.get("GROK_BAR_AUTH")
    if override:
        return Path(override).expanduser()
    return default_auth_path()
