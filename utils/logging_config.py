"""Process-wide logging: level from LOG_LEVEL, one-line records, secrets masked."""
import logging
import os
import re
import sys

_SECRET_PATTERNS = [
    # Bearer/Basic authorization values
    (re.compile(r"(?i)\b(bearer|basic)\s+[A-Za-z0-9._~+/=-]{8,}"), r"\1 [redacted]"),
    # key=value / "key": "value" pairs for credential-like names
    (re.compile(r"""(?i)\b(access_token|refresh_token|adp_token|device_private_key|password|passwd|secret|secret_key|api_token|authorization|cookie|csrf_token)\b(["']?\s*[:=]\s*["']?)([^\s"',;&}]+)"""),
     r"\1\2[redacted]"),
    # Audible activation/license voucher material in URLs
    (re.compile(r"(?i)([?&](?:token|key|code|signature)=)[^&\s]+"), r"\1[redacted]"),
]


class RedactSecretsFilter(logging.Filter):
    """Last line of defence: mask credential-looking values in any log record."""

    def filter(self, record: logging.LogRecord) -> bool:
        try:
            message = record.getMessage()
        except Exception:
            return True
        redacted = message
        for pattern, replacement in _SECRET_PATTERNS:
            redacted = pattern.sub(replacement, redacted)
        if redacted != message:
            record.msg, record.args = redacted, ()
        return True


def configure_logging() -> None:
    """Idempotent. Honors LOG_LEVEL (default INFO) and logs to stderr."""
    level_name = os.environ.get("LOG_LEVEL", "INFO").upper()
    level = getattr(logging, level_name, logging.INFO)
    root = logging.getLogger()
    if any(getattr(h, "_audible_handler", False) for h in root.handlers):
        root.setLevel(level)
        return
    handler = logging.StreamHandler(sys.stderr)
    handler._audible_handler = True
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
    handler.addFilter(RedactSecretsFilter())
    root.addHandler(handler)
    root.setLevel(level)
    # Chatty libraries stay quiet unless explicitly debugging.
    for noisy in ("httpx", "httpcore", "apscheduler.executors.default", "urllib3"):
        logging.getLogger(noisy).setLevel(max(level, logging.WARNING))
