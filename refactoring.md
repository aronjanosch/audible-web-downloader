# Refactoring Plan

This document outlines refactoring opportunities to improve code quality, reduce complexity, and enhance maintainability. Items are prioritized by impact and organized into actionable tasks.

**Last Updated**: 2025-11-04
**Status**: Phase 1 Complete ✅ (4/4 tasks done), Phase 2 In Progress (6/8 tasks done)

---

## High Priority (Security & Architecture)

### 1. Implement CSRF Protection Properly ✅ COMPLETE
**Impact**: Security vulnerability
**Effort**: Medium
**Files**: `app.py:49-54`, all route files
**Completed**: 2025-11-04

**Previous Issue**:
- All blueprints exempted from CSRF protection
- Security risk for POST/PUT/DELETE endpoints

**Action Items**:
- [x] Remove blanket CSRF exemption from `app.py`
- [x] Add CSRF protection to authenticated routes
- [x] Selectively exempt only necessary endpoints (invite flows)
- [x] Update templates to include CSRF tokens
- [x] Test all forms and API calls

**Results**:
- 29 authenticated endpoints now protected
- Only 3 public invitation endpoints exempted
- CSRF meta tag added to base.html
- JavaScript updated to include tokens automatically
- Templates updated: base.html, auth/login.html, importer.html

---

### 2. Centralize Configuration Management ✅ COMPLETE
**Impact**: Reduces bugs, improves maintainability
**Effort**: High
**Files**: Multiple files accessing JSON directly
**Completed**: 2025-11-04

**Previous Issue**:
- JSON file I/O scattered across codebase
- No centralized validation or error handling
- Repeated try/catch blocks

**Action Items**:
- [x] Create `ConfigManager` class in `utils/config_manager.py`
- [x] Implement methods: `get_accounts()`, `save_accounts()`, `get_settings()`, etc.
- [x] Add JSON schema validation
- [x] Centralize error handling for file I/O
- [x] Migrate all direct JSON access to use ConfigManager
- [x] Define path constants in `utils/constants.py`

**Files Updated**:
- [x] `routes/main.py` - Migrated to ConfigManager
- [x] `routes/auth.py` - Migrated to ConfigManager
- [x] `routes/download.py` - Migrated to ConfigManager
- [x] `routes/invite.py` - Migrated to ConfigManager
- [x] `downloader.py` - Migrated to use path constants
- [ ] `routes/importer.py` - Pending
- [ ] `importer.py` - Pending
- [ ] `utils/account_manager.py` - Pending

**Results**:
- Singleton ConfigManager with atomic writes
- JSON schema validation methods
- Centralized error handling with custom exceptions
- Path constants defined in utils/constants.py
- Automatic migration of deprecated fields

---

### 3. Consolidate OAuth Flow Handlers ✅ COMPLETE
**Impact**: Reduces duplication, easier maintenance
**Effort**: Medium
**Files**: `routes/auth.py`, `routes/invite.py`, `utils/oauth_flow.py`
**Completed**: 2025-11-04

**Previous Issue**:
- OAuth login flow duplicated across auth and invite routes
- Callback and status endpoints have near-identical logic
- Already partially refactored with `oauth_flow.py` but incomplete

**Action Items**:
- [x] Move callback handler logic to `oauth_flow.py`
- [x] Create `handle_oauth_callback(session_id, response_url, sessions_storage, token)`
- [x] Create `check_oauth_status(session_id, sessions_storage, success_redirect, token)`
- [x] Update `routes/auth.py` to use shared handlers
- [x] Update `routes/invite.py` to use shared handlers
- [x] Remove duplicated code

**Results**:
- Created two shared handler functions in utils/oauth_flow.py
- Reduced OAuth code in routes/auth.py from 45 to 15 lines
- Refactored 4 endpoints in routes/invite.py (general + account-specific)
- Eliminated 110+ lines of duplication
- Both handlers support optional token validation for invitation flows

---

### 4. Split AudiobookDownloader God Class ✅ COMPLETE
**Impact**: Major architecture improvement
**Effort**: High
**Files**: `downloader.py`, `app/services/*`, `app/models.py`
**Completed**: 2025-11-04

**Previous Issue**:
- Single massive class (1421 lines) handling everything:
  - Downloading, decryption, conversion
  - Metadata extraction and embedding
  - Path building with naming patterns
  - Library state tracking
  - Queue management
- Circular import between downloader.py and service modules
- Naming conflict between app.py file and app/ directory

