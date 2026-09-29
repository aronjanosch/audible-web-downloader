"""HTTP-level performance: response compression and static asset caching.

* Static URLs get a content-derived ``?v=`` so they can be cached for a year and still update on
  deploy. Vendored libraries live under ``static/vendor/<pinned version>`` and never change in place.
* Everything else static is revalidated with ETag / Last-Modified (Flask's default), so a repeat
  visit costs a 304.
* Text responses are compressed (brotli/zstd/gzip, negotiated). Server-sent events are not
  compressed: ``text/event-stream`` is deliberately absent from the compressible MIME types.
"""
import hashlib
from pathlib import Path

from flask import request
from flask_compress import Compress

IMMUTABLE = "public, max-age=31536000, immutable"
_hashes: dict[str, tuple[int, str]] = {}


def _asset_version(static_root: Path, filename: str) -> str | None:
    path = (static_root / filename)
    try:
        stat = path.stat()
    except OSError:
        return None
    key = (stat.st_mtime_ns << 20) ^ stat.st_size
    cached = _hashes.get(filename)
    if cached and cached[0] == key:
        return cached[1]
    digest = hashlib.sha1(path.read_bytes()).hexdigest()[:10]
    _hashes[filename] = (key, digest)
    return digest


def install_web_perf(app) -> None:
    app.config.setdefault("COMPRESS_MIMETYPES", [
        "text/html", "text/css", "text/plain", "text/javascript", "application/javascript",
        "application/json", "image/svg+xml",
    ])
    app.config.setdefault("COMPRESS_MIN_SIZE", 512)
    app.config.setdefault("COMPRESS_ALGORITHM", ["br", "gzip"])
    app.config.setdefault("COMPRESS_BR_LEVEL", 4)
    Compress(app)

    static_root = Path(app.static_folder)

    @app.url_defaults
    def version_static_urls(endpoint, values):
        if endpoint != "static" or "v" in values:
            return
        filename = values.get("filename", "")
        if filename.startswith("vendor/"):
            return  # versioned by directory; keeps <link rel=preload> and CSS url() identical
        version = _asset_version(static_root, filename)
        if version:
            values["v"] = version

    @app.after_request
    def static_cache_policy(response):
        if request.endpoint == "static" and response.status_code in (200, 304):
            if request.path.startswith("/static/vendor/") or "v" in request.args:
                response.headers["Cache-Control"] = IMMUTABLE
            else:
                response.headers["Cache-Control"] = "no-cache"
            # Static files stream by default, and flask-compress only offers brotli/zstd for streams.
            # Small text assets are buffered so every client gets its best encoding (gzip included).
            if (response.status_code == 200 and response.mimetype in app.config["COMPRESS_MIMETYPES"]
                    and (response.content_length or 0) < 2_000_000):
                response.direct_passthrough = False
                response.set_data(response.get_data())
        return response
