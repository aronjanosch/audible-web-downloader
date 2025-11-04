"""
Shared utilities for managing accounts and libraries configuration.
Centralized functions to load and save account/library data from JSON files.
"""
import json
import os
from pathlib import Path
from typing import Dict, Any, Tuple
from utils.errors import AccountNotFoundError, LibraryNotFoundError, ValidationError
import audible


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


def get_account_or_404(account_name: str) -> Tuple[Dict[str, Any], str]:
    """
    Load and validate account by name, raising AccountNotFoundError if not found.
    
    Args:
        account_name: Name of the account to load.
    
    Returns:
        Tuple of (account_data, region)
    
    Raises:
        AccountNotFoundError: If account doesn't exist.
    """
    from utils.config_manager import get_config_manager
    
    config_manager = get_config_manager()
    accounts = config_manager.get_accounts()
    
    if account_name not in accounts:
        raise AccountNotFoundError(account_name)
    
    account_data = accounts[account_name]
    region = account_data.get('region', 'us')
    
    return account_data, region


def get_library_config(library_name: str) -> Tuple[Dict[str, Any], str]:
    """
    Load and validate library configuration by name.
    
    Args:
        library_name: Name of the library to load.
    
    Returns:
        Tuple of (library_config, library_path)
    
    Raises:
        LibraryNotFoundError: If library doesn't exist.
        ValidationError: If library configuration is invalid.
    """
    from utils.config_manager import get_config_manager
    
    config_manager = get_config_manager()
    libraries = config_manager.get_libraries()
    
    if library_name not in libraries:
        raise LibraryNotFoundError(library_name)
    
    library_config = libraries[library_name]
    library_path = library_config.get('path')
    
    if not library_path:
        raise ValidationError(
            f"Library '{library_name}' has no path configured",
            field='path',
            details={'library_name': library_name}
        )
    
    return library_config, library_path


def load_authenticator(account_name: str, region: str) -> audible.Authenticator:
    """
    Load Audible authenticator from file for an account.
    
    Args:
        account_name: Name of the account
        region: Audible region code (e.g., 'us', 'uk', 'de')
    
    Returns:
        Authenticator instance
    
    Raises:
        AuthenticationError: If auth file doesn't exist or is invalid
    """
    from utils.constants import get_auth_file_path
    from utils.errors import AuthenticationError
    
    auth_file = get_auth_file_path(account_name)
    
    if not auth_file.exists():
        raise AuthenticationError(
            f"Account '{account_name}' is not authenticated",
            details={'account_name': account_name}
        )
    
    try:
        auth = audible.Authenticator.from_file(auth_file)
        return auth
    except Exception as e:
        raise AuthenticationError(
            f"Failed to load authentication for account '{account_name}': {str(e)}",
            details={'account_name': account_name, 'error': str(e)}
        )