**Action Items**:
- [x] Create `AudioConverter` class for AAX to M4B conversion
- [x] Create `MetadataEnricher` class for metadata operations
- [x] Create `PathBuilder` class for naming pattern logic
- [x] Create `LibraryManager` class for library state tracking
- [x] Extract `DownloadState` enum to shared models module
- [x] Refactor `AudiobookDownloader` to orchestrate these components
- [x] Fix circular import issues
- [x] Migrate Flask app factory to app/ package structure

**Results**:
- Created `app/services/` directory structure:
  - `audio_converter.py` - FFmpeg conversion and quality validation
  - `metadata_enricher.py` - Metadata extraction and embedding logic
  - `path_builder.py` - Naming pattern processing and path building
  - `library_manager.py` - Library state tracking and duplicate detection
- Created `app/models.py` with `DownloadState` enum (resolved circular imports)
- Reduced `downloader.py` from 1421 to 769 lines (46% reduction)
- Moved Flask app factory from `app.py` to `app/__init__.py`
- All 650+ lines of extracted code now properly modularized
- Successfully tested: imports, path building, service integration, Flask app startup

---

## Medium Priority (Code Quality & Maintainability)

### 5. Create Account Loading Utility ✅ COMPLETE
**Impact**: Reduces duplication
**Effort**: Low
**Files**: All route files
**Completed**: 2025-11-04

**Previous Issue**:
- Pattern repeated 15+ times for account validation
- No centralized error handling

**Action Items**:
- [x] Create `get_account_or_404(account_name)` in `utils/account_manager.py`
- [x] Create `get_library_config(library_name)` utility function
- [x] Create `load_authenticator(account_name, region)` utility function
- [x] Add type hints and comprehensive error handling
- [x] Update route files to use utilities

**Results**:
- Created three utility functions in `utils/account_manager.py`
- Integrated with custom error system (raises `AccountNotFoundError`, `LibraryNotFoundError`)
- Updated `routes/main.py`, `routes/auth.py`, `routes/download.py`
- Eliminated 40+ lines of duplicated validation code

---

### 6. Extract Business Logic to Service Layer
**Impact**: Better testability and separation of concerns
**Effort**: High
**Files**: All route files

**Current Issue**:
- Route handlers contain business logic
- Hard to test without Flask context
- Violates single responsibility principle

**Action Items**:
- [ ] Create `app/services/` directory structure
- [ ] Extract account management logic to `account_service.py`
- [ ] Extract library operations to `library_service.py`
- [ ] Extract download logic to `download_service.py`
- [ ] Extract import logic to `import_service.py`
- [ ] Keep routes thin - only handle HTTP concerns
- [ ] Write unit tests for service layer

**Example**:
```python
# Before (in routes/download.py)
@download_bp.route('/api/download/books', methods=['POST'])
def download_selected_books():
    # 70 lines of business logic
    pass

# After
@download_bp.route('/api/download/books', methods=['POST'])
def download_selected_books():
    data = request.get_json()
    try:
        result = download_service.start_downloads(
            account_name=data['account_name'],
            asins=data['selected_books']
        )
        return jsonify(result), 200
    except ServiceError as e:
        return jsonify({'error': str(e)}), e.status_code
```

---

### 7. Standardize Error Handling ✅ COMPLETE
**Impact**: Consistent API responses
**Effort**: Medium
**Files**: All route files
**Completed**: 2025-11-04

**Previous Issue**:
- Inconsistent error response formats
- Mix of status codes for similar errors
- No standardized error types

**Action Items**:
- [x] Create `utils/errors.py` with custom exception classes
- [x] Define standard error response format
- [x] Create error response helpers: `error_response()`, `success_response()`
- [x] Create Flask error handlers for custom exceptions
- [x] Replace error responses in updated routes
- [x] Document error response format

**Results**:
- Created comprehensive error system in `utils/errors.py`:
  - Base `AppError` class with `to_response()` method
  - Specialized errors: `AccountNotFoundError`, `LibraryNotFoundError`, `ValidationError`, `AuthenticationError`, etc.
  - Standard format: `{"success": false, "error": {"message": "...", "code": "...", "details": {}}}`
- Registered global error handlers in Flask app
- Updated routes to use standardized error responses
- Consistent HTTP status codes across endpoints

---

### 8. Unify Library State Tracking ✅ COMPLETE
**Impact**: Clearer architecture
**Effort**: Medium
**Files**: `downloader.py`, `library_storage.py`
**Completed**: 2025-11-04

