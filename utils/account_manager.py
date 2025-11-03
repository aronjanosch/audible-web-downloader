"""
Shared utilities for managing accounts and libraries configuration.
Centralized functions to load and save account/library data from JSON files.
"""
import json
import os
from pathlib import Path
from typing import Dict, Any


def load_accounts(accounts_file: str = None) -> Dict[str, Any]:
    """
    Load saved Audible accounts from JSON file.

    Args:
        accounts_file: Path to accounts file. If None, uses Flask current_app config.

    Returns:
        Dictionary of accounts or empty dict if file doesn't exist.
    """
    if accounts_file is None:
        from flask import current_app
        accounts_file = current_app.config['ACCOUNTS_FILE']

    if os.path.exists(accounts_file):
        with open(accounts_file, 'r') as f:
            return json.load(f)
    return {}


def save_accounts(accounts: Dict[str, Any], accounts_file: str = None) -> None:
    """
    Save Audible accounts to JSON file.

    Args:
        accounts: Dictionary of account data to save.
        accounts_file: Path to accounts file. If None, uses Flask current_app config.
    """
    if accounts_file is None:
        from flask import current_app
        accounts_file = current_app.config['ACCOUNTS_FILE']

    with open(accounts_file, 'w') as f:
        json.dump(accounts, f, indent=2)


def load_libraries(libraries_file: str = "config/libraries.json") -> Dict[str, Any]:
    """
    Load libraries configuration from JSON file.
    Automatically migrates deprecated fields if found.

    Args:
        libraries_file: Path to libraries config file.

    Returns:
        Dictionary of libraries or empty dict if file doesn't exist.
    """
    libraries_path = Path(libraries_file)
    if libraries_path.exists():
        with open(libraries_path, 'r') as f:
            libraries = json.load(f)

        # Migrate: Remove deprecated use_audiobookshelf_structure field
        migrated = False
        for library_name, library_config in libraries.items():
            if 'use_audiobookshelf_structure' in library_config:
                del library_config['use_audiobookshelf_structure']
                migrated = True

        # Save migrated configuration
        if migrated:
            save_libraries(libraries, libraries_file)
            print("✓ Migrated libraries.json to remove deprecated use_audiobookshelf_structure field")

        return libraries
    return {}


def save_libraries(libraries: Dict[str, Any], libraries_file: str = "config/libraries.json") -> None:
    """
    Save libraries configuration to JSON file.

    Args:
        libraries: Dictionary of library data to save.
        libraries_file: Path to libraries config file.
    """
    libraries_path = Path(libraries_file)
    with open(libraries_path, 'w') as f:
        json.dump(libraries, f, indent=2)
