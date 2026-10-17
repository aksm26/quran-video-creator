"""Is there a newer release on GitHub? The app only tells the user; it never downloads or installs anything."""

import re

import requests

from .. import __version__

LATEST = "https://api.github.com/repos/aksm26/quran-video-creator/releases/latest"


def parse(version: str) -> tuple[int, ...]:
    """'v1.2.0' -> (1, 2, 0). Anything after the numbers (a '-beta' tag) is ignored."""
    return tuple(int(n) for n in re.findall(r"\d+", version.split("-")[0]))


def newer_release(session: requests.Session, current: str = __version__) -> tuple[str, str] | None:
    """(version, release page URL) when GitHub's latest release is newer than `current`, else None.
    Raises on network or data problems; the caller decides that an update check failing is not worth a word."""
    r = session.get(LATEST, timeout=10, headers={"Accept": "application/vnd.github+json"})
    r.raise_for_status()
    data = r.json()
    tag, url = data["tag_name"], data["html_url"]
    return (tag.lstrip("v"), url) if parse(tag) > parse(current) else None
