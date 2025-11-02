from flask import Blueprint, request, jsonify, session, current_app, Response
import asyncio
import json
import os
import time
from downloader import download_books, AudiobookDownloader

download_bp = Blueprint('download', __name__)

def load_accounts():
    """Load saved Audible accounts from JSON file"""
    accounts_file = current_app.config['ACCOUNTS_FILE']
    if os.path.exists(accounts_file):
        with open(accounts_file, 'r') as f:
            return json.load(f)
    return {}

def load_libraries():
    """Load libraries configuration from JSON file"""
    from pathlib import Path
    libraries_file = Path("config/libraries.json")
    if libraries_file.exists():
        with open(libraries_file, 'r') as f:
            return json.load(f)
    return {}

@download_bp.route('/api/download/books', methods=['POST'])
def download_selected_books():
    """API endpoint to download selected books"""
    data = request.get_json()
    selected_asins = data.get('selected_asins', [])
    cleanup_aax = data.get('cleanup_aax', True)
    library_name = data.get('library_name')

    if not selected_asins:
        return jsonify({'error': 'No books selected for download'}), 400

    if not library_name:
        return jsonify({'error': 'No library selected. Please configure and select a library first.'}), 400

    current_account = session.get('current_account')
    if not current_account:
        return jsonify({'error': 'No account selected'}), 400

    accounts = load_accounts()
    if current_account not in accounts:
        return jsonify({'error': 'Account not found'}), 404

    account_data = accounts[current_account]
    region = account_data['region']

    # Get library path from library_name
    libraries = load_libraries()
    if library_name not in libraries:
        return jsonify({'error': 'Selected library not found'}), 404

    library_config = libraries[library_name]
    library_path = library_config['path']

    # Fetch library directly since session storage is too large for browser cookies
    from auth import fetch_library
    library = asyncio.run(fetch_library(current_account, region))

    if not library:
        return jsonify({'error': 'Failed to fetch library for download'}), 400

    # Get selected book details
    selected_books = [
        book for book in library
        if book['asin'] in selected_asins
    ]

    if not selected_books:
        return jsonify({'error': 'Selected books not found in library'}), 400

    try:
        # Set cleanup preference and selected library in session for progress tracking
        session['cleanup_aax'] = cleanup_aax
        session['download_library'] = library_name

        # Start download process asynchronously
        results = asyncio.run(download_books(
            current_account,
            region,
            selected_books,
            cleanup_aax=cleanup_aax,
            library_path=library_path
        ))

        successful_downloads = len([r for r in results if r])

        return jsonify({
            'success': True,
            'message': f'Download completed! {successful_downloads} of {len(selected_books)} books downloaded successfully.',
            'results': results
        })

    except Exception as e:
        return jsonify({'error': f'Download error: {str(e)}'}), 500

@download_bp.route('/api/download/status/<asin>')
def download_status_asin(asin):
    """API endpoint to check download status for a specific book"""
    current_account = session.get('current_account')
    if not current_account:
        return jsonify({'error': 'No account selected'}), 400

    download_library = session.get('download_library')
    if not download_library:
        return jsonify({'error': 'No active download library'}), 400

    accounts = load_accounts()
    if current_account not in accounts:
        return jsonify({'error': 'Account not found'}), 404

    libraries = load_libraries()
    if download_library not in libraries:
        return jsonify({'error': 'Download library not found'}), 404

    region = accounts[current_account]['region']
    library_config = libraries[download_library]
    library_path = library_config['path']

    downloader = AudiobookDownloader(current_account, region, library_path=library_path)
    state = downloader.get_download_state(asin)
    return jsonify(state)

@download_bp.route('/api/download/progress')
def download_progress():
    """API endpoint to get progress for all downloads"""
    current_account = session.get('current_account')
    if not current_account:
        return jsonify({'error': 'No account selected'}), 400

    download_library = session.get('download_library')
    if not download_library:
        return jsonify({})  # Return empty progress if no active downloads

    accounts = load_accounts()
    if current_account not in accounts:
        return jsonify({'error': 'Account not found'}), 404

    libraries = load_libraries()
    if download_library not in libraries:
        return jsonify({})  # Return empty if library no longer exists

    region = accounts[current_account]['region']
    library_config = libraries[download_library]
    library_path = library_config['path']

    downloader = AudiobookDownloader(current_account, region, library_path=library_path)

    # Get all download states
    all_states = downloader.download_states

    # Format progress data
    progress_data = {}
    for asin, state in all_states.items():
        progress_info = {
            'state': state.get('state', 'unknown'),
            'title': state.get('title', 'Unknown'),
            'timestamp': state.get('timestamp', 0),
            'progress_percent': state.get('progress_percent', 0),
            'downloaded_bytes': state.get('downloaded_bytes', 0),
            'total_bytes': state.get('total_bytes'),
            'error': state.get('error')
        }
        progress_data[asin] = progress_info

    return jsonify(progress_data)

@download_bp.route('/api/download/status')
def download_status():
    """API endpoint to check overall download status"""
    current_account = session.get('current_account')
    if not current_account:
        return jsonify({'status': 'idle'})

    download_library = session.get('download_library')
    if not download_library:
        return jsonify({'status': 'idle'})

    accounts = load_accounts()
    if current_account not in accounts:
        return jsonify({'status': 'idle'})

    libraries = load_libraries()
    if download_library not in libraries:
        return jsonify({'status': 'idle'})

    region = accounts[current_account]['region']
    library_config = libraries[download_library]
    library_path = library_config['path']

    downloader = AudiobookDownloader(current_account, region, library_path=library_path)

    # Count active downloads
    active_downloads = 0
    for state_data in downloader.download_states.values():
        state = state_data.get('state', '')
        if state in ['pending', 'license_requested', 'license_granted', 'downloading', 'decrypting']:
            active_downloads += 1

    return jsonify({
        'status': 'downloading' if active_downloads > 0 else 'idle',
        'active_downloads': active_downloads
    })

@download_bp.route('/api/library/sync', methods=['POST'])
def sync_library():
    """API endpoint to sync library and populate download history"""
    data = request.get_json() or {}
    library_name = data.get('library_name')

    if not library_name:
        return jsonify({'error': 'No library selected. Please select a library to sync.'}), 400

    current_account = session.get('current_account')
    if not current_account:
        return jsonify({'error': 'No account selected'}), 400

    accounts = load_accounts()
    if current_account not in accounts:
        return jsonify({'error': 'Account not found'}), 404

    # Get library path from library_name
    libraries = load_libraries()
    if library_name not in libraries:
        return jsonify({'error': 'Selected library not found'}), 404

    library_config = libraries[library_name]
    library_path = library_config['path']
    region = accounts[current_account]['region']

    try:
        # Create downloader instance and run sync
        downloader = AudiobookDownloader(current_account, region, library_path=library_path)
        stats = downloader.sync_library()

        return jsonify({
            'success': True,
            'message': f'Library sync complete! Found {stats["asins_found"]} books with ASINs.',
            'stats': stats
        })

    except Exception as e:
        return jsonify({'error': f'Sync error: {str(e)}'}), 500

@download_bp.route('/api/download/progress-stream')
def download_progress_stream():
    """Server-Sent Events endpoint for real-time progress updates"""
    current_account = session.get('current_account')
    if not current_account:
        return jsonify({'error': 'No account selected'}), 400

    download_library = session.get('download_library')
    if not download_library:
        return jsonify({'error': 'No active download library'}), 400

    accounts = load_accounts()
    if current_account not in accounts:
        return jsonify({'error': 'Account not found'}), 404

    libraries = load_libraries()
    if download_library not in libraries:
        return jsonify({'error': 'Download library not found'}), 404

    region = accounts[current_account]['region']
    library_config = libraries[download_library]
    library_path = library_config['path']

    downloader = AudiobookDownloader(current_account, region, library_path=library_path)

    def generate_progress_updates():
        """Generate progress updates as Server-Sent Events"""
        last_progress_data = {}
        consecutive_no_changes = 0
        
        while True:
            try:
                # Get all download states
                all_states = downloader.download_states
                
                # Format progress data
                progress_data = {}
                active_downloads = 0
                
                for asin, state in all_states.items():
                    progress_info = {
                        'state': state.get('state', 'unknown'),
                        'title': state.get('title', 'Unknown'),
                        'timestamp': state.get('timestamp', 0),
                        'progress_percent': state.get('progress_percent', 0),
                        'downloaded_bytes': state.get('downloaded_bytes', 0),
                        'total_bytes': state.get('total_bytes'),
                        'error': state.get('error')
                    }
                    progress_data[asin] = progress_info
                    
                    # Count active downloads
                    if state.get('state') not in ['converted', 'error']:
                        active_downloads += 1
                
                # Only send data if there are changes or active downloads
                if progress_data != last_progress_data or active_downloads > 0:
                    yield f"data: {json.dumps(progress_data)}\n\n"
                    last_progress_data = progress_data.copy()
                    consecutive_no_changes = 0
                else:
                    consecutive_no_changes += 1
                
                # Stop streaming after 30 seconds of no active downloads and no changes
                if active_downloads == 0 and consecutive_no_changes > 30:
                    break
                    
                time.sleep(1)  # Send updates every second
                
            except Exception as e:
                # Send error as SSE event
                error_data = {'error': str(e)}
                yield f"data: {json.dumps(error_data)}\n\n"
                break
    
    return Response(
        generate_progress_updates(),
        mimetype='text/event-stream',
        headers={
            'Cache-Control': 'no-cache',
            'Connection': 'keep-alive',
            'Access-Control-Allow-Origin': '*',
        }
    )