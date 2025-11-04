"""
Shared OAuth flow utilities for Audible authentication.

Handles the common OAuth authentication flow pattern used across
regular auth and invitation routes.
"""

from pathlib import Path
from threading import Event, Thread
from typing import Dict, Any, Callable, Optional
import audible
from audible.localization import Locale


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
            config_dir = Path("config") / "auth" / self.account_name
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
