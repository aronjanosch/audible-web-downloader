"""
Invitation routes for family sharing.
Allows family members to add their Audible accounts via shareable link.
"""

from flask import Blueprint, request, jsonify, render_template, redirect, url_for, current_app
import asyncio
import json
import os
import secrets
from pathlib import Path
from functools import wraps
from app.services.auth_service import AudibleAuth
from audible.localization import Locale, search_template
import audible
from app.services.settings_service import settings_manager
from utils.config_manager import get_config_manager, ConfigurationError
from utils.oauth_flow import start_oauth_login, handle_oauth_callback, check_oauth_status

invite_bp = Blueprint('invite', __name__)

# Get ConfigManager singleton
config_manager = get_config_manager()

# Store for active login sessions (shared with auth module concept)
invite_login_sessions = {}


def validate_token(f):
    """Decorator to validate invitation token"""
    @wraps(f)
    def decorated_function(token, *args, **kwargs):
        if not settings_manager.validate_invitation_token(token):
            return render_template('invite/invalid_token.html'), 403
        return f(token, *args, **kwargs)
    return decorated_function


@invite_bp.route('/invite/<token>')
@validate_token
def landing_page(token):
    """Display the invitation landing page with account creation form"""
    # Get list of supported regions from audible localization
    regions = [
        {'code': 'us', 'name': 'United States'},
        {'code': 'uk', 'name': 'United Kingdom'},
        {'code': 'de', 'name': 'Germany'},
        {'code': 'fr', 'name': 'France'},
        {'code': 'ca', 'name': 'Canada'},
        {'code': 'it', 'name': 'Italy'},
        {'code': 'au', 'name': 'Australia'},
        {'code': 'in', 'name': 'India'},
        {'code': 'jp', 'name': 'Japan'},
        {'code': 'es', 'name': 'Spain'},
        {'code': 'br', 'name': 'Brazil'},
    ]

    return render_template('invite/landing.html', token=token, regions=regions)


@invite_bp.route('/invite/<token>/add-account', methods=['POST'])
@validate_token
def add_account(token):
    """Handle account creation from invitation"""
    data = request.get_json()

    if not data:
        return jsonify({'error': 'No JSON data received'}), 400

    account_name = data.get('account_name')
    region = data.get('region', 'us')

    if not account_name:
        return jsonify({'error': 'Account name is required'}), 400

    # Validate account name format
    if not account_name.replace('_', '').replace('-', '').isalnum():
        return jsonify({'error': 'Account name can only contain letters, numbers, hyphens, and underscores'}), 400

    accounts = config_manager.get_accounts()

    if account_name in accounts:
        return jsonify({'error': 'Account name already exists. Please choose a different name.'}), 400

    # Validate region
    template = search_template('country_code', region)
    if not template:
        return jsonify({'error': f'Unsupported region: {region}'}), 400

    # Create account
    accounts[account_name] = {
        "region": region,
        "authenticated": False
    }

    config_manager.save_accounts(accounts)

    return jsonify({
        'success': True,
        'account_name': account_name,
        'auth_url': url_for('invite.start_login', token=token, account_name=account_name)
    })


@invite_bp.route('/invite/<token>/auth/login/<account_name>')
@validate_token
def start_login(token, account_name):
    """Start the Audible login process for invitation"""
    accounts = config_manager.get_accounts()

    if account_name not in accounts:
        return jsonify({'error': 'Account not found'}), 404

    account_data = accounts[account_name]
    region = account_data['region']

    # Get localization data
    template = search_template('country_code', region)
    if not template:
        return jsonify({'error': f'Unsupported region: {region}'}), 400
    loc = Locale(**template)

    # Start OAuth login using shared utility
    session_id = start_oauth_login(
        account_name=account_name,
        locale=loc,
        sessions_storage=invite_login_sessions,
        session_id_prefix='invite_',
        additional_data={'token': token}
    )

    # Redirect to login page
    return redirect(url_for('invite.login_page', token=token, session_id=session_id))


@invite_bp.route('/invite/<token>/auth/login-page/<session_id>')
@validate_token
def login_page(token, session_id):
    """Display login page with OAuth URL"""
    if session_id not in invite_login_sessions:
        return "Login session not found", 404

    session_data = invite_login_sessions[session_id]

    # Verify token matches
    if session_data.get('token') != token:
        return "Invalid token", 403

    # Wait for OAuth URL to be available
    if 'oauth_url' not in session_data:
        return "Login initializing...", 202

    return render_template('invite/login.html',
                         oauth_url=session_data['oauth_url'],
                         session_id=session_id,
                         token=token,
                         account_name=session_data['account_name'])


@invite_bp.route('/invite/<token>/auth/callback/<session_id>', methods=['POST'])
@validate_token
def login_callback(token, session_id):
    """Handle the OAuth callback URL from user"""
    data = request.get_json()
    response_url = data.get('response_url')

    success, error, code = handle_oauth_callback(
        session_id=session_id,
        response_url=response_url,
        sessions_storage=invite_login_sessions,
        token=token
    )

    if not success:
        return jsonify({'error': error}), code

    return jsonify({'success': True, 'message': 'Processing login...'}), code


@invite_bp.route('/invite/<token>/auth/status/<session_id>')
@validate_token
def login_status(token, session_id):
    """Check login status"""
    # Get account_name from session for the redirect URL
    if session_id in invite_login_sessions:
        account_name = invite_login_sessions[session_id]['account_name']
        success_redirect = url_for('invite.success_page', token=token, account_name=account_name)
    else:
        # If session not found, check_oauth_status will handle the error
        success_redirect = url_for('invite.success_page', token=token, account_name='unknown')

    response, code = check_oauth_status(
        session_id=session_id,
        sessions_storage=invite_login_sessions,
        success_redirect=success_redirect,
        token=token
    )

    return jsonify(response), code


