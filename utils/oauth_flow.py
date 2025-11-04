"""
Shared OAuth flow utilities for Audible authentication.

Handles the common OAuth authentication flow pattern used across
regular auth and invitation routes.
"""

from pathlib import Path
from threading import Event, Thread
from typing import Dict, Any, Callable, Optional, Tuple
import audible
from audible.localization import Locale
from utils.constants import get_account_auth_dir
from utils.config_manager import get_config_manager


class OAuthSession:
    """Manages an OAuth login session with Audible."""

    def __init__(
        self,
        account_name: str,
        locale: Locale,
        session_id: str,
        sessions_storage: Dict[str, Any],
        additional_data: Optional[Dict[str, Any]] = None
    ):
        """
        Initialize OAuth session.

        Args:
            account_name: Name of the account being authenticated
            locale: Audible locale for the region
            session_id: Unique identifier for this session
            sessions_storage: Dict to store session data (login_sessions or invite_login_sessions)
            additional_data: Optional extra data to store in session (e.g., token, is_account_invite)
        """
        self.account_name = account_name
        self.locale = locale
        self.session_id = session_id
        self.sessions_storage = sessions_storage
        self.additional_data = additional_data or {}

        self.login_event = Event()
        self.login_result = {}

    def web_login_callback(self, oauth_url: str) -> str:
        """
        Callback that stores OAuth URL and waits for user to complete login.

        Args:
            oauth_url: OAuth URL from Audible

        Returns:
            Response URL from user completing OAuth flow

        Raises:
            Exception: If login times out or is cancelled
        """
        # Store session data
        session_data = {
            'oauth_url': oauth_url,
            'event': self.login_event,
            'result': self.login_result,
            'account_name': self.account_name,
            **self.additional_data
        }
        self.sessions_storage[self.session_id] = session_data

        # Wait for user to complete login (5 minute timeout)
        self.login_event.wait(timeout=300)

        if 'response_url' in self.login_result:
            return self.login_result['response_url']
        else:
            raise Exception("Login timeout or cancelled")

    def login_thread(self):
        """
        Perform Audible authentication in background thread.
        Saves authentication to file on success.
        """
        try:
            # Use audible's built-in external login method
            auth = audible.Authenticator.from_login_external(
                locale=self.locale,
                with_username=False,
                login_url_callback=self.web_login_callback
            )

            # Save authenticator to expected location
            config_dir = get_account_auth_dir(self.account_name)
            config_dir.mkdir(parents=True, exist_ok=True)
            auth_file = config_dir / "auth.json"
            auth.to_file(auth_file, encryption=False)

            self.login_result['success'] = True

        except Exception as e:
            self.login_result['error'] = str(e)
            self.login_result['success'] = False

    def start(self):
        """
        Start the OAuth login process in a background thread.

        Returns:
            session_id: The session ID for tracking this login process
        """
        # Start login in background thread
        Thread(target=self.login_thread, daemon=True).start()

        return self.session_id


def start_oauth_login(
    account_name: str,
    locale: Locale,
    sessions_storage: Dict[str, Any],
    session_id_prefix: str = "",
    additional_data: Optional[Dict[str, Any]] = None
) -> str:
    """
    Start OAuth login process for an account.

    Args:
        account_name: Name of the account to authenticate
        locale: Audible locale for the region
        sessions_storage: Dict to store session data (shared between routes)
        session_id_prefix: Optional prefix for session ID (e.g., "invite_", "account_")
        additional_data: Optional extra data to store in session

    Returns:
        session_id: Unique session ID for tracking the login process

    Example:
        >>> from audible.localization import Locale, search_template
        >>> template = search_template('country_code', 'us')
        >>> locale = Locale(**template)
        >>> session_id = start_oauth_login(
        ...     'my_account',
        ...     locale,
        ...     login_sessions,
        ...     session_id_prefix='invite_',
        ...     additional_data={'token': 'abc123'}
        ... )
    """
    # Create unique session ID
    session_id = f"{session_id_prefix}{account_name}_{len(sessions_storage)}"

    # Create and start OAuth session
    oauth_session = OAuthSession(
        account_name=account_name,
        locale=locale,
        session_id=session_id,
        sessions_storage=sessions_storage,
        additional_data=additional_data
    )

    return oauth_session.start()


def handle_oauth_callback(
    session_id: str,
    response_url: str,
    sessions_storage: Dict[str, Any],
    token: Optional[str] = None
) -> Tuple[bool, Optional[str], int]:
    """
    Handle OAuth callback URL from user.

    Shared handler for both regular auth and invitation flows.

    Args:
        session_id: The OAuth session ID
        response_url: The OAuth response URL from the user
        sessions_storage: Storage dict containing session data
        token: Optional invitation token for validation (invitation flow only)

    Returns:
        Tuple of (success, error_message, status_code)

    Example:
        >>> success, error, code = handle_oauth_callback(
        ...     session_id='my_session',
        ...     response_url='https://...',
        ...     sessions_storage=login_sessions
        ... )
        >>> if not success:
        ...     return jsonify({'error': error}), code
    """
    # Check if session exists
    if session_id not in sessions_storage:
        return False, 'Login session not found', 404

    session_data = sessions_storage[session_id]

    # Verify token if provided (invitation flow)
    if token is not None and session_data.get('token') != token:
        return False, 'Invalid token', 403

    # Validate response URL
    if not response_url:
        return False, 'Response URL is required', 400

    # Pass response URL to waiting OAuth session
    session_data['result']['response_url'] = response_url
    session_data['event'].set()

    return True, None, 200


def check_oauth_status(
    session_id: str,
    sessions_storage: Dict[str, Any],
    success_redirect: str,
    token: Optional[str] = None
) -> Tuple[Dict[str, Any], int]:
    """
    Check OAuth login status and return appropriate response.

    Shared handler for both regular auth and invitation flows.

    Args:
        session_id: The OAuth session ID
        sessions_storage: Storage dict containing session data
        success_redirect: URL to redirect to on successful authentication
        token: Optional invitation token for validation (invitation flow only)

    Returns:
        Tuple of (response_dict, status_code)

    Example:
        >>> response, code = check_oauth_status(
        ...     session_id='my_session',
        ...     sessions_storage=login_sessions,
        ...     success_redirect='/dashboard'
        ... )
        >>> return jsonify(response), code
    """
    # Check if session exists
    if session_id not in sessions_storage:
        return {'error': 'Login session not found'}, 404

    session_data = sessions_storage[session_id]

    # Verify token if provided (invitation flow)
    if token is not None and session_data.get('token') != token:
        return {'error': 'Invalid token'}, 403

    result = session_data['result']

    # Check if login completed
    if 'success' in result:
        # Clean up session
        del sessions_storage[session_id]
        account_name = session_data['account_name']

        if result['success']:
            # Mark account as authenticated in config
            config_manager = get_config_manager()
            accounts = config_manager.get_accounts()
            accounts[account_name]['authenticated'] = True
            config_manager.save_accounts(accounts)

            return {
                'success': True,
                'message': 'Login successful!',
                'redirect': success_redirect
            }, 200
        else:
            return {
                'success': False,
                'error': result.get('error', 'Unknown error')
            }, 200

    # Login still in progress
    return {'status': 'pending'}, 200
