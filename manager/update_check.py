"""Check GitHub Releases for a newer version. Fails silently — no internet, no
releases yet, or the repo isn't public all just mean "no update found"."""
import re
from typing import Optional, Tuple

import requests

from manager.version import __version__

REPO = "smokybbbbb/mamp_poo-for-Windows"
_API_URL = f"https://api.github.com/repos/{REPO}/releases/latest"


def _parse_version(v: str) -> tuple:
    parts = re.findall(r"\d+", v)
    return tuple(int(p) for p in parts) or (0,)


def check_for_update(timeout: int = 5) -> Optional[Tuple[str, str]]:
    """Return (latest_tag, release_url) if a newer release exists, else None."""
    try:
        r = requests.get(_API_URL, timeout=timeout)
        if r.status_code != 200:
            return None
        data = r.json()
        tag = data.get("tag_name", "")
        url = data.get("html_url", "")
        if not tag or not url:
            return None
        if _parse_version(tag) > _parse_version(__version__):
            return tag, url
    except Exception:
        pass
    return None
