from flask import Blueprint, render_template, request, jsonify, session, current_app
import json
import os
from pathlib import Path
from settings import settings_manager

main_bp = Blueprint('main', __name__)

def load_accounts():
    """Load saved Audible accounts from JSON file"""
    accounts_file = current_app.config['ACCOUNTS_FILE']
    if os.path.exists(accounts_file):
        with open(accounts_file, 'r') as f:
            return json.load(f)
    return {}

def save_accounts(accounts):
    """Save Audible accounts to JSON file"""
    accounts_file = current_app.config['ACCOUNTS_FILE']
    with open(accounts_file, 'w') as f:
        json.dump(accounts, f, indent=2)

def load_libraries():
    """Load libraries configuration from JSON file"""
    libraries_file = Path("config/libraries.json")
    if libraries_file.exists():
        with open(libraries_file, 'r') as f:
            libraries = json.load(f)

            # Migrate: Remove deprecated use_audiobookshelf_structure field
            migrated = False
            for library_name, library_config in libraries.items():
                if 'use_audiobookshelf_structure' in library_config:
                    del library_config['use_audiobookshelf_structure']
                    migrated = True

            # Save migrated configuration
            if migrated:
                save_libraries(libraries)
                print("✓ Migrated libraries.json to remove deprecated use_audiobookshelf_structure field")

            return libraries
    return {}

def save_libraries(libraries):
    """Save libraries configuration to JSON file"""
    libraries_file = Path("config/libraries.json")
    with open(libraries_file, 'w') as f:
        json.dump(libraries, f, indent=2)

@main_bp.route('/')
def index():
    """Main page with account management and library display"""
    accounts = load_accounts()
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

@main_bp.route('/api/accounts', methods=['GET'])
def get_accounts():
    """API endpoint to get all accounts"""
    accounts = load_accounts()
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
    
    accounts = load_accounts()
    
    if account_name in accounts:
        return jsonify({'error': 'Account name already exists'}), 400
    
    accounts[account_name] = {
        "region": region,
        "authenticated": False
    }
    
    save_accounts(accounts)
    session['current_account'] = account_name
    
    return jsonify({'success': True, 'account': accounts[account_name]})

@main_bp.route('/api/accounts/<account_name>/select', methods=['POST'])
def select_account(account_name):
    """API endpoint to select an account"""
    accounts = load_accounts()
    
    if account_name not in accounts:
        return jsonify({'error': 'Account not found'}), 404
    
    session['current_account'] = account_name
    return jsonify({'success': True})

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
    libraries = load_libraries()
    return jsonify(libraries)

@main_bp.route('/api/libraries', methods=['POST'])
def add_library():
    """API endpoint to add a new library"""
    data = request.get_json()
    library_name = data.get('library_name')
    library_path = data.get('library_path')

    if not library_name or not library_path:
        return jsonify({'error': 'Library name and path are required'}), 400

    libraries = load_libraries()

    if library_name in libraries:
        return jsonify({'error': 'Library name already exists'}), 400

    # Validate and create path if it doesn't exist
    library_path_obj = Path(library_path)
    library_path_obj.mkdir(parents=True, exist_ok=True)

    libraries[library_name] = {
        'path': library_path,
        'created_at': library_path_obj.stat().st_mtime
    }

    save_libraries(libraries)

    return jsonify({'success': True, 'library': libraries[library_name]})

@main_bp.route('/api/libraries/<library_name>', methods=['DELETE'])
def delete_library(library_name):
    """API endpoint to delete a library"""
    libraries = load_libraries()

    if library_name not in libraries:
        return jsonify({'error': 'Library not found'}), 404

    del libraries[library_name]
    save_libraries(libraries)

    return jsonify({'success': True})

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

@main_bp.route('/api/library/state', methods=['GET'])
def get_library_state():
    """Get library state (list of ASINs in library.json)"""
    try:
        library_file = Path("config") / "library.json"
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