"""
Centralized configuration management for JSON file I/O.
Provides consistent error handling, atomic writes, and optional schema validation.
"""
import json
import shutil
from pathlib import Path
from typing import Dict, Any, Optional
from app.config.constants import (
    ACCOUNTS_FILE,
    LIBRARIES_FILE,
    SETTINGS_FILE,
    CONFIG_DIR,
    AUTH_DIR,
)


class ConfigurationError(Exception):
    """Raised when configuration file operations fail"""
    pass


class ValidationError(ConfigurationError):
    """Raised when configuration data fails validation"""
    pass


class ConfigManager:
    """
    Centralized manager for configuration file I/O operations.
    Provides atomic writes, error handling, and optional validation.
    """

    def __init__(self):
        """Initialize ConfigManager and ensure required directories exist"""
        self._ensure_directories()

    def _ensure_directories(self) -> None:
        """Create required config directories if they don't exist"""
        CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        AUTH_DIR.mkdir(parents=True, exist_ok=True)

    def _read_json_file(self, file_path: Path, default: Any = None) -> Any:
        """
        Read and parse a JSON file with error handling.

        Args:
            file_path: Path to the JSON file
            default: Default value to return if file doesn't exist

        Returns:
            Parsed JSON data or default value

        Raises:
            ConfigurationError: If file exists but cannot be read or parsed
        """
        if not file_path.exists():
            return default if default is not None else {}

        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                return json.load(f)
        except json.JSONDecodeError as e:
            raise ConfigurationError(
                f"Invalid JSON in {file_path}: {e}"
            ) from e
        except IOError as e:
            raise ConfigurationError(
                f"Cannot read {file_path}: {e}"
            ) from e

    def _write_json_file(self, file_path: Path, data: Any) -> None:
        """
        Write data to JSON file with atomic operation.
        Uses temporary file and rename to prevent corruption on failure.

        Args:
            file_path: Path to the JSON file
            data: Data to serialize to JSON

        Raises:
            ConfigurationError: If file cannot be written
        """
        # Ensure parent directory exists
        file_path.parent.mkdir(parents=True, exist_ok=True)

        # Write to temporary file first
        temp_file = file_path.with_suffix('.tmp')
        try:
            with open(temp_file, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=2, ensure_ascii=False)

            # Atomic rename (replaces existing file)
            temp_file.replace(file_path)

        except (IOError, OSError) as e:
            # Clean up temp file on error
            if temp_file.exists():
                temp_file.unlink()
            raise ConfigurationError(
                f"Cannot write {file_path}: {e}"
            ) from e

    # ========== Accounts Management ==========

    def get_accounts(self) -> Dict[str, Any]:
        """
        Load all Audible accounts from configuration.

        Returns:
            Dictionary of account data keyed by account name

        Raises:
            ConfigurationError: If accounts file cannot be read
        """
        accounts = self._read_json_file(ACCOUNTS_FILE, default={})

        # Migration: Remove deprecated use_audiobookshelf_structure field
        migrated = False
        for account_name, account_data in accounts.items():
            if isinstance(account_data, dict) and 'use_audiobookshelf_structure' in account_data:
                del account_data['use_audiobookshelf_structure']
                migrated = True

        if migrated:
            self.save_accounts(accounts)
            print("✓ Migrated accounts.json to remove deprecated fields")

        return accounts

    def save_accounts(self, accounts: Dict[str, Any]) -> None:
        """
        Save Audible accounts to configuration.

        Args:
            accounts: Dictionary of account data

        Raises:
            ConfigurationError: If accounts file cannot be written
        """
        self._write_json_file(ACCOUNTS_FILE, accounts)

    def get_account(self, account_name: str) -> Optional[Dict[str, Any]]:
        """
        Get a specific account by name.

        Args:
            account_name: Name of the account

        Returns:
            Account data dictionary or None if not found

        Raises:
            ConfigurationError: If accounts file cannot be read
        """
        accounts = self.get_accounts()
        return accounts.get(account_name)

    def update_account(self, account_name: str, updates: Dict[str, Any]) -> None:
        """
        Update specific fields of an account.

        Args:
            account_name: Name of the account to update
            updates: Dictionary of fields to update

        Raises:
            ConfigurationError: If account doesn't exist or cannot be saved
        """
        accounts = self.get_accounts()

        if account_name not in accounts:
            raise ConfigurationError(f"Account '{account_name}' not found")

        accounts[account_name].update(updates)
        self.save_accounts(accounts)

    def delete_account(self, account_name: str) -> None:
        """
        Delete an account from configuration.

        Args:
            account_name: Name of the account to delete

        Raises:
            ConfigurationError: If account doesn't exist or cannot be saved
        """
        accounts = self.get_accounts()

        if account_name not in accounts:
            raise ConfigurationError(f"Account '{account_name}' not found")

        del accounts[account_name]
        self.save_accounts(accounts)

    # ========== Libraries Management ==========

    def get_libraries(self) -> Dict[str, Any]:
        """
        Load all library configurations.

        Returns:
            Dictionary of library configurations keyed by library name

        Raises:
            ConfigurationError: If libraries file cannot be read
        """
        libraries = self._read_json_file(LIBRARIES_FILE, default={})

        # Migration: Remove deprecated use_audiobookshelf_structure field
        migrated = False
        for library_name, library_config in libraries.items():
            if isinstance(library_config, dict) and 'use_audiobookshelf_structure' in library_config:
                del library_config['use_audiobookshelf_structure']
                migrated = True

        if migrated:
            self.save_libraries(libraries)
            print("✓ Migrated libraries.json to remove deprecated fields")

        return libraries

    def save_libraries(self, libraries: Dict[str, Any]) -> None:
        """
        Save library configurations.

        Args:
            libraries: Dictionary of library configurations

        Raises:
            ConfigurationError: If libraries file cannot be written
        """
        self._write_json_file(LIBRARIES_FILE, libraries)

    def get_library(self, library_name: str) -> Optional[Dict[str, Any]]:
        """
        Get a specific library configuration by name.

        Args:
            library_name: Name of the library

        Returns:
            Library configuration dictionary or None if not found

        Raises:
            ConfigurationError: If libraries file cannot be read
        """
        libraries = self.get_libraries()
        return libraries.get(library_name)

    def update_library(self, library_name: str, updates: Dict[str, Any]) -> None:
        """
        Update specific fields of a library configuration.

        Args:
            library_name: Name of the library to update
            updates: Dictionary of fields to update

        Raises:
            ConfigurationError: If library doesn't exist or cannot be saved
        """
        libraries = self.get_libraries()

        if library_name not in libraries:
            raise ConfigurationError(f"Library '{library_name}' not found")

        libraries[library_name].update(updates)
        self.save_libraries(libraries)

    def delete_library(self, library_name: str) -> None:
        """
        Delete a library configuration.

        Args:
            library_name: Name of the library to delete

        Raises:
            ConfigurationError: If library doesn't exist or cannot be saved
        """
        libraries = self.get_libraries()

        if library_name not in libraries:
            raise ConfigurationError(f"Library '{library_name}' not found")

        del libraries[library_name]
        self.save_libraries(libraries)

    # ========== Settings Management ==========
    # Note: Settings are primarily managed by SettingsManager in settings.py
    # These methods provide a unified interface for consistency

    def get_settings(self) -> Dict[str, Any]:
        """
        Load application settings.

        Returns:
            Dictionary of application settings

        Raises:
            ConfigurationError: If settings file cannot be read
        """
        return self._read_json_file(SETTINGS_FILE, default={})

    def save_settings(self, settings: Dict[str, Any]) -> None:
        """
        Save application settings.

        Args:
            settings: Dictionary of application settings

        Raises:
            ConfigurationError: If settings file cannot be written
        """
        self._write_json_file(SETTINGS_FILE, settings)

    def update_setting(self, key: str, value: Any) -> None:
        """
        Update a specific setting.

        Args:
            key: Setting key
            value: Setting value

        Raises:
            ConfigurationError: If settings cannot be saved
        """
        settings = self.get_settings()
        settings[key] = value
        self.save_settings(settings)

    # ========== Validation ==========

    def validate_account(self, account_data: Dict[str, Any]) -> bool:
        """
        Validate account data structure.

        Args:
            account_data: Account data to validate

        Returns:
            True if valid

        Raises:
            ValidationError: If account data is invalid
        """
        required_fields = ['region', 'authenticated']

        for field in required_fields:
            if field not in account_data:
                raise ValidationError(f"Account missing required field: {field}")

        valid_regions = ['us', 'uk', 'de', 'fr', 'jp', 'it', 'in', 'ca', 'au', 'es']
        if account_data['region'] not in valid_regions:
            raise ValidationError(f"Invalid region: {account_data['region']}")

        if not isinstance(account_data['authenticated'], bool):
            raise ValidationError("Field 'authenticated' must be boolean")

        return True

    def validate_library(self, library_config: Dict[str, Any]) -> bool:
        """
        Validate library configuration structure.

        Args:
            library_config: Library configuration to validate

        Returns:
            True if valid

        Raises:
            ValidationError: If library configuration is invalid
        """
        required_fields = ['path']

        for field in required_fields:
            if field not in library_config:
                raise ValidationError(f"Library missing required field: {field}")

        # Validate path exists (optional - might want to allow non-existent paths)
        # library_path = Path(library_config['path'])
        # if not library_path.exists():
        #     raise ValidationError(f"Library path does not exist: {library_path}")

        return True


# Global singleton instance
_config_manager: Optional[ConfigManager] = None


def get_config_manager() -> ConfigManager:
    """
    Get the global ConfigManager singleton instance.

    Returns:
        ConfigManager instance
    """
    global _config_manager
    if _config_manager is None:
        _config_manager = ConfigManager()
    return _config_manager
