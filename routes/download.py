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

@download_bp.route('/api/download/books', methods=['POST'])
def download_selected_books():
    """API endpoint to download selected books"""
    data = request.get_json()
    selected_asins = data.get('selected_asins', [])
    cleanup_aax = data.get('cleanup_aax', True)
    
    if not selected_asins:
        return jsonify({'error': 'No books selected for download'}), 400
    
    current_account = session.get('current_account')
    if not current_account:
        return jsonify({'error': 'No account selected'}), 400
    
    accounts = load_accounts()
    if current_account not in accounts:
        return jsonify({'error': 'Account not found'}), 404
    
    account_data = accounts[current_account]
    region = account_data['region']
    
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
        # Set cleanup preference in session
        session['cleanup_aax'] = cleanup_aax
        
        # Start download process asynchronously
        results = asyncio.run(download_books(
            current_account,
            region,
            selected_books,
            cleanup_aax=cleanup_aax
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
    
    accounts = load_accounts()
    if current_account not in accounts:
        return jsonify({'error': 'Account not found'}), 404
    
    region = accounts[current_account]['region']
    downloader = AudiobookDownloader(current_account, region)
    state = downloader.get_download_state(asin)
    return jsonify(state)

@download_bp.route('/api/download/progress')
def download_progress():
    """API endpoint to get progress for all downloads"""
    current_account = session.get('current_account')
    if not current_account:
        return jsonify({'error': 'No account selected'}), 400
    
    accounts = load_accounts()
    if current_account not in accounts:
        return jsonify({'error': 'Account not found'}), 404
    
    region = accounts[current_account]['region']
    downloader = AudiobookDownloader(current_account, region)
    
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
    
    accounts = load_accounts()
    if current_account not in accounts:
        return jsonify({'status': 'idle'})
    
    region = accounts[current_account]['region']
    downloader = AudiobookDownloader(current_account, region)
    
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

@download_bp.route('/api/download/progress-stream')
def download_progress_stream():
    """Server-Sent Events endpoint for real-time progress updates"""
    current_account = session.get('current_account')
    if not current_account:
        return jsonify({'error': 'No account selected'}), 400
    
    accounts = load_accounts()
    if current_account not in accounts:
        return jsonify({'error': 'Account not found'}), 404
    
    region = accounts[current_account]['region']
    downloader = AudiobookDownloader(current_account, region)
    
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