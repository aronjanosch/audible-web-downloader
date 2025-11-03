from flask import Blueprint, request, jsonify, session, current_app, Response, render_template
import asyncio
import json
import os
import time
from downloader import download_books, AudiobookDownloader, DownloadQueueManager
from utils.account_manager import load_accounts, load_libraries

download_bp = Blueprint('download', __name__)

@download_bp.route('/downloads')
def downloads_page():
    """Download progress monitoring page"""
    return render_template('downloads.html')

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
    # Use shared queue manager for download status
    queue_manager = DownloadQueueManager()
    state = queue_manager.get_download(asin)
    
    if state:
        return jsonify(state)
    else:
        return jsonify({})

@download_bp.route('/api/download/progress')
def download_progress():
    """API endpoint to get progress for all downloads"""
    # Use shared queue manager for download progress
    queue_manager = DownloadQueueManager()
    
    # Get all download states
    all_states = queue_manager.get_all_downloads()

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
            'speed': state.get('speed', 0),
            'eta': state.get('eta', 0),
            'elapsed': state.get('elapsed', 0),
            'error': state.get('error'),
            'error_type': state.get('error_type')
        }
        progress_data[asin] = progress_info

    return jsonify(progress_data)

@download_bp.route('/api/download/status')
def download_status():
    """API endpoint to check overall download status"""
    # Use shared queue manager for download status
    queue_manager = DownloadQueueManager()
    stats = queue_manager.get_statistics()

    return jsonify({
        'status': 'downloading' if stats['active'] > 0 else 'idle',
        'active_downloads': stats['active'],
        'queued': stats['queued'],
        'completed': stats['completed'],
        'failed': stats['failed']
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
    queue_manager = DownloadQueueManager()

    def generate_progress_updates():
        """Generate progress updates as Server-Sent Events"""
        
        while True:
            try:
                # Get all download states from shared manager
                all_states = queue_manager.get_all_downloads()
                stats = queue_manager.get_statistics()
                
                # Format progress data with all fields
                progress_data = {}
                for asin, state in all_states.items():
                    progress_info = {
                        'state': state.get('state', 'unknown'),
                        'title': state.get('title', 'Unknown'),
                        'timestamp': state.get('timestamp', 0),
                        'progress_percent': state.get('progress_percent', 0),
                        'downloaded_bytes': state.get('downloaded_bytes', 0),
                        'total_bytes': state.get('total_bytes'),
                        'speed': state.get('speed', 0),
                        'eta': state.get('eta', 0),
                        'elapsed': state.get('elapsed', 0),
                        'error': state.get('error'),
                        'error_type': state.get('error_type'),
                        'downloaded_by_account': state.get('downloaded_by_account')
                    }
                    progress_data[asin] = progress_info
                
                # Send combined update with progress and statistics
                update = {
                    'downloads': progress_data,
                    'stats': stats,
                    'timestamp': time.time()
                }
                
                yield f"data: {json.dumps(update)}\n\n"
                    
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