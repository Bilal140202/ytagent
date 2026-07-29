"""Shared HTTP session + retry helpers for non-yt-dlp methods.

Why this exists: yt-dlp has its own HTTP layer. For our hand-rolled methods
(innertube_direct, cobalt, piped, invidious) we use `requests` directly, and
we want consistent: UA, retries, timeouts, cert handling.
"""

from __future__ import annotations

import requests
from requests.adapters import HTTPAdapter

try:
    from urllib3.util.retry import Retry
except ImportError:  # pragma: no cover
    from requests.packages.urllib3.util.retry import Retry  # type: ignore

# A boring, modern browser UA. YouTube is more permissive with browser UAs
# than with python-requests/x.y.
DEFAULT_UA = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
)

DEFAULT_TIMEOUT = 30  # seconds, both connect and read


def make_session(
    *,
    retries: int = 3,
    backoff: float = 1.5,
    verify: bool = False,
    user_agent: str = DEFAULT_UA,
) -> requests.Session:
    """Return a configured requests.Session with retry adapter.

    Args:
        retries: number of retries on 429/5xx/connection errors
        backoff: urllib3 backoff factor (wait = backoff * (2 ** (retry-1)))
        verify: SSL verify. Default False to match yt-dlp's --no-check-certificates
                (some cloud MITM proxies break cert chains).
        user_agent: UA string.

    Returns:
        A requests.Session ready to use.
    """
    session = requests.Session()
    session.headers.update({"User-Agent": user_agent})
    session.verify = verify

    retry = Retry(
        total=retries,
        connect=retries,
        read=retries,
        status=retries,
        backoff_factor=backoff,
        status_forcelist=(429, 500, 502, 503, 504),
        allowed_methods=frozenset(["GET", "POST", "HEAD"]),
        raise_on_status=False,
    )
    adapter = HTTPAdapter(max_retries=retry, pool_connections=4, pool_maxsize=4)
    session.mount("https://", adapter)
    session.mount("http://", adapter)
    return session


def safe_request(
    session: requests.Session,
    method: str,
    url: str,
    *,
    timeout: int = DEFAULT_TIMEOUT,
    **kwargs,
) -> requests.Response | None:
    """Make a request with timeout + exception swallowing.

    Returns the Response on success (any status code), or None on network error.
    Never raises. Caller must check `is None` and inspect status codes.
    """
    try:
        return session.request(method, url, timeout=timeout, **kwargs)
    except requests.exceptions.RequestException:
        return None
