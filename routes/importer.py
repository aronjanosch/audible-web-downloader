"""
Importer routes for M4B audiobook import functionality.
Handles scanning, matching, and importing M4B files with Audible metadata.
"""

from flask import Blueprint, request, jsonify, session, current_app
import asyncio
import logging
from pathlib import Path
from typing import Dict, List
import json

from importer import AudiobookImporter, ImportQueueManager

importer_bp = Blueprint('importer', __name__, url_prefix='/api/importer')
logger = logging.getLogger(__name__)

# Global queue manager instance
queue_manager = ImportQueueManager()


@importer_bp.route('/scan', methods=['POST'])
def scan_source_directory():
    """
    Scan source directory for M4B files.
    
    Request body:
        {
            "source_path": "/path/to/source",
            "library_path": "/path/to/library",
            "account_name": "account_name"
        }
    
    Response:
        {
            "success": true,
            "files": [...],
            "count": 10,
            "total_size": 1234567890,
            "errors": []
        }
    """
    try:
        data = request.get_json()
        source_path = data.get('source_path')
        library_path = data.get('library_path')
        account_name = data.get('account_name')
        region = data.get('region', 'us')
        
        if not source_path:
            return jsonify({'error': 'source_path is required'}), 400
        
        if not library_path:
            return jsonify({'error': 'library_path is required'}), 400
        
        if not account_name:
            return jsonify({'error': 'account_name is required'}), 400
        
        # Validate paths
        if not Path(source_path).exists():
            return jsonify({'error': f'Source path does not exist: {source_path}'}), 400
        
        if not Path(library_path).exists():
            return jsonify({'error': f'Library path does not exist: {library_path}'}), 400
        
        # Initialize importer
        try:
            importer = AudiobookImporter(account_name, region, library_path)
        except ValueError as e:
            return jsonify({'error': str(e)}), 400
        
        # Scan directory
        files = importer.scan_directory(source_path)
        
        # Calculate total size
        total_size = sum(f.get('file_size', 0) for f in files)
        
        # Store scan results in session for later use
        session['import_scan_results'] = {
            'files': files,
            'source_path': source_path,
            'library_path': library_path,
            'account_name': account_name,
            'region': region
        }
        
        return jsonify({
            'success': True,
            'files': files,
            'count': len(files),
            'total_size': total_size,
            'errors': []
        })
        
    except Exception as e:
        logger.error(f"Error scanning directory: {e}", exc_info=True)
        return jsonify({'error': f'Failed to scan directory: {str(e)}'}), 500


@importer_bp.route('/match', methods=['POST'])
def match_files():
    """
    Match scanned files with Audible metadata.
    
    Request body:
        {
            "files": [...],
            "account_name": "account_name",
            "region": "us",
            "library_path": "/path/to/library"
        }
    
    Response:
        {
            "success": true,
            "matched_files": [{
                "file_info": {...},
                "audible_match": {...},
                "confidence": 0.95,
                "duplicate_status": {...},
                "selected": true/false
            }],
            "stats": {
                "matched": 5,
                "uncertain": 2,
                "not_found": 1,
                "duplicates": 2
            }
        }
    """
    try:
        data = request.get_json()
        files = data.get('files', [])
        account_name = data.get('account_name')
        region = data.get('region', 'us')
        library_path = data.get('library_path')
        
        if not files:
            return jsonify({'error': 'files list is required'}), 400
        
        if not account_name:
            return jsonify({'error': 'account_name is required'}), 400
        
        if not library_path:
            return jsonify({'error': 'library_path is required'}), 400
        
        # Initialize importer
        try:
            importer = AudiobookImporter(account_name, region, library_path)
        except ValueError as e:
            return jsonify({'error': str(e)}), 400
        
        # Match files with Audible (async operation)
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        
        matched_files = []
        stats = {
            'matched': 0,
            'uncertain': 0,
            'not_found': 0,
            'duplicates': 0,
            'total': len(files)
        }
        
        for file_info in files:
            try:
                # Match with Audible
                match_result = loop.run_until_complete(
                    importer.match_with_audible(file_info)
                )
                
                # Check for duplicates
                selected_match = match_result.get('selected_match')
                duplicate_status = importer.check_duplicate(file_info, selected_match)
                
                # Determine if file should be selected for import
                selected = False
                if duplicate_status:
                    stats['duplicates'] += 1
                    selected = False  # Auto-deselect duplicates
                elif match_result['status'] == 'matched':
                    stats['matched'] += 1
                    selected = True
                elif match_result['status'] == 'uncertain':
                    stats['uncertain'] += 1
                    selected = False  # User must review uncertain matches
                else:
                    stats['not_found'] += 1
                    selected = False
                
                matched_files.append({
                    'file_info': file_info,
                    'match_result': match_result,
                    'duplicate_status': duplicate_status,
                    'selected': selected
                })
                
            except Exception as e:
                logger.error(f"Error matching file {file_info.get('file_path')}: {e}")
                matched_files.append({
                    'file_info': file_info,
                    'match_result': {
                        'status': 'error',
                        'reason': str(e),
                        'matches': [],
                        'confidence': 0.0
                    },
                    'duplicate_status': None,
                    'selected': False
                })
        
        loop.close()
        
        # Store results in session
        session['import_match_results'] = {
            'matched_files': matched_files,
            'stats': stats,
            'account_name': account_name,
            'region': region,
            'library_path': library_path
        }
        
        return jsonify({
            'success': True,
            'matched_files': matched_files,
            'stats': stats
        })
        
    except Exception as e:
        logger.error(f"Error matching files: {e}", exc_info=True)
        return jsonify({'error': f'Failed to match files: {str(e)}'}), 500


