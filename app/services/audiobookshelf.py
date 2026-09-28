"""Optional Audiobookshelf scan and catalog reconciliation.

ABS is a separate view of the files we own. Its availability never changes local
download/file-presence state.
"""

import logging
import os
import time
from collections import defaultdict
from urllib.parse import quote, urlsplit

import requests

from utils.db import get_db, transaction
from utils.fuzzy_matching import normalize_for_matching

logger = logging.getLogger(__name__)


class AudiobookshelfError(RuntimeError):
    pass


class AudiobookshelfClient:
    def __init__(self, url: str, token: str, library_id: str, *, session=None):
        parsed = urlsplit(url)
        if parsed.scheme not in ("http", "https") or not parsed.netloc or parsed.username or parsed.password:
            raise ValueError("ABS_URL must be an http(s) origin without embedded credentials")
        if not token or not library_id:
            raise ValueError("ABS_API_TOKEN and ABS_LIBRARY_ID are required")
        self.base_url = url.rstrip("/")
        self.library_id = quote(library_id, safe="")
        self.session = session or requests.Session()
        self.headers = {"Authorization": f"Bearer {token}"}

    @classmethod
    def from_environment(cls):
        values = [os.environ.get(key, "").strip() for key in
                  ("ABS_URL", "ABS_API_TOKEN", "ABS_LIBRARY_ID")]
        if not any(values):
            return None
        if not all(values):
            raise AudiobookshelfError("ABS_URL, ABS_API_TOKEN and ABS_LIBRARY_ID must all be set")
        return cls(*values)

    def _request(self, method, path, **kwargs):
        try:
            response = self.session.request(
                method, f"{self.base_url}{path}", headers=self.headers,
                timeout=8, **kwargs,
            )
            response.raise_for_status()
            return response
        except requests.RequestException as exc:
            code = getattr(getattr(exc, "response", None), "status_code", None)
            raise AudiobookshelfError(
                f"Audiobookshelf request failed (HTTP {code})" if code else
                "Audiobookshelf is unavailable"
            ) from exc

    def trigger_scan(self):
        """ABS queues the scan; a successful response does not mean indexing finished."""
        self._request("POST", f"/api/libraries/{self.library_id}/scan")

    def list_items(self):
        """Read all pages and reject unknown response shapes before changing status."""
        result = []
        page = 0
        while True:
            response = self._request(
                "GET", f"/api/libraries/{self.library_id}/items",
                params={"limit": 100, "page": page, "minified": 0, "collapseseries": 0},
            )
            try:
                body = response.json()
            except ValueError as exc:
                raise AudiobookshelfError("Audiobookshelf returned invalid JSON") from exc
            if not isinstance(body, dict) or not isinstance(body.get("results"), list):
                raise AudiobookshelfError("Unsupported Audiobookshelf items response")
            for item in body["results"]:
                if not isinstance(item, dict) or not isinstance(item.get("media"), dict) \
                   or not isinstance(item["media"].get("metadata"), dict):
                    raise AudiobookshelfError("Unsupported Audiobookshelf item response")
            result.extend(body["results"])
            total = body.get("total")
            if not isinstance(total, int) or total < len(result):
                raise AudiobookshelfError("Unsupported Audiobookshelf pagination response")
            if len(result) >= total:
                return result
            if not body["results"]:
                raise AudiobookshelfError("Audiobookshelf pagination stopped early")
            page += 1


def _normal(value):
    return normalize_for_matching(str(value or "")).strip()


def _author(metadata):
    authors = metadata.get("authors")
    if isinstance(authors, list):
        return _normal(" ".join(a.get("name", "") if isinstance(a, dict) else str(a) for a in authors))
    return _normal(metadata.get("authorName") or metadata.get("author"))


def reconcile_items(items):
    """Match downloaded books by ASIN, then unique title and compatible author.

    Never attach a title match to an ABS item carrying a different ASIN.
    Ambiguous candidates remain unlinked for manual metadata correction.
    """
    by_asin = defaultdict(list)
    by_title = defaultdict(list)
    for item in items:
        if not isinstance(item, dict) or item.get("mediaType") not in (None, "book"):
            continue
        metadata = (item.get("media") or {}).get("metadata") or {}
        if not isinstance(metadata, dict) or not item.get("id"):
            continue
        asin = str(metadata.get("asin") or "").strip().upper()
        title = _normal(metadata.get("title"))
        if asin:
            by_asin[asin].append(item)
        if title:
            by_title[title].append(item)

    books = get_db().execute(
        "SELECT asin, title, authors FROM books WHERE status='downloaded'"
    ).fetchall()
    local_titles = defaultdict(int)
    for book in books:
        local_titles[_normal(book["title"])] += 1
    now = time.time()
    counts = defaultdict(int)
    with transaction() as conn:
        for book in books:
            asin = book["asin"].upper()
            candidates = by_asin.get(asin, [])
            method = "asin" if candidates else None
            if not candidates:
                title_matches = by_title.get(_normal(book["title"]), [])
                local_author = _normal(book["authors"])
                candidates = [item for item in title_matches
                              if not ((item.get("media") or {}).get("metadata") or {}).get("asin")
                              and (not local_author or not _author((item.get("media") or {}).get("metadata") or {})
                                   or local_author == _author((item.get("media") or {}).get("metadata") or {}))]
                if candidates:
                    method = "title"
            if len(candidates) > 1 or (method == "title" and candidates
                                      and local_titles[_normal(book["title"])] > 1):
                status, item_id = "ambiguous", None
            elif candidates:
                item = candidates[0]
                item_id = item["id"]
                status = "missing" if item.get("isMissing") or item.get("isInvalid") else "matched"
            else:
                status, item_id = "pending", None
            conn.execute(
                """INSERT INTO abs_items (asin, item_id, match_method, status, last_synced)
                   VALUES (?, ?, ?, ?, ?)
                   ON CONFLICT(asin) DO UPDATE SET item_id=excluded.item_id,
                     match_method=excluded.match_method, status=excluded.status,
                     last_synced=excluded.last_synced""",
                (book["asin"], item_id, method, status, now),
            )
            counts[status] += 1
    return dict(counts)


def trigger_scan_after_download():
    """Best-effort notification; downloaded files remain valid if ABS is offline."""
    try:
        client = AudiobookshelfClient.from_environment()
        if client:
            client.trigger_scan()
    except (AudiobookshelfError, ValueError):
        logger.warning("Audiobookshelf scan could not be triggered", exc_info=True)