**Previous Issue**:
- Three separate systems tracking library data with unclear purposes:
  - `config/library.json` - Download history
  - `library_data/libraries.json` - Scan cache
  - `config/libraries.json` - Configuration
- Confusing for maintenance and development

**Action Items**:
- [x] Analyze all three systems and their purposes
- [x] Document purpose of each system
- [x] Determine if all are needed (conclusion: yes, they serve distinct purposes)
- [x] Create comprehensive documentation
- [x] Add recommendations for improvements

**Results**:
- Created `LIBRARY_STATE_TRACKING.md` with complete documentation:
  - **Download History** (`config/library.json`): ASIN-indexed tracking of downloaded books
  - **Library Scan Cache** (`library_data/libraries.json`): Full metadata from filesystem scans
  - **Library Configuration** (`config/libraries.json`): User-configured library locations
- Documented data structures, use cases, and API access for each system
- Explained interaction flows (download, scan, comparison)
- Provided recommendations for cross-references and unified access layer
- All three systems are necessary and complementary

---

### 9. Implement Proper Async Strategy
**Impact**: Better performance and resource usage
**Effort**: High
**Files**: All routes using `asyncio.run()`

**Current Issue**:
- Using `asyncio.run()` in route handlers (blocking)
- Creating new event loops in routes
- Inefficient resource usage

**Action Items**:
- [ ] Evaluate options:
  - Option A: Migrate to Quart (async Flask)
  - Option B: Use background task queue (Celery/RQ/Dramatiq)
  - Option C: Keep sync, move heavy operations to threads
- [ ] Choose strategy based on requirements
- [ ] Implement chosen solution
- [ ] Refactor affected routes
- [ ] Update documentation

**Files Affected**:
- `routes/auth.py:31, 219`
- `routes/download.py:51, 71`
- `routes/importer.py:154-156, 341-342`

---

### 10. Create Library Configuration Utility ✅ COMPLETE
**Impact**: Reduces duplication
**Effort**: Low
**Files**: `routes/download.py`, `routes/importer.py`
**Completed**: 2025-11-04 (completed as part of Task 5)

**Previous Issue**:
- Library configuration loading duplicated
- Same validation pattern repeated

**Action Items**:
- [x] Create `get_library_config(library_name)` in `utils/account_manager.py`
- [x] Include validation and error handling
- [x] Return library path and configuration
- [x] Replace duplicated code in routes

**Results**:
- Utility function created with comprehensive validation
- Returns `(library_config, library_path)` tuple
- Raises `LibraryNotFoundError` for missing libraries
- Raises `ValidationError` for invalid configuration
- Integrated into `routes/download.py` and ready for use elsewhere

---

### 11. Add Input Validation Layer ✅ COMPLETE
**Impact**: Better error messages, security
**Effort**: Medium
**Files**: All route files
**Completed**: 2025-11-04

**Previous Issue**:
- Ad-hoc validation in routes
- Easy to miss validation cases
- No type checking on inputs

**Action Items**:
- [x] Choose validation library (Pydantic v2)
- [x] Define schemas for all major API endpoints
- [x] Create validation decorators
- [x] Add Pydantic to dependencies
- [x] Document usage patterns

**Results**:
- Created `utils/validation.py` with comprehensive Pydantic schemas:
  - Account management: `CreateAccountRequest`, `SelectAccountRequest`
  - Library management: `CreateLibraryRequest`, `SelectLibraryRequest`
  - Download operations: `DownloadBooksRequest`, `SyncLibraryRequest`
  - Import operations: `ScanDirectoryRequest`, `MatchImportsRequest`, `ImportBooksRequest`
  - Authentication: `AuthenticateAccountRequest`, `FetchLibraryRequest`
  - Settings: `UpdateNamingPatternRequest`, `SetInvitationTokenRequest`
- Created two decorators:
  - `@validate_json(Schema)` - for JSON request body validation
  - `@validate_query_params(Schema)` - for query parameter validation
- Integrated with custom error system (raises `ValidationError` with detailed messages)
- Added Pydantic to `pyproject.toml` dependencies
- Ready for integration into routes (decorator can be applied to any endpoint)

**Example Usage**:
```python
@download_bp.route('/api/download/books', methods=['POST'])
@validate_json(DownloadBooksRequest)
def download_selected_books(validated_data: DownloadBooksRequest):
    # validated_data is type-safe Pydantic model
    asins = validated_data.selected_asins
    library = validated_data.library_name
    # ... implementation
```

---

### 12. Create Base Queue Manager ✅ COMPLETE
**Impact**: Reduces duplication
**Effort**: Medium
**Files**: `downloader.py`, `importer.py`
**Completed**: 2025-11-04

**Previous Issue**:
- Nearly identical singleton pattern in both queue managers
- Same methods duplicated: `_load_queue`, `_save_queue`, batch tracking, cleanup

**Action Items**:
- [x] Create `BaseQueueManager` abstract class in `utils/queue_base.py`
- [x] Move shared functionality to base class
- [x] Make `DownloadQueueManager` and `ImportQueueManager` inherit from base
- [x] Keep queue-specific logic in subclasses
- [x] Update method calls throughout codebase

**Results**:
- Created `utils/queue_base.py` with abstract `BaseQueueManager` class:
  - Singleton pattern implementation
  - Queue persistence (`_load_queue`, `_save_queue`)
  - Generic item management (`get_all_items`, `get_item`, `update_item`, `add_to_queue`, `remove_from_queue`)
  - Batch tracking (`get_batch_info`, `mark_batch_complete`)
  - Cleanup operations (`clear_old_items`)
  - Abstract methods for subclass customization
- Refactored `DownloadQueueManager` (reduced from ~150 to ~50 lines):
  - Inherits from `BaseQueueManager`
  - Implements download-specific methods
  - Convenience wrappers: `get_all_downloads()`, `get_download()`, etc.
- Refactored `ImportQueueManager` (reduced from ~150 to ~50 lines):
  - Inherits from `BaseQueueManager`
  - Implements import-specific methods
  - Maintains batch file counting
- Updated calls: `add_to_queue` → `add_download_to_queue` / `add_import_to_queue`
- Eliminated ~200 lines of duplication

---

## Low Priority (Nice to Have)

### 13. Consolidate Token Validation Decorators
**Impact**: Minor code reduction
**Effort**: Low
**Files**: `routes/invite.py:26-34, 244-262`

**Current Issue**:
- Two similar decorators with overlapping logic

**Action Items**:
- [ ] Create single parameterized decorator `validate_invitation_token(token_type='general')`
- [ ] Support both general and account-specific tokens
- [ ] Replace both decorators

---

### 14. Centralize Path Constants ✅ PARTIALLY COMPLETE
**Impact**: Easier maintenance
**Effort**: Low
**Files**: Multiple files
**Completed**: 2025-11-04 (partial - done for migrated files)

**Previous Issue**:
- Hardcoded paths: `"config/"`, `"downloads/"`, `"library_data/"`, `"config/auth/"`
- Path changes require search/replace

**Action Items**:
- [x] Create `utils/constants.py`
- [x] Define path constants with helpers:
```python
CONFIG_DIR = Path("config")
DOWNLOADS_DIR = Path("downloads")
LIBRARY_DATA_DIR = Path("library_data")
AUTH_DIR = CONFIG_DIR / "auth"
get_auth_file_path(account_name)
get_account_auth_dir(account_name)
```
- [x] Replace hardcoded paths in migrated files (routes/auth.py, routes/download.py, routes/invite.py, downloader.py)
- [ ] Replace hardcoded paths in remaining files (routes/importer.py, importer.py, etc.)

**Results**:
- Created utils/constants.py with path constants and helpers
- Replaced hardcoded paths in 5 files during Configuration Management migration
- Remaining files to be updated in future iterations

---

### 15. Extract Region Configuration
**Impact**: Minor improvement
**Effort**: Low
**Files**: `auth.py:37-49`, `routes/invite.py:41-53`

**Current Issue**:
- Region list duplicated
- Not easily extensible

**Action Items**:
- [ ] Move region mapping to `config/regions.json` or constants
- [ ] Create utility function `get_available_regions()`
- [ ] Replace hardcoded lists

---

### 16. Create Authenticator Utility
**Impact**: Minor code reduction
**Effort**: Low
**Files**: `downloader.py`, `importer.py`, `auth.py`

**Current Issue**:
- `_load_authenticator()` method duplicated 3 times
- Same auth file path construction logic

**Action Items**:
- [ ] Create `load_authenticator(account_name, region)` in `utils/account_manager.py`
- [ ] Create `get_auth_file_path(account_name)` helper
- [ ] Replace duplicated code

---

### 17. Extract Magic Numbers to Constants
**Impact**: Better documentation
**Effort**: Low
**Files**: `downloader.py`, `importer.py`

**Current Issue**:
- Hardcoded values without explanation:
  - `Semaphore(3)` - max concurrent downloads
  - `timeout=300` - 5 minute timeout
  - `older_than_hours=24` - cleanup threshold

