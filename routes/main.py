from flask import Blueprint, render_template, request, jsonify, session, current_app
import json
import os
import shutil
from pathlib import Path
from settings import settings_manager
from utils.config_manager import get_config_manager, ConfigurationError
from utils.constants import get_account_auth_dir, CONFIG_DIR
from utils.errors import AccountNotFoundError, LibraryNotFoundError, ValidationError, success_response, error_response
from utils.account_manager import get_account_or_404, get_library_config

main_bp = Blueprint('main', __name__)

# Get ConfigManager singleton
config_manager = get_config_manager()

@main_bp.route('/')
def index():
    """Main page with account management and library display"""
    accounts = config_manager.get_accounts()
    current_account = session.get('current_account')

    # Get current account data
    current_account_data = None
    if current_account and current_account in accounts:
        current_account_data = accounts[current_account]

    # Get library from session
    library = session.get('library', [])

    return render_template('index.html',
                         accounts=accounts,
                         current_account=current_account,
                         current_account_data=current_account_data,
                         library=library)

@main_bp.route('/import')
def importer():
    """Import page for M4B audiobooks"""
    accounts = config_manager.get_accounts()
    current_account = session.get('current_account')

    # Get current account data
    current_account_data = None
    if current_account and current_account in accounts:
        current_account_data = accounts[current_account]

    return render_template('importer.html',
                         accounts=accounts,
                         current_account=current_account,
                         current_account_data=current_account_data)

@main_bp.route('/api/accounts', methods=['GET'])
def get_accounts():
    """API endpoint to get all accounts"""
    accounts = config_manager.get_accounts()
    return jsonify(accounts)

@main_bp.route('/api/accounts', methods=['POST'])
def add_account():
    """API endpoint to add a new account"""
    data = request.get_json()

    if not data:
        return jsonify({'error': 'No JSON data received'}), 400

    account_name = data.get('account_name')
    region = data.get('region', 'us')

    if not account_name:
        return jsonify({'error': 'Account name is required'}), 400

    accounts = config_manager.get_accounts()

    if account_name in accounts:
        return jsonify({'error': 'Account name already exists'}), 400

    accounts[account_name] = {
        "region": region,
        "authenticated": False
    }

    config_manager.save_accounts(accounts)
    session['current_account'] = account_name

    return jsonify({'success': True, 'account': accounts[account_name]})

@main_bp.route('/api/accounts/<account_name>/generate-invite-link', methods=['POST'])
def generate_account_invite_link(account_name):
    """Generate a unique invitation link for a specific account"""
    try:
        account_data, region = get_account_or_404(account_name)
        accounts = config_manager.get_accounts()

        # Check if already authenticated
        if account_data.get('authenticated'):
            raise ValidationError('Account is already authenticated')

        # Generate unique token for this account
        import secrets
        token = secrets.token_urlsafe(32)

        # Store token in account data
        accounts[account_name]['pending_invitation_token'] = token
        config_manager.save_accounts(accounts)

        # Build invitation URL
        invitation_url = request.url_root.rstrip('/') + '/invite/account/' + token

        return success_response({
            'invitation_url': invitation_url,
            'token': token,
            'account_name': account_name
        })
    except Exception as e:
        # Custom errors are handled by error handler
        if isinstance(e, (AccountNotFoundError, ValidationError)):
            raise
        return error_response(str(e), status_code=500)

@main_bp.route('/api/accounts/<account_name>/revoke-invite-link', methods=['POST'])
def revoke_account_invite_link(account_name):
    """Revoke the invitation link for a specific account"""
    try:
        account_data, region = get_account_or_404(account_name)
        accounts = config_manager.get_accounts()

        # Remove pending invitation token
        if 'pending_invitation_token' in accounts[account_name]:
            accounts[account_name].pop('pending_invitation_token')
            config_manager.save_accounts(accounts)

        return success_response(message='Invitation link revoked')
    except AccountNotFoundError:
        raise
    except Exception as e:
        return error_response(str(e), status_code=500)

@main_bp.route('/api/accounts/<account_name>/select', methods=['POST'])
def select_account(account_name):
    """API endpoint to select an account"""
    try:
        account_data, region = get_account_or_404(account_name)
        session['current_account'] = account_name
        return success_response()
    except AccountNotFoundError:
        raise

@main_bp.route('/api/accounts/<account_name>', methods=['DELETE'])
def delete_account(account_name):
    """API endpoint to delete an account"""
    try:
        account_data, region = get_account_or_404(account_name)
        accounts = config_manager.get_accounts()

        # Remove account from accounts.json
        del accounts[account_name]
        config_manager.save_accounts(accounts)

        # Clean up auth directory if it exists
        auth_dir = get_account_auth_dir(account_name)
        if auth_dir.exists():
            shutil.rmtree(auth_dir)

        # Clear from session if this was the current account
        if session.get('current_account') == account_name:
            session.pop('current_account', None)
            session.pop('library', None)

        return success_response(message='Account deleted successfully')
    except AccountNotFoundError:
        raise
    except Exception as e:
        return error_response(str(e), status_code=500)

@main_bp.route('/api/library/search')
def search_library():
    """API endpoint to search library"""
    search_term = request.args.get('q', '').lower()
    library = session.get('library', [])

    if not search_term:
        return jsonify(library)

    filtered_books = [
        book for book in library
        if search_term in book.get('title', '').lower() or
           search_term in book.get('authors', '').lower()
    ]

    return jsonify(filtered_books)

@main_bp.route('/api/libraries', methods=['GET'])
def get_libraries():
    """API endpoint to get all libraries"""
    libraries = config_manager.get_libraries()
    return jsonify(libraries)

@main_bp.route('/api/libraries', methods=['POST'])
def add_library():
    """API endpoint to add a new library"""
    data = request.get_json()
    library_name = data.get('library_name')
    library_path = data.get('library_path')

    if not library_name or not library_path:
        return jsonify({'error': 'Library name and path are required'}), 400

    libraries = config_manager.get_libraries()

    if library_name in libraries:
        return jsonify({'error': 'Library name already exists'}), 400

    # Validate and create path if it doesn't exist
    library_path_obj = Path(library_path)
    library_path_obj.mkdir(parents=True, exist_ok=True)

    libraries[library_name] = {
        'path': library_path,
        'created_at': library_path_obj.stat().st_mtime
    }

    config_manager.save_libraries(libraries)

    return jsonify({'success': True, 'library': libraries[library_name]})

@main_bp.route('/api/libraries/<library_name>', methods=['DELETE'])
def delete_library(library_name):
    """API endpoint to delete a library"""
    try:
        library_config, library_path = get_library_config(library_name)
        libraries = config_manager.get_libraries()

        del libraries[library_name]
        config_manager.save_libraries(libraries)

        return success_response()
    except LibraryNotFoundError:
        raise

@main_bp.route('/api/settings/naming', methods=['GET'])
def get_naming_settings():
    """Get current naming pattern settings, presets, and placeholders"""
    try:
        settings = settings_manager.get_all_settings()
        return jsonify({
            'success': True,
            'settings': settings
        })
    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500

@main_bp.route('/api/settings/naming', methods=['POST'])
def update_naming_settings():
    """Update the naming pattern"""
    try:
        data = request.get_json()
        pattern = data.get('pattern')
        preset = data.get('preset')

        if not pattern:
            return jsonify({
                'success': False,
                'error': 'Pattern is required'
            }), 400

        # Validate the pattern
        is_valid, error_message = settings_manager.validate_pattern(pattern)
        if not is_valid:
            return jsonify({
                'success': False,
                'error': error_message
            }), 400

        # Save the new pattern
        settings_manager.set_naming_pattern(pattern, preset)

        return jsonify({
            'success': True,
            'pattern': pattern,
            'preset': preset
        })
    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500

@main_bp.route('/api/settings/invitation-link', methods=['GET'])
def get_invitation_link():
    """Get the invitation link for family sharing"""
    try:
        token = settings_manager.get_invitation_token()
        # Build full URL
        invitation_url = request.url_root.rstrip('/') + '/invite/' + token
        return jsonify({
            'success': True,
            'invitation_url': invitation_url,
            'token': token
        })
    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500

@main_bp.route('/api/settings/regenerate-invitation-token', methods=['POST'])
def regenerate_invitation_token():
    """Regenerate the invitation token (invalidates old link)"""
    try:
        new_token = settings_manager.regenerate_invitation_token()
        invitation_url = request.url_root.rstrip('/') + '/invite/' + new_token
        return jsonify({
            'success': True,
            'invitation_url': invitation_url,
            'token': new_token
        })
    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500

@main_bp.route('/api/settings/set-invitation-token', methods=['POST'])
def set_invitation_token():
    """Set a custom invitation token"""
    try:
        data = request.get_json()
        token = data.get('token')

        if not token:
            return jsonify({
                'success': False,
                'error': 'Token is required'
            }), 400

        # Validate token format (alphanumeric, hyphens, underscores only)
        import re
        if not re.match(r'^[a-zA-Z0-9_-]+$', token):
            return jsonify({
                'success': False,
                'error': 'Token can only contain letters, numbers, hyphens, and underscores'
            }), 400

        # Minimum length check
        if len(token) < 8:
            return jsonify({
                'success': False,
                'error': 'Token must be at least 8 characters long'
            }), 400

        # Set the custom token
        settings_manager.set_invitation_token(token)
        invitation_url = request.url_root.rstrip('/') + '/invite/' + token

        return jsonify({
            'success': True,
            'invitation_url': invitation_url,
            'token': token
        })
    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500

@main_bp.route('/api/library/state', methods=['GET'])
def get_library_state():
    """Get library state (list of ASINs in library.json)"""
    try:
        library_file = CONFIG_DIR / "library.json"
        if library_file.exists():
            with open(library_file, 'r') as f:
                library_state = json.load(f)
                # Return just the ASINs for efficient lookup
                return jsonify({
                    'success': True,
                    'asins': list(library_state.keys())
                })
        return jsonify({
            'success': True,
            'asins': []
        })
    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500