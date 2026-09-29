from flask import Blueprint, request, jsonify, session, current_app, Response, render_template, redirect, url_for
import asyncio
import json
import os
from pathlib import Path
import audible
from auth import authenticate_account, fetch_library, AudibleAuth
from audible.localization import Locale, search_template
from utils.config_manager import get_config_manager, ConfigurationError
from utils.constants import get_account_auth_dir, get_auth_file_path
from utils.oauth_flow import start_oauth_login, handle_oauth_callback, check_oauth_status
from utils.errors import AccountNotFoundError, ValidationError, AuthenticationError, success_response, error_response
from utils.account_manager import get_account_or_404
from utils.library_cache import get_cached_library, write_library_cache, cache_stamp, merged_get, merged_put
from utils.security import current_user, require_member_account
from utils.token_lifecycle import load_authenticator, probe_authenticator

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
        require_member_account(account_name)
        
        account_data, region = get_account_or_404(account_name)
        
        # Run authentication asynchronously
        auth = asyncio.run(authenticate_account(account_name, region))
        
        if auth:
            config_manager.update_account(account_name, {'authenticated': True})
            return success_response(message='Authentication successful')
        else:
            raise AuthenticationError('Authentication failed')
            
    except (AccountNotFoundError, ValidationError, AuthenticationError):
        raise
    except Exception as e:
        return error_response(f'Authentication error: {str(e)}', status_code=500)

@auth_bp.route('/api/auth/check', methods=['POST'])
def check_auth():
    """Probe Audible, refreshing an expired access token when possible."""
    data = request.get_json()
    account_name = data.get('account_name')
    
    if not account_name:
        return jsonify({'error': 'Account name is required'}), 400
    require_member_account(account_name)
    
    accounts = config_manager.get_accounts()
    
    if account_name not in accounts:
        return jsonify({'error': 'Account not found'}), 404
    
    try:
        asyncio.run(probe_authenticator(account_name))
    except AuthenticationError:
        return jsonify({'authenticated': False, 'reauth_url': url_for('auth.start_login', account_name=account_name)})
    except Exception:
        return jsonify({'error': 'Audible is temporarily unavailable'}), 503
    return jsonify({'authenticated': True})

# Store for active login sessions
login_sessions = {}

@auth_bp.route('/auth/login/<account_name>')
def start_login(account_name):
    """Start the Audible login process"""
    try:
        account_data, region = get_account_or_404(account_name)
        require_member_account(account_name)

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
    require_member_account(session_data['account_name'])
    
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
    if session_id not in login_sessions:
        return jsonify({'error': 'Login session not found'}), 404
    require_member_account(login_sessions[session_id]['account_name'])
    data = request.get_json() or {}
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
    if session_id not in login_sessions:
        return jsonify({'error': 'Login session not found'}), 404
    require_member_account(login_sessions[session_id]['account_name'])
    response, code = check_oauth_status(
        session_id=session_id,
        sessions_storage=login_sessions,
        success_redirect=url_for('main.index')
    )

    return jsonify(response), code

@auth_bp.route('/api/library/all', methods=['GET'])
def fetch_all_libraries():
    """Fetch Audible libraries from all authenticated accounts, using cache where fresh."""
    accounts = config_manager.get_accounts()
    user = current_user()
    if user['role'] != 'admin':
        accounts = {user['account_name']: accounts[user['account_name']]} if user['account_name'] in accounts else {}
    authenticated = [
        (name, data) for name, data in accounts.items()
        if data.get('authenticated') and get_auth_file_path(name).exists()
    ]

    if not authenticated:
        return success_response({'library': []})

    force = request.args.get('force', '').lower() in ('1', 'true', 'yes')

    # Fast path: every account's cache is fresh and unchanged since the merged body was built.
    merged_key = None
    if not force:
        stamps = [cache_stamp(name) for name, _ in authenticated]
        if all(stamp is not None for stamp in stamps):
            merged_key = tuple((name, stamp) for (name, _), stamp in zip(authenticated, stamps))
            body = merged_get(merged_key)
            if body is not None:
                return Response(body, mimetype='application/json')

    async def _fetch_all():
        cached_results, to_fetch = [], []
        for name, data in authenticated:
            if not force:
                cached = get_cached_library(name)
                if cached is not None:
                    cached_results.append((name, cached))
                    continue
            to_fetch.append((name, data))
        tasks = [fetch_library(name, data['region']) for name, data in to_fetch]
        live = await asyncio.gather(*tasks, return_exceptions=True) if tasks else []
        return cached_results, to_fetch, live

    cached_results, to_fetch, live_results = asyncio.run(_fetch_all())

    combined = []
    from utils.auto_downloader import record_purchases
    for name, books in cached_results:
        record_purchases(name, books)
        for book in books:
            book.setdefault('account_name', name)
        combined.extend(books)

    for (name, _), result in zip(to_fetch, live_results):
        if isinstance(result, Exception) or not result:
            continue
        for book in result:
            book['account_name'] = name
        record_purchases(name, result)
        write_library_cache(name, result)
        combined.extend(result)

    # Keep one catalog card per ASIN, with every owning account visible.
    by_asin = {}
    for book in combined:
        asin = book.get('asin')
        if not asin:
            continue
        if asin not in by_asin:
            by_asin[asin] = {**book, 'account_names': []}
        owner = book.get('account_name')
        if owner and owner not in by_asin[asin]['account_names']:
            by_asin[asin]['account_names'].append(owner)

    if merged_key is not None and not to_fetch:
        response = jsonify({'success': True, 'library': list(by_asin.values())})
        merged_put(merged_key, response.get_data())
        return response
    return success_response({'library': list(by_asin.values())})


@auth_bp.route('/api/library/fetch', methods=['POST'])
def fetch_library_route():
    """API endpoint to fetch the user's Audible library"""
    try:
        data = request.get_json()
        account_name = data.get('account_name')
        
        if not account_name:
            raise ValidationError('Account name is required')
        require_member_account(account_name)
        
        account_data, region = get_account_or_404(account_name)
        
        load_authenticator(account_name)
        
        force = request.args.get('force', '').lower() in ('1', 'true', 'yes')
        if not force:
            cached = get_cached_library(account_name)
            if cached is not None:
                from utils.auto_downloader import record_purchases
                record_purchases(account_name, cached)
                return success_response({
                    'message': f'Loaded {len(cached)} books (cached)',
                    'library': cached,
                    'from_cache': True
                })

        library = asyncio.run(fetch_library(account_name, region))

        if library:
            for book in library:
                book['account_name'] = account_name
            from utils.auto_downloader import record_purchases
            record_purchases(account_name, library)
            write_library_cache(account_name, library)
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
