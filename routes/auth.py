from flask import Blueprint, request, jsonify, session, current_app, render_template, redirect, url_for
import asyncio
import json
import os
from pathlib import Path
import audible
from app.services.auth_service import authenticate_account, fetch_library, AudibleAuth
from audible.localization import Locale, search_template
from utils.config_manager import get_config_manager, ConfigurationError
from app.config.constants import get_account_auth_dir, get_auth_file_path
from utils.oauth_flow import start_oauth_login, handle_oauth_callback, check_oauth_status
from utils.errors import AccountNotFoundError, ValidationError, AuthenticationError, success_response, error_response
from utils.account_manager import get_account_or_404

auth_bp = Blueprint('auth', __name__)

# Get ConfigManager singleton
config_manager = get_config_manager()

@auth_bp.route('/api/auth/authenticate', methods=['POST'])
def authenticate():
    """API endpoint to authenticate an account with Audible"""
    try:
        data = request.get_json()
        account_name = data.get('account_name')
        
        if not account_name:
            raise ValidationError('Account name is required')
        
        account_data, region = get_account_or_404(account_name)
        accounts = config_manager.get_accounts()
        
        # Run authentication asynchronously
        auth = asyncio.run(authenticate_account(account_name, region))
        
        if auth:
            accounts[account_name]['authenticated'] = True
            config_manager.save_accounts(accounts)
            return success_response(message='Authentication successful')
        else:
            raise AuthenticationError('Authentication failed')
            
    except (AccountNotFoundError, ValidationError, AuthenticationError):
        raise
    except Exception as e:
        return error_response(f'Authentication error: {str(e)}', status_code=500)

@auth_bp.route('/api/auth/check', methods=['POST'])
def check_auth():
    """API endpoint to check if an account is authenticated"""
    data = request.get_json()
    account_name = data.get('account_name')
    
    if not account_name:
        return jsonify({'error': 'Account name is required'}), 400
    
    accounts = config_manager.get_accounts()
    
    if account_name not in accounts:
        return jsonify({'error': 'Account not found'}), 404
    
    account_data = accounts[account_name]
    region = account_data['region']
    
    # Check if we have a valid auth file
    auth_file = get_auth_file_path(account_name)
    
    is_authenticated = False
    if auth_file.exists():
        try:
            # Try to load the authenticator - if it works, we're authenticated
            auth = audible.Authenticator.from_file(auth_file)
            is_authenticated = True
        except Exception:
            # If loading fails, we're not authenticated
            is_authenticated = False
    
    # Update account data if status changed
    if accounts[account_name].get('authenticated') != is_authenticated:
        accounts[account_name]['authenticated'] = is_authenticated
        save_accounts(accounts)
    
    return jsonify({'authenticated': is_authenticated})

# Store for active login sessions
login_sessions = {}

@auth_bp.route('/auth/login/<account_name>')
def start_login(account_name):
    """Start the Audible login process"""
    try:
        account_data, region = get_account_or_404(account_name)

        # Get localization data
        template = search_template('country_code', region)
        if not template:
            raise ValidationError(f'Unsupported region: {region}')
        loc = Locale(**template)

        # Start OAuth login using shared utility
        session_id = start_oauth_login(
            account_name=account_name,
            locale=loc,
            sessions_storage=login_sessions
        )

        # Redirect to login page
        return redirect(url_for('auth.login_page', session_id=session_id))
    except (AccountNotFoundError, ValidationError):
        raise

@auth_bp.route('/auth/login-page/<session_id>')
def login_page(session_id):
    """Display login page with OAuth URL"""
    if session_id not in login_sessions:
        return "Login session not found", 404
    
    session_data = login_sessions[session_id]
    
    # Wait for OAuth URL to be available
    if 'oauth_url' not in session_data:
        return "Login initializing...", 202
    
    return render_template('auth/login.html', 
                         oauth_url=session_data['oauth_url'],
                         session_id=session_id,
                         account_name=session_data['account_name'])

@auth_bp.route('/auth/callback/<session_id>', methods=['POST'])
def login_callback(session_id):
    """Handle the OAuth callback URL from user"""
    data = request.get_json()
    response_url = data.get('response_url')

    success, error, code = handle_oauth_callback(
        session_id=session_id,
        response_url=response_url,
        sessions_storage=login_sessions
    )

    if not success:
        return jsonify({'error': error}), code

    return jsonify({'success': True, 'message': 'Processing login...'}), code

@auth_bp.route('/auth/status/<session_id>')
def login_status(session_id):
    """Check login status"""
    response, code = check_oauth_status(
        session_id=session_id,
        sessions_storage=login_sessions,
        success_redirect=url_for('main.index')
    )

    return jsonify(response), code

@auth_bp.route('/api/library/fetch', methods=['POST'])
def fetch_library_route():
    """API endpoint to fetch the user's Audible library"""
    try:
        data = request.get_json()
        account_name = data.get('account_name')
        
        if not account_name:
            raise ValidationError('Account name is required')
        
        account_data, region = get_account_or_404(account_name)
        
        # Check if authenticated by trying to load the auth file
        auth_file = get_auth_file_path(account_name)
        
        if not auth_file.exists():
            raise AuthenticationError('Account not authenticated')
        
        try:
            # Try to load the authenticator - if it fails, we're not authenticated
            auth = audible.Authenticator.from_file(auth_file)
        except Exception:
            raise AuthenticationError('Account not authenticated')
        
        # Simply fetch library using existing authentication file
        # The authenticator should already be saved during login
        library = asyncio.run(fetch_library(account_name, region))
        
        if library:
            # Don't store in session - too large for browser cookies
            return success_response({
                'message': f'Loaded {len(library)} books',
                'library': library
            })
        else:
            raise ValidationError('Failed to load library')
            
    except (AccountNotFoundError, ValidationError, AuthenticationError):
        raise
    except Exception as e:
        return error_response(f'Library fetch error: {str(e)}', status_code=500) 