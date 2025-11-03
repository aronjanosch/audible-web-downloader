"""
Global application settings management.
Handles naming patterns, presets, and configuration persistence.
"""

import json
import secrets
from pathlib import Path
from typing import Dict, Any, List, Optional

# Default naming pattern (AudioBookshelf recommended structure)
DEFAULT_NAMING_PATTERN = "{Author}/[{Series}/][Vol. {Volume} - ]{Year} - {Title}[ {{Narrator}}]/{Title}.m4b"

# Preset naming patterns
NAMING_PRESETS = {
    "audiobookshelf": {
        "name": "AudioBookshelf (Recommended)",
        "pattern": "{Author}/[{Series}/][Vol. {Volume} - ]{Year} - {Title}[ {{´{Narrator}}]/{Title}.m4b",
        "description": "Author/[Series/][Vol. # - Year - Title {Narrator}]/Title.m4b (each book in its own folder)"
    },
    "flat": {
        "name": "Flat Structure",
        "pattern": "{Title}/{Title}.m4b",
        "description": "Title/Title.m4b (minimal folder structure)"
    },
    "author_title": {
        "name": "Author/Title",
        "pattern": "{Author}/{Year} - {Title}[ {{Narrator}}]/{Title}.m4b",
        "description": "Author/[Year - Title {Narrator}]/Title.m4b (organized by author)"
    },
    "series_focused": {
        "name": "Series Focused",
        "pattern": "[{Series}/][Vol. {Volume} - ]{Title} - {Author}/{Title}.m4b",
        "description": "[Series/][Vol. # - Title - Author]/Title.m4b (organized by series)"
    }
}

# Available placeholders for naming patterns
AVAILABLE_PLACEHOLDERS = {
    "{Author}": "Book author(s), formatted appropriately for multiple authors",
    "{Series}": "Book series name (optional, empty if no series)",
    "{Title}": "Book title only, without any metadata",
    "{Year}": "Release year (e.g., 2024)",
    "{Narrator}": "Narrator name(s) - use {{Narrator}} for AudioBookshelf format",
    "{Publisher}": "Publisher name",
    "{Language}": "Book language code",
    "{ASIN}": "Amazon Standard Identification Number",
    "{Volume}": "Series volume/sequence number only (e.g., 1, 2, 3)",
}

# Conditional syntax documentation
CONDITIONAL_SYNTAX_INFO = """
Conditional Bracket Syntax:
---------------------------
Use square brackets [] to create conditional sections that are only included when all
placeholders within them have values. If any placeholder inside brackets is empty,
the entire bracketed section (including surrounding text) is omitted.

Examples:
  [Vol. {Volume} - ]  → "Vol. 1 - " when volume exists, "" when volume is empty
  [{Series}/]         → "Series Name/" when series exists, "" when series is empty
  [ {{Narrator}}]   → " {Narrator}" when narrator exists, "" when narrator is empty

Pattern Example:
  {Author}/[{Series}/][Vol. {Volume} - ]{Year} - {Title}[ {{Narrator}}]/{Title}.m4b

Results (folder structure):
  With series & volume:    "Author/Series/Vol. 1 - 2024 - Title {Narrator}/Title.m4b"
  Without series/volume:   "Author/2024 - Title {Narrator}/Title.m4b"
  Without narrator:        "Author/Series/Vol. 1 - 2024 - Title/Title.m4b"

Note: The pattern is the complete source of truth for the file path. Include /{Title}.m4b
at the end to place each book in its own folder for Audiobookshelf compatibility.

Additional Cleanup:
  - Extra spaces and dashes are automatically cleaned up
  - Empty parentheses (), brackets [], and braces {} are removed
  - Empty directory segments are removed from paths
"""

SETTINGS_FILE = Path(__file__).parent / "config" / "settings.json"