@invite_bp.route('/invite/<token>/success/<account_name>')
@validate_token
def success_page(token, account_name):
    """Display success page after account is added"""
    accounts = config_manager.get_accounts()

    if account_name not in accounts:
        return "Account not found", 404

    account_data = accounts[account_name]

    return render_template('invite/success.html',
                         account_name=account_name,
                         region=account_data['region'])


# ============================================================================
# SINGLE-ACCOUNT INVITATION ROUTES
# These routes are for account-specific invitations where the admin creates
# an account and generates a unique link for one user to authenticate it.
# ============================================================================

def validate_account_token(f):
    """Decorator to validate account-specific invitation token"""
    @wraps(f)
    def decorated_function(token, *args, **kwargs):
        accounts = config_manager.get_accounts()

        # Find account with matching pending_invitation_token
        matching_account = None
        for account_name, account_data in accounts.items():
            if account_data.get('pending_invitation_token') == token:
                matching_account = account_name
                break

        if not matching_account:
            return render_template('invite/invalid_token.html'), 403

        # Pass the account_name to the route handler
        return f(token, matching_account, *args, **kwargs)
    return decorated_function


@invite_bp.route('/invite/account/<token>')
@validate_account_token
def account_landing_page(token, account_name):
    """Display landing page for single-account invitation"""
    accounts = config_manager.get_accounts()
    account_data = accounts[account_name]

    # Check if already authenticated
    if account_data.get('authenticated'):
        return render_template('invite/account_already_authenticated.html',
                             account_name=account_name)

    return render_template('invite/account_landing.html',
                         token=token,
                         account_name=account_name,
                         region=account_data['region'])


@invite_bp.route('/invite/account/<token>/auth/login')
@validate_account_token
def account_start_login(token, account_name):
    """Start the Audible login process for single-account invitation"""
    accounts = config_manager.get_accounts()
    account_data = accounts[account_name]
    region = account_data['region']

    # Get localization data
    template = search_template('country_code', region)
    if not template:
        return jsonify({'error': f'Unsupported region: {region}'}), 400
    loc = Locale(**template)

    # Start OAuth login using shared utility
    session_id = start_oauth_login(
        account_name=account_name,
        locale=loc,
        sessions_storage=invite_login_sessions,
        session_id_prefix='account_',
        additional_data={'token': token, 'is_account_invite': True}
    )

    # Redirect to login page
    return redirect(url_for('invite.account_login_page', token=token, session_id=session_id))


@invite_bp.route('/invite/account/<token>/auth/login-page/<session_id>')
@validate_account_token
def account_login_page(token, account_name, session_id):
    """Display login page with OAuth URL for single-account invitation"""
    if session_id not in invite_login_sessions:
        return "Login session not found", 404

    session_data = invite_login_sessions[session_id]

    # Verify token matches and is account invite
    if session_data.get('token') != token or not session_data.get('is_account_invite'):
        return "Invalid token", 403

    # Wait for OAuth URL to be available
    if 'oauth_url' not in session_data:
        return "Login initializing...", 202

    return render_template('invite/account_login.html',
                         oauth_url=session_data['oauth_url'],
                         session_id=session_id,
                         token=token,
                         account_name=session_data['account_name'])


@invite_bp.route('/invite/account/<token>/auth/callback/<session_id>', methods=['POST'])
@validate_account_token
def account_login_callback(token, account_name, session_id):
    """Handle the OAuth callback URL from user for single-account invitation"""
    # Additional validation for account-specific invite
    if session_id in invite_login_sessions:
        session_data = invite_login_sessions[session_id]
        if not session_data.get('is_account_invite'):
            return jsonify({'error': 'Invalid token'}), 403

    data = request.get_json()
    response_url = data.get('response_url')

    success, error, code = handle_oauth_callback(
        session_id=session_id,
        response_url=response_url,
        sessions_storage=invite_login_sessions,
        token=token
    )

    if not success:
        return jsonify({'error': error}), code

    return jsonify({'success': True, 'message': 'Processing login...'}), code


@invite_bp.route('/invite/account/<token>/auth/status/<session_id>')
@validate_account_token
def account_login_status(token, account_name, session_id):
    """Check login status for single-account invitation"""
    # Additional validation for account-specific invite
    if session_id in invite_login_sessions:
        session_data = invite_login_sessions[session_id]
        if not session_data.get('is_account_invite'):
            return jsonify({'error': 'Invalid token'}), 403

    success_redirect = url_for('invite.account_success_page', token=token, account_name=account_name)

    response, code = check_oauth_status(
        session_id=session_id,
        sessions_storage=invite_login_sessions,
        success_redirect=success_redirect,
        token=token
    )

    # If authentication successful, remove pending_invitation_token
    if response.get('success'):
        accounts = config_manager.get_accounts()
        if account_name in accounts:
            accounts[account_name].pop('pending_invitation_token', None)
            config_manager.save_accounts(accounts)

    return jsonify(response), code


@invite_bp.route('/invite/account/<token>/success/<account_name>')
@validate_account_token
def account_success_page(token, account_name):
    """Display success page after account authentication for single-account invitation"""
    accounts = config_manager.get_accounts()
    account_data = accounts[account_name]

    return render_template('invite/account_success.html',
                         account_name=account_name,
                         region=account_data['region'])