@importer_bp.route('/preview-path', methods=['POST'])
def preview_import_path():
    """
    Preview the target import path for a file.
    
    Request body:
        {
            "audible_product": {...},
            "library_path": "/path/to/library"
        }
    
    Response:
        {
            "success": true,
            "target_path": "/path/to/library/Author/Title.m4b"
        }
    """
    try:
        data = request.get_json()
        audible_product = data.get('audible_product')
        library_path = data.get('library_path')
        
        if not audible_product:
            return jsonify({'error': 'audible_product is required'}), 400
        
        if not library_path:
            return jsonify({'error': 'library_path is required'}), 400
        
        # Use a temporary importer instance to build the path
        # We don't need authentication for path building
        from downloader import AudiobookDownloader
        
        # Create a minimal downloader instance for path building
        downloader = AudiobookDownloader(
            account_name="temp",
            region="us",
            library_path=library_path,
            downloads_dir="downloads"
        )
        
        # Build the target path
        target_path = downloader.build_path_from_pattern(
            base_path=library_path,
            title=audible_product.get('title', 'Unknown'),
            authors=audible_product.get('authors', []),
            narrators=audible_product.get('narrators', []),
            series=audible_product.get('series'),
            release_date=audible_product.get('release_date'),
            publisher=audible_product.get('publisher_name'),
            language=audible_product.get('language'),
            asin=audible_product.get('asin')
        )
        
        return jsonify({
            'success': True,
            'target_path': str(target_path)
        })
        
    except Exception as e:
        logger.error(f"Error generating path preview: {e}", exc_info=True)
        return jsonify({'error': f'Failed to generate preview: {str(e)}'}), 500


@importer_bp.route('/search-manual', methods=['POST'])
def manual_search():
    """
    Manual Audible search for specific file.
    
    Request body:
        {
            "file_path": "/path/to/file.m4b",
            "search_query": "book title author",
            "account_name": "account_name",
            "region": "us"
        }
    
    Response:
        {
            "success": true,
            "results": [...audible products...]
        }
    """
    try:
        data = request.get_json()
        file_path = data.get('file_path')
        search_query = data.get('search_query')
        account_name = data.get('account_name')
        region = data.get('region', 'us')
        library_path = data.get('library_path')
        
        if not search_query:
            return jsonify({'error': 'search_query is required'}), 400
        
        if not account_name:
            return jsonify({'error': 'account_name is required'}), 400
        
        if not library_path:
            return jsonify({'error': 'library_path is required'}), 400
        
        # Initialize importer
        try:
            importer = AudiobookImporter(account_name, region, library_path)
        except ValueError as e:
            return jsonify({'error': str(e)}), 400
        
        # Search Audible
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        
        results = loop.run_until_complete(
            importer.search_audible_catalog(search_query, num_results=10)
        )
        
        loop.close()
        
        return jsonify({
            'success': True,
            'results': results,
            'query': search_query
        })
        
    except Exception as e:
        logger.error(f"Error performing manual search: {e}", exc_info=True)
        return jsonify({'error': f'Failed to search: {str(e)}'}), 500


