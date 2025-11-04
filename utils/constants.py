"""
Application-wide path constants and configuration values.
Centralized location for all file system paths and magic numbers.
"""
from pathlib import Path

# Base directories
BASE_DIR = Path(__file__).parent.parent
CONFIG_DIR = BASE_DIR / "config"
DOWNLOADS_DIR = BASE_DIR / "downloads"
LIBRARY_DATA_DIR = BASE_DIR / "library_data"

# Config file paths
ACCOUNTS_FILE = CONFIG_DIR / "accounts.json"
LIBRARIES_FILE = CONFIG_DIR / "libraries.json"
SETTINGS_FILE = CONFIG_DIR / "settings.json"
DOWNLOAD_QUEUE_FILE = CONFIG_DIR / "download_queue.json"
DOWNLOAD_STATES_FILE = DOWNLOADS_DIR / "download_states.json"

# Auth directory
AUTH_DIR = CONFIG_DIR / "auth"


def get_auth_file_path(account_name: str) -> Path:
    """
    Get the authentication file path for a specific account.

    Args:
        account_name: Name of the Audible account

    Returns:
        Path to the account's auth.json file
    """
    return AUTH_DIR / account_name / "auth.json"


def get_account_auth_dir(account_name: str) -> Path:
    """
    Get the authentication directory for a specific account.

    Args:
        account_name: Name of the Audible account

    Returns:
        Path to the account's auth directory
    """
    return AUTH_DIR / account_name


# Download configuration constants
MAX_CONCURRENT_DOWNLOADS = 3  # Limit concurrent downloads to prevent API throttling
DOWNLOAD_TIMEOUT_SECONDS = 300  # 5 minutes timeout for download operations
CLEANUP_THRESHOLD_HOURS = 24  # Remove temporary files older than 24 hours

# FFmpeg conversion constants
FFMPEG_AUDIO_CODEC = "copy"  # Copy audio stream without re-encoding
FFMPEG_OUTPUT_FORMAT = "ipod"  # M4B container format