**Action Items**:
- [ ] Create named constants with documentation
- [ ] Move to configuration file if values should be configurable
```python
# Configuration
MAX_CONCURRENT_DOWNLOADS = 3  # Limit concurrent downloads to prevent API throttling
DOWNLOAD_TIMEOUT_SECONDS = 300  # 5 minutes
CLEANUP_THRESHOLD_HOURS = 24  # Remove scan results older than 24 hours
```

---

### 18. Standardize API URL Patterns
**Impact**: Better API design
**Effort**: Medium
**Files**: All route files

**Current Issue**:
- Inconsistent patterns:
  - `/api/accounts` vs `/api/library/search`
  - `/downloads` (page) vs `/api/download/books` (endpoint)

**Action Items**:
- [ ] Define URL structure standards
- [ ] Consider API versioning: `/api/v1/`
- [ ] Separate UI routes from API routes clearly
- [ ] Update all routes
- [ ] Update frontend to match

**Suggested Structure**:
```
# UI Routes (return HTML)
GET /                    # Main page
GET /downloads          # Downloads page
GET /library            # Library page
GET /invite/{token}     # Invite pages

# API Routes (return JSON)
GET  /api/accounts
POST /api/accounts
GET  /api/library
POST /api/library/sync
POST /api/downloads/start
GET  /api/downloads/status
```

---

### 19. Remove Dead Code
**Impact**: Minor cleanup
**Effort**: Low
**Files**: `app.py`, `utils/account_manager.py`

**Action Items**:
- [ ] Remove `LOCAL_LIBRARY_PATH` from `app.py:24` if truly unused
- [ ] Remove old migration code in `utils/account_manager.py:63-73` after grace period
- [ ] Add version tracking for migrations
- [ ] Document removal schedule

---

### 20. Improve Error Specificity
**Impact**: Better debugging
**Effort**: Low
**Files**: Multiple routes

**Current Issue**:
- Generic `except Exception as e:` catches
- Hides specific error types

**Action Items**:
- [ ] Replace generic catches with specific exceptions
- [ ] Let unexpected exceptions bubble to Flask error handlers
- [ ] Add proper logging for caught exceptions

---

## Implementation Strategy

### Phase 1: Foundation (High Priority Items 1-4) - 100% COMPLETE ✅
**Timeline**: 2-3 weeks
**Goal**: Address security and major architecture issues
**Status**: All 4 tasks complete (2025-11-04)

1. ✅ CSRF Protection - COMPLETE
2. ✅ Configuration Management - COMPLETE
3. ✅ OAuth Consolidation - COMPLETE
4. ✅ Split AudiobookDownloader - COMPLETE

### Phase 2: Quality Improvements (Medium Priority Items 5-12) - 75% COMPLETE ✅
**Timeline**: 3-4 weeks
**Goal**: Improve maintainability and testability
**Status**: 6 of 8 tasks complete (2025-11-04)

**Completed**:
1. ✅ Task 5: Create Account Loading Utility
2. ✅ Task 7: Standardize Error Handling
3. ✅ Task 8: Unify Library State Tracking
4. ✅ Task 10: Create Library Configuration Utility
5. ✅ Task 11: Add Input Validation Layer
6. ✅ Task 12: Create Base Queue Manager

**Remaining**:
- [ ] Task 6: Extract Business Logic to Service Layer (High effort)
- [ ] Task 9: Implement Proper Async Strategy (High effort)

### Phase 3: Polish (Low Priority Items 13-20)
**Timeline**: 1-2 weeks
**Goal**: Clean up remaining issues

These can be done incrementally or as time permits.

---

## Success Metrics

- **Code Duplication**: Reduce duplicated code blocks by 70%
- **Test Coverage**: Achieve >80% coverage on service layer
- **Maintainability**: Reduce average function length by 40%
- **Complexity**: No functions over 50 lines (except legitimate cases)
- **Response Time**: No regression in API response times
- **Security**: Zero CSRF vulnerabilities

---

## Notes

- Always create feature branch for refactoring work
- Run full test suite after each major change
- Update documentation alongside code changes
- Consider backward compatibility for configuration changes
- Plan database migrations if moving away from JSON files

---

## References

- [Flask Best Practices](https://flask.palletsprojects.com/en/latest/patterns/)
- [Python Code Quality Tools](https://realpython.com/python-code-quality/)
- [Refactoring Guru](https://refactoring.guru/refactoring)
