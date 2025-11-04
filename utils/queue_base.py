"""
Base Queue Manager - Abstract base class for queue management.
Provides common functionality for DownloadQueueManager and ImportQueueManager.
"""
import json
import time
from pathlib import Path
from abc import ABC, abstractmethod
from typing import Dict, Optional


class BaseQueueManager(ABC):
    """
    Abstract base class for queue managers with singleton pattern.
    Provides common functionality for queue persistence and statistics.
    """
    _instance = None
    
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance
    
    def __init__(self, queue_file: Path):
        """
        Initialize the queue manager.
        
        Args:
            queue_file: Path to the queue JSON file
        """
        # Only initialize once (singleton pattern)
        if self._initialized:
            return
        
        self._initialized = True
        self._queue_file = queue_file
        self._queue_file.parent.mkdir(parents=True, exist_ok=True)
        
        # Load existing queue or create empty
        self._load_queue()
        
        # Initialize batch tracking
        if '_batch_info' not in self._queue:
            self._queue['_batch_info'] = {
                'current_batch_id': None,
                'batch_complete': False,
                'batch_start_time': None
            }
    
    def _load_queue(self):
        """Load queue from disk"""
        if self._queue_file.exists():
            try:
                with open(self._queue_file, 'r') as f:
                    self._queue = json.load(f)
            except (json.JSONDecodeError, IOError) as e:
                self._log_warning(f"Could not load queue: {e}")
                self._queue = {}
        else:
            self._queue = {}
    
    def _save_queue(self):
        """Persist queue to disk"""
        try:
            with open(self._queue_file, 'w') as f:
                json.dump(self._queue, f, indent=2)
        except IOError as e:
            self._log_warning(f"Could not save queue: {e}")
    
    def get_all_items(self) -> Dict:
        """
        Get all items in the queue (excluding batch info and metadata).
        
        Returns:
            Dictionary of queue items
        """
        return {k: v for k, v in self._queue.items() if not k.startswith('_')}
    
    def get_item(self, item_id: str) -> Optional[Dict]:
        """
        Get a specific item from the queue.
        
        Args:
            item_id: Unique identifier for the item (e.g., ASIN or file path)
        
        Returns:
            Item data or None if not found
        """
        return self._queue.get(item_id)
    
    def update_item(self, item_id: str, updates: Dict):
        """
        Update an item in the queue.
        
        Args:
            item_id: Unique identifier for the item
            updates: Dictionary of updates to apply
        """
        if item_id not in self._queue:
            self._queue[item_id] = {}
        
        # Merge updates into existing entry
        self._queue[item_id].update(updates)
        self._queue[item_id]['last_updated'] = time.time()
        
        # Persist to disk
        self._save_queue()
    
    def add_to_queue(self, item_id: str, title: str, initial_state: str, **metadata):
        """
        Add a new item to the queue.
        
        Args:
            item_id: Unique identifier for the item
            title: Display title for the item
            initial_state: Initial state value
            **metadata: Additional metadata for the item
        """
        # Check if we need to start a new batch
        batch_info = self._queue.get('_batch_info', {})
        
        # Start a new batch if no current batch exists or current batch is complete
        if not batch_info.get('current_batch_id') or batch_info.get('batch_complete', False):
            batch_id = self._generate_batch_id()
            self._queue['_batch_info'] = {
                'current_batch_id': batch_id,
                'batch_complete': False,
                'batch_start_time': time.time()
            }
        
        self._queue[item_id] = {
            self._get_item_id_key(): item_id,
            'title': title,
            'state': initial_state,
            'added_at': time.time(),
            'last_updated': time.time(),
            'batch_id': self._queue['_batch_info']['current_batch_id'],
            **metadata
        }
        self._save_queue()
    
    def remove_from_queue(self, item_id: str):
        """
        Remove an item from the queue.
        
        Args:
            item_id: Unique identifier for the item
        """
        if item_id in self._queue:
            del self._queue[item_id]
            self._save_queue()
    
    def get_batch_info(self) -> Dict:
        """
        Get current batch information.
        
        Returns:
            Dictionary with batch metadata
        """
        return self._queue.get('_batch_info', {})
    
    def mark_batch_complete(self):
        """Mark the current batch as complete"""
        if '_batch_info' in self._queue:
            self._queue['_batch_info']['batch_complete'] = True
            self._save_queue()
    
    def clear_old_items(self, older_than_hours: int = 24):
        """
        Clear items older than specified hours from completed batches.
        
        Args:
            older_than_hours: Remove items older than this many hours
        """
        current_time = time.time()
        cutoff_time = current_time - (older_than_hours * 3600)
        batch_info = self._queue.get('_batch_info', {})
        current_batch_id = batch_info.get('current_batch_id')
        
        items_to_remove = []
        for item_id, item_data in self._queue.items():
            # Skip metadata entries
            if item_id.startswith('_'):
                continue
            
            # Don't remove items from current batch
            if item_data.get('batch_id') == current_batch_id:
                continue
            
            # Check if item is old enough
            last_updated = item_data.get('last_updated', 0)
            if last_updated < cutoff_time:
                items_to_remove.append(item_id)
        
        # Remove old items
        for item_id in items_to_remove:
            del self._queue[item_id]
        
        if items_to_remove:
            self._save_queue()
        
        return len(items_to_remove)
    
    @abstractmethod
    def get_statistics(self) -> Dict:
        """
        Get queue statistics. Must be implemented by subclasses.
        
        Returns:
            Dictionary with statistics specific to the queue type
        """
        pass
    
    @abstractmethod
    def _generate_batch_id(self) -> str:
        """
        Generate a unique batch ID. Must be implemented by subclasses.
        
        Returns:
            Unique batch identifier
        """
        pass
    
    @abstractmethod
    def _get_item_id_key(self) -> str:
        """
        Get the key name for the item ID field. Must be implemented by subclasses.
        For downloads: 'asin'
        For imports: 'file_path'
        
        Returns:
            Key name for the item ID
        """
        pass
    
    @abstractmethod
    def _log_warning(self, message: str):
        """
        Log a warning message. Must be implemented by subclasses.
        
        Args:
            message: Warning message to log
        """
        pass

