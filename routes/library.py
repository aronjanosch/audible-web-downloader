"""
Library management routes for local audiobook scanning and comparison.
"""

from flask import Blueprint, request, jsonify, session, current_app
import os
import json
from pathlib import Path
import logging
from datetime import datetime
from library_scanner import LocalLibraryScanner, LibraryComparator
from library_storage import LibraryStorage

library_bp = Blueprint('library', __name__, url_prefix='/api/library')
logger = logging.getLogger(__name__)

# Initialize storage
storage = LibraryStorage()

@library_bp.route('/scan-local', methods=['POST'])
def scan_local_library():
    """Scan local audiobook library directory."""
    data = request.get_json() or {}
    library_path = data.get('library_path') or current_app.config.get('LOCAL_LIBRARY_PATH')
    force_rescan = data.get('force_rescan', False)
    
    if not library_path:
        return jsonify({'error': 'Library path is required'}), 400
    
    if not os.path.exists(library_path):
        return jsonify({'error': f'Library path does not exist: {library_path}'}), 400
    
    try:
        scanner = LocalLibraryScanner(library_path, storage)
        
        # Check if we have cached data and don't need to rescan
        if not force_rescan:
            cached_library = scanner.load_cached_library()
            if cached_library:
                logger.info(f"Using cached library data for {library_path}")
                return jsonify({
                    'success': True,
                    'message': f'Loaded {cached_library["book_count"]} books from cached library',
                    'book_count': cached_library['book_count'],
                    'library_path': library_path,
                    'library_id': cached_library['id'],
                    'last_scanned': cached_library['last_scanned'],
                    'cached': True,
                    'stats': cached_library.get('stats', {}),
                    'books': cached_library['books'][:10]  # Preview
                })
        
        # Perform fresh scan
        library_id, local_books = scanner.scan_and_save_library()
        
        logger.info(f"Scanned and saved {len(local_books)} books from {library_path}")
        
        # Get the full library data with stats
        library_data = storage.load_library(library_id)
        
        return jsonify({
            'success': True,
            'message': f'Scanned {len(local_books)} books from local library',
            'book_count': len(local_books),
            'library_path': library_path,
            'library_id': library_id,
            'last_scanned': library_data['last_scanned'],
            'cached': False,
            'stats': library_data.get('stats', {}),
            'books': local_books[:10]  # Return first 10 books as preview
        })
        
    except Exception as e:
        logger.error(f"Error scanning local library: {e}")
        return jsonify({'error': f'Failed to scan library: {str(e)}'}), 500

@library_bp.route('/compare', methods=['POST'])
def compare_libraries():
    """Compare Audible library with local library."""
    data = request.get_json() or {}
    
    # Get parameters
    audible_library = data.get('audible_library', [])
    library_id = data.get('library_id')
    library_path = data.get('library_path')
    audible_account = data.get('audible_account', 'unknown')
    
    if not audible_library:
        return jsonify({'error': 'No Audible library provided. Please fetch your Audible library first.'}), 400
    
    # Get local library data
    local_library_data = None
    
    if library_id:
        local_library_data = storage.load_library(library_id)
    elif library_path:
        local_library_data = storage.load_library_by_path(library_path)
    else:
        return jsonify({'error': 'No library ID or path provided.'}), 400
    
    if not local_library_data:
        return jsonify({'error': 'No local library found. Please scan your local library first.'}), 400
    
    local_books = local_library_data.get('books', [])
    
    try:
        comparator = LibraryComparator()
        comparison_result = comparator.compare_libraries(audible_library, local_books)
        
        # Save comparison result to persistent storage
        comparison_id = storage.save_comparison(
            local_library_data['id'],
            audible_account,
            comparison_result
        )
        
        logger.info(f"Library comparison saved as {comparison_id}: "
                   f"{comparison_result['missing_count']} missing, "
                   f"{comparison_result['available_count']} available locally")
        
        return jsonify({
            'success': True,
            'comparison': comparison_result,
            'comparison_id': comparison_id,
            'library_id': local_library_data['id']
        })
        
    except Exception as e:
        logger.error(f"Error comparing libraries: {e}")
        return jsonify({'error': f'Failed to compare libraries: {str(e)}'}), 500

@library_bp.route('/missing', methods=['GET'])
def get_missing_books():
    """Get books that are missing from local library."""
    library_id = request.args.get('library_id')
    audible_account = request.args.get('audible_account')
    
    if not library_id or not audible_account:
        return jsonify({'error': 'Library ID and Audible account are required'}), 400
    
    # Load comparison data
    comparison_data = storage.load_comparison(library_id, audible_account)
    
    if not comparison_data:
        return jsonify({'error': 'No library comparison found. Please compare libraries first.'}), 400
    
    comparison = comparison_data.get('comparison_data', {})
    missing_books = comparison.get('missing_from_local', [])
    
    # Apply filters
    search_term = request.args.get('search', '').lower()
    language = request.args.get('language')
    author = request.args.get('author')
    
    if search_term:
        missing_books = [
            book for book in missing_books
            if search_term in book.get('title', '').lower() or 
               search_term in book.get('authors', '').lower()
        ]
    
    if language:
        missing_books = [
            book for book in missing_books
            if book.get('language') == language
        ]
    
    if author:
        missing_books = [
            book for book in missing_books
            if author.lower() in book.get('authors', '').lower()
        ]
    
    return jsonify({
        'success': True,
        'missing_books': missing_books,
        'total_missing': len(comparison.get('missing_from_local', [])),
        'filtered_count': len(missing_books)
    })

