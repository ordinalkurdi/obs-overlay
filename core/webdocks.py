"""Qt-free helpers for web docks (embedded pages such as Twitch chat or the Stream Manager)."""
from __future__ import annotations
import re
from urllib.parse import urlparse

PRESETS = {
    "Twitch chat": {"input": "Twitch channel name", "error": "Enter a valid Twitch channel name (3-25 letters, digits or _)."},
    "Twitch Stream Manager": {"input": None, "error": ""},
    "Custom URL": {"input": "https://example.com/page", "error": "Enter a valid http(s) address."},
}
_CHANNEL = re.compile(r"^[A-Za-z0-9_]{3,25}$")


def normalize_url(text: str) -> str | None:
    """Accepts 'example.com/x' or full http(s) URLs. Rejects every other scheme (file:, javascript:, ...)."""
    t = (text or "").strip()
    if not t or any(c in t for c in " \t\r\n\0"):
        return None
    if "://" not in t:
        if ":" in t.split("/")[0] and not re.match(r"^[^/]+:\d+(/|$)", t):
            return None                                   # e.g. javascript:alert(1), mailto:x
        t = "https://" + t
    u = urlparse(t)
    if u.scheme not in ("http", "https") or not u.netloc or not u.hostname:
        return None
    return t


def host_of(url: str) -> str:
    return (urlparse(url).hostname or "Web dock").removeprefix("www.")


def preset_url(name: str, text: str) -> str | None:
    if name == "Twitch chat":
        ch = (text or "").strip().lstrip("#@")
        return f"https://www.twitch.tv/popout/{ch.lower()}/chat?popout=" if _CHANNEL.match(ch) else None
    if name == "Twitch Stream Manager":
        return "https://dashboard.twitch.tv/stream-manager"
    return normalize_url(text)