@importer_bp.route('/execute', methods=['POST'])
def execute_import():
    """
    Execute import for selected files.
    
    Request body:
        {
            "imports": [
                {
                    "file_path": "/path/to/file.m4b",
                    "audible_product": {...}
                }
            ],
            "library_path": "/path/to/library",
            "account_name": "account_name",
            "region": "us"
        }
    
    Response:
        {
            "success": true,
            "batch_id": "import_batch_123456",
            "message": "Import started for 5 files"
        }
    """
    try:
        data = request.get_json()
        imports = data.get('imports', [])
        library_path = data.get('library_path')
        account_name = data.get('account_name')
        region = data.get('region', 'us')
        
        if not imports:
            return jsonify({'error': 'imports list is required'}), 400
        
        if not library_path:
            return jsonify({'error': 'library_path is required'}), 400
        
        if not account_name:
            return jsonify({'error': 'account_name is required'}), 400
        
        # Initialize importer
        try:
            importer = AudiobookImporter(account_name, region, library_path)
        except ValueError as e:
            return jsonify({'error': str(e)}), 400
        
        # Start a new batch with expected count to prevent race conditions
        batch_id = queue_manager.start_new_batch(expected_count=len(imports))
        logger.info(f"Started new import batch {batch_id} with {len(imports)} files")
        
        # Add all imports to queue
        for import_item in imports:
            file_path = import_item['file_path']
            audible_product = import_item['audible_product']
            title = audible_product.get('title', Path(file_path).stem)
            
            queue_manager.add_import_to_queue(
                file_path=file_path,
                title=title,
                audible_product=audible_product
            )
        
        # Start import in background thread
        def run_import():
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            try:
                results = loop.run_until_complete(importer.batch_import(imports))
                logger.info(f"Import completed: {results}")
            except Exception as e:
                logger.error(f"Import failed: {e}", exc_info=True)
            finally:
                loop.close()
        
        import threading
        import_thread = threading.Thread(target=run_import, daemon=True)
        import_thread.start()
        
        return jsonify({
            'success': True,
            'batch_id': batch_id,
            'message': f'Import started for {len(imports)} file(s)',
            'count': len(imports)
        })
        
    except Exception as e:
        logger.error(f"Error executing import: {e}", exc_info=True)
        return jsonify({'error': f'Failed to execute import: {str(e)}'}), 500


@importer_bp.route('/progress', methods=['GET'])
def get_import_progress():
    """
    Get import progress for current batch.
    
    Response:
        {
            "success": true,
            "statistics": {
                "active": 2,
                "queued": 3,
                "completed": 5,
                "failed": 1,
                "skipped": 2,
                "total_imports": 13,
                "batch_complete": false,
                "batch_id": "import_batch_123456"
            },
            "imports": {...}
        }
    """
    try:
        stats = queue_manager.get_statistics()
        imports = queue_manager.get_all_imports()
        
        return jsonify({
            'success': True,
            'statistics': stats,
            'imports': imports
        })
        
    except Exception as e:
        logger.error(f"Error getting import progress: {e}", exc_info=True)
        return jsonify({'error': f'Failed to get progress: {str(e)}'}), 500


@importer_bp.route('/clear-queue', methods=['POST'])
def clear_import_queue():
    """
    Clear completed imports from queue.
    
    Request body:
        {
            "older_than_hours": 24
        }
    
    Response:
        {
            "success": true,
            "cleared_count": 5
        }
    """
    try:
        data = request.get_json() or {}
        older_than_hours = data.get('older_than_hours', 24)
        
        cleared_count = queue_manager.clear_completed(older_than_hours)
        
        return jsonify({
            'success': True,
            'cleared_count': cleared_count
        })
        
    except Exception as e:
        logger.error(f"Error clearing queue: {e}", exc_info=True)
        return jsonify({'error': f'Failed to clear queue: {str(e)}'}), 500


@importer_bp.route('/libraries', methods=['GET'])
def get_libraries():
    """
    Get list of available libraries for import target selection.
    
    Response:
        {
            "success": true,
            "libraries": [...]
        }
    """
    try:
        # Use the same config manager as the main libraries endpoint for consistency
        from utils.config_manager import get_config_manager

        config_manager = get_config_manager()
        libraries_dict = config_manager.get_libraries()
        
        # Convert dict format to array format for importer UI
        libraries_array = []
        for name, config in libraries_dict.items():
            libraries_array.append({
                'name': name,
                'path': config.get('path'),
                'created_at': config.get('created_at')
            })
        
        logger.info(f"Importer libraries endpoint: Found {len(libraries_array)} libraries")
        
        return jsonify({
            'success': True,
            'libraries': libraries_array
        })
        
    except Exception as e:
        logger.error(f"Error getting libraries: {e}", exc_info=True)
        return jsonify({'error': f'Failed to get libraries: {str(e)}'}), 500

