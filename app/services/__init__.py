"""
Services package for business logic components.

This package contains specialized service classes that handle specific
aspects of the audiobook download and management process.
"""

# Core services (existing)
from .path_builder import PathBuilder
from .audio_converter import AudioConverter
from .metadata_enricher import MetadataEnricher
from .library_manager import LibraryManager

# Migrated services (from root level)
from .auth_service import AudibleAuth, authenticate_account, fetch_library
from .download_service import AudiobookDownloader, DownloadQueueManager, download_books
from .import_service import AudiobookImporter, ImportQueueManager, ImportState
from .scanner_service import LocalLibraryScanner, LibraryComparator
from .storage_service import LibraryStorage
from .settings_service import SettingsManager, settings_manager, get_naming_pattern, set_naming_pattern, get_all_settings

__all__ = [
    # Core services
    'PathBuilder',
    'AudioConverter',
    'MetadataEnricher',
    'LibraryManager',
    # Auth services
    'AudibleAuth',
    'authenticate_account',
    'fetch_library',
    # Download services
    'AudiobookDownloader',
    'DownloadQueueManager',
    'download_books',
    # Import services
    'AudiobookImporter',
    'ImportQueueManager',
    'ImportState',
    # Scanner services
    'LocalLibraryScanner',
    'LibraryComparator',
    # Storage services
    'LibraryStorage',
    # Settings services
    'SettingsManager',
    'settings_manager',
    'get_naming_pattern',
    'set_naming_pattern',
    'get_all_settings',
]