@library_bp.route('/local-books', methods=['GET'])
def get_local_books():
    """Get local library books with filtering."""
    local_library_data = session.get('local_library', {})
    local_books = local_library_data.get('books', [])
    
    if not local_books:
        return jsonify({'error': 'No local library found. Please scan your local library first.'}), 400
    
    # Apply filters
    search_term = request.args.get('search', '').lower()
    author = request.args.get('author')
    series = request.args.get('series')
    language = request.args.get('language')
    
    filtered_books = local_books
    
    if search_term:
        filtered_books = [
            book for book in filtered_books
            if search_term in book.get('title', '').lower() or 
               search_term in book.get('authors', '').lower()
        ]
    
    if author:
        filtered_books = [
            book for book in filtered_books
            if author.lower() in book.get('authors', '').lower()
        ]
    
    if series:
        filtered_books = [
            book for book in filtered_books
            if book.get('series') and series.lower() in book.get('series', '').lower()
        ]
    
    if language and language != 'all':
        filtered_books = [
            book for book in filtered_books
            if book.get('language') == language
        ]
    
    # Get unique values for filters
    all_authors = sorted(set(book.get('authors', '') for book in local_books if book.get('authors')))
    all_series = sorted(set(book.get('series', '') for book in local_books if book.get('series')))
    all_languages = sorted(set(book.get('language', 'unknown') for book in local_books))
    
    return jsonify({
        'success': True,
        'books': filtered_books,
        'total_books': len(local_books),
        'filtered_count': len(filtered_books),
        'library_path': local_library_data.get('path'),
        'filters': {
            'authors': all_authors,
            'series': all_series,
            'languages': all_languages
        }
    })

@library_bp.route('/stats', methods=['GET'])
def get_library_stats():
    """Get library statistics and comparison summary."""
    audible_library = session.get('library', [])
    local_library_data = session.get('local_library', {})
    local_books = local_library_data.get('books', [])
    comparison = session.get('library_comparison', {})
    
    # Calculate statistics
    stats = {
        'audible': {
            'total_books': len(audible_library),
            'total_hours': sum(book.get('length_mins', 0) for book in audible_library) / 60 if audible_library else 0
        },
        'local': {
            'total_books': len(local_books),
            'total_size_gb': sum(book.get('file_size', 0) for book in local_books) / (1024**3) if local_books else 0,
            'library_path': local_library_data.get('path'),
            'languages': {}
        },
        'comparison': {
            'missing_count': comparison.get('missing_count', 0),
            'available_count': comparison.get('available_count', 0),
            'local_only_count': comparison.get('local_only_count', 0),
            'coverage_percentage': (comparison.get('available_count', 0) / len(audible_library) * 100) if audible_library else 0
        }
    }
    
    # Language breakdown for local library
    if local_books:
        language_counts = {}
        for book in local_books:
            lang = book.get('language', 'unknown')
            language_counts[lang] = language_counts.get(lang, 0) + 1
        stats['local']['languages'] = language_counts
    
    # Author breakdown
    if audible_library:
        audible_authors = {}
        for book in audible_library:
            author = book.get('authors', 'Unknown')
            audible_authors[author] = audible_authors.get(author, 0) + 1
        stats['audible']['top_authors'] = sorted(audible_authors.items(), key=lambda x: x[1], reverse=True)[:10]
    
    return jsonify({
        'success': True,
        'stats': stats
    })

@library_bp.route('/set-path', methods=['POST'])
def set_library_path():
    """Set or update the local library path."""
    data = request.get_json()
    library_path = data.get('library_path')
    
    if not library_path:
        return jsonify({'error': 'Library path is required'}), 400
    
    if not os.path.exists(library_path):
        return jsonify({'error': f'Path does not exist: {library_path}'}), 400
    
    if not os.path.isdir(library_path):
        return jsonify({'error': f'Path is not a directory: {library_path}'}), 400
    
    # Clear any existing local library data
    session.pop('local_library', None)
    session.pop('library_comparison', None)
    
    # Store the path in app config (this could be persisted to a config file)
    current_app.config['LOCAL_LIBRARY_PATH'] = library_path
    
    return jsonify({
        'success': True,
        'message': f'Library path set to: {library_path}',
        'library_path': library_path
    })

@library_bp.route('/list', methods=['GET'])
def list_libraries():
    """List all stored libraries."""
    try:
        summary = storage.get_library_summary()
        return jsonify({
            'success': True,
            'summary': summary
        })
    except Exception as e:
        logger.error(f"Error listing libraries: {e}")
        return jsonify({'error': f'Failed to list libraries: {str(e)}'}), 500

@library_bp.route('/library/<library_id>', methods=['GET'])
def get_library_details(library_id):
    """Get detailed information about a specific library."""
    try:
        library_data = storage.load_library(library_id)
        if not library_data:
            return jsonify({'error': 'Library not found'}), 404
        
        return jsonify({
            'success': True,
            'library': library_data
        })
    except Exception as e:
        logger.error(f"Error getting library details: {e}")
        return jsonify({'error': f'Failed to get library details: {str(e)}'}), 500

@library_bp.route('/library/<library_id>', methods=['DELETE'])
def delete_library(library_id):
    """Delete a library from storage."""
    try:
        success = storage.delete_library(library_id)
        if success:
            return jsonify({
                'success': True,
                'message': f'Library {library_id} deleted successfully'
            })
        else:
            return jsonify({'error': 'Library not found'}), 404
    except Exception as e:
        logger.error(f"Error deleting library: {e}")
        return jsonify({'error': f'Failed to delete library: {str(e)}'}), 500

@library_bp.route('/comparisons', methods=['GET'])
def list_comparisons():
    """List all library comparisons."""
    try:
        comparisons = storage.list_comparisons()
        return jsonify({
            'success': True,
            'comparisons': comparisons
        })
    except Exception as e:
        logger.error(f"Error listing comparisons: {e}")
        return jsonify({'error': f'Failed to list comparisons: {str(e)}'}), 500