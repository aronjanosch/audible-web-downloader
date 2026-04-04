"""
Common models and enums used across the application.
"""

from enum import Enum


class DownloadState(Enum):
    """Download state enum for tracking audiobook download progress"""
    PENDING = "pending"
    RETRYING = "retrying"
    LICENSE_REQUESTED = "license_requested"
    LICENSE_GRANTED = "license_granted"
    DOWNLOADING = "downloading"
    DOWNLOAD_COMPLETE = "download_complete"
    DECRYPTING = "decrypting"
    CONVERTED = "converted"
    ERROR = "error"


class BookStatus(Enum):
    """
    High-level status of a book in the library.

    Transitions::

        WANTED ──[download starts]──> DOWNLOADING ──[converted]──> DOWNLOADED
          ^                                                              |
          |                                                    [file deleted]
          └──────────────────[re-download]──────────────── MISSING
        WANTED ──[ignore]──> IGNORED ──[un-ignore]──> WANTED
    """
    WANTED      = "wanted"       # In Audible library, not yet downloaded
    DOWNLOADING = "downloading"  # Active download in progress
    DOWNLOADED  = "downloaded"   # File confirmed present on disk
    MISSING     = "missing"      # Was downloaded, file no longer exists
    IGNORED     = "ignored"      # User dismissed
