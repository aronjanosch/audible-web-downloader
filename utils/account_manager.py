"""
Shared utilities for account and library lookups backed by SQLite (via ConfigManager).
"""
from typing import Dict, Any, Tuple
from utils.errors import AccountNotFoundError, LibraryNotFoundError, ValidationError
import audible


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
    from utils.token_lifecycle import load_authenticator as load_token_authenticator

    return load_token_authenticator(account_name)