class SettingsManager:
    """Manages application settings with file persistence."""

    def __init__(self):
        self.settings = self._load_settings()

    def _load_settings(self) -> Dict[str, Any]:
        """Load settings from settings.json or create with defaults."""
        if SETTINGS_FILE.exists():
            try:
                with open(SETTINGS_FILE, 'r', encoding='utf-8') as f:
                    settings = json.load(f)
                    # Ensure naming_pattern exists
                    if 'naming_pattern' not in settings:
                        settings['naming_pattern'] = DEFAULT_NAMING_PATTERN
                    return settings
            except (json.JSONDecodeError, IOError) as e:
                print(f"Error loading settings: {e}. Using defaults.")
                return self._get_default_settings()
        else:
            # Create default settings file
            default_settings = self._get_default_settings()
            self._save_settings(default_settings)
            return default_settings

    def _get_default_settings(self) -> Dict[str, Any]:
        """Get default settings structure."""
        return {
            "naming_pattern": DEFAULT_NAMING_PATTERN,
            "selected_preset": "audiobookshelf",
            "invitation_token": self._generate_token()
        }

    def _generate_token(self) -> str:
        """Generate a secure random token for invitations."""
        return secrets.token_urlsafe(32)

    def _save_settings(self, settings: Dict[str, Any]) -> None:
        """Save settings to settings.json."""
        try:
            with open(SETTINGS_FILE, 'w', encoding='utf-8') as f:
                json.dump(settings, indent=2, fp=f)
        except IOError as e:
            print(f"Error saving settings: {e}")

    def get_naming_pattern(self) -> str:
        """Get the current naming pattern."""
        return self.settings.get('naming_pattern', DEFAULT_NAMING_PATTERN)

    def set_naming_pattern(self, pattern: str, preset: Optional[str] = None) -> None:
        """
        Set a new naming pattern.

        Args:
            pattern: The naming pattern string with placeholders
            preset: Optional preset identifier (e.g., 'audiobookshelf', 'flat', 'custom')
        """
        self.settings['naming_pattern'] = pattern
        self.settings['selected_preset'] = preset if preset else 'custom'
        self._save_settings(self.settings)

    def get_presets(self) -> Dict[str, Dict[str, str]]:
        """Get all available naming pattern presets."""
        return NAMING_PRESETS

    def get_placeholders(self) -> Dict[str, str]:
        """Get all available placeholders with descriptions."""
        return AVAILABLE_PLACEHOLDERS

    def get_all_settings(self) -> Dict[str, Any]:
        """Get complete settings including presets and placeholders."""
        return {
            "naming_pattern": self.get_naming_pattern(),
            "selected_preset": self.settings.get('selected_preset', 'audiobookshelf'),
            "presets": NAMING_PRESETS,
            "placeholders": AVAILABLE_PLACEHOLDERS
        }

    def validate_pattern(self, pattern: str) -> tuple[bool, Optional[str]]:
        """
        Validate a naming pattern.

        Returns:
            Tuple of (is_valid, error_message)
        """
        if not pattern or not pattern.strip():
            return False, "Pattern cannot be empty"

        # Check for invalid path characters
        invalid_chars = ['<', '>', ':', '"', '|', '?', '*']
        for char in invalid_chars:
            if char in pattern:
                return False, f"Pattern contains invalid character: {char}"

        # Pattern should contain at least {Title} for the filename
        if '{Title}' not in pattern:
            return False, "Pattern must contain {Title} for the filename"

        # Pattern should end with .m4b extension
        if not pattern.strip().endswith('.m4b'):
            return False, "Pattern must end with .m4b extension"

        return True, None

    def get_invitation_token(self) -> str:
        """Get the current invitation token, generating one if it doesn't exist."""
        if 'invitation_token' not in self.settings:
            self.settings['invitation_token'] = self._generate_token()
            self._save_settings(self.settings)
        return self.settings['invitation_token']

    def regenerate_invitation_token(self) -> str:
        """Generate a new invitation token, replacing the old one."""
        new_token = self._generate_token()
        self.settings['invitation_token'] = new_token
        self._save_settings(self.settings)
        return new_token

    def validate_invitation_token(self, token: str) -> bool:
        """Validate that the provided token matches the stored invitation token."""
        stored_token = self.get_invitation_token()
        return secrets.compare_digest(token, stored_token)

    def set_invitation_token(self, token: str) -> str:
        """Set a custom invitation token."""
        self.settings['invitation_token'] = token
        self._save_settings(self.settings)
        return token


# Global settings manager instance
settings_manager = SettingsManager()


def get_naming_pattern() -> str:
    """Get the current naming pattern (convenience function)."""
    return settings_manager.get_naming_pattern()


def set_naming_pattern(pattern: str, preset: Optional[str] = None) -> None:
    """Set the naming pattern (convenience function)."""
    settings_manager.set_naming_pattern(pattern, preset)


def get_all_settings() -> Dict[str, Any]:
    """Get all settings (convenience function)."""
    return settings_manager.get_all_settings()
