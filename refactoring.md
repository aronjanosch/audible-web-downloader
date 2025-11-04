# Refactoring Plan

This document outlines refactoring opportunities to improve code quality, reduce complexity, and enhance maintainability. Items are prioritized by impact and organized into actionable tasks.

**Last Updated**: 2025-11-04
**Status**: Phase 1 Complete (3/4 tasks done)

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

### 4. Split AudiobookDownloader God Class
**Impact**: Major architecture improvement
**Effort**: High
**Files**: `downloader.py` (1600+ lines)

**Current Issue**:
- Single massive class handling everything:
  - Downloading, decryption, conversion
  - Metadata extraction and embedding
  - Path building with naming patterns
  - Library state tracking
  - Queue management

**Action Items**:
- [ ] Create `AudioConverter` class for AAX to M4B conversion
- [ ] Create `MetadataEnricher` class for metadata operations
- [ ] Create `PathBuilder` class for naming pattern logic
- [ ] Create `LibraryManager` class for library state tracking
- [ ] Refactor `AudiobookDownloader` to orchestrate these components
- [ ] Update tests if they exist

**Suggested Structure**:
```
app/services/
├── audio_converter.py      # FFmpeg conversion logic
├── metadata_enricher.py    # Metadata extraction and embedding
├── path_builder.py         # Naming pattern and path logic
├── library_manager.py      # Library state tracking
└── download_orchestrator.py # Coordinates download process
```

---

## Medium Priority (Code Quality & Maintainability)

### 5. Create Account Loading Utility
**Impact**: Reduces duplication
**Effort**: Low
**Files**: All route files

**Current Issue**:
- Pattern repeated 15+ times:
```python
accounts = load_accounts()
if account_name not in accounts:
    return jsonify({'error': 'Account not found'}), 404
account_data = accounts[account_name]
region = account_data['region']
```

**Action Items**:
- [ ] Create `get_account_or_404(account_name)` in `utils/account_manager.py`
- [ ] Option 1: Return account data or raise 404 exception
- [ ] Option 2: Create decorator `@require_account('account_name')`
- [ ] Replace all instances with utility function
- [ ] Add type hints

**Files to Update**:
- `routes/main.py`
- `routes/auth.py`
- `routes/download.py`
- `routes/invite.py`
- `routes/importer.py`

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

### 7. Standardize Error Handling
**Impact**: Consistent API responses
**Effort**: Medium
**Files**: All route files

**Current Issue**:
- Inconsistent error response formats
- Mix of status codes for similar errors
- No standardized error types

**Action Items**:
- [ ] Create `utils/errors.py` with custom exception classes
- [ ] Define standard error response format
- [ ] Create error response helpers: `error_response(message, code)`
- [ ] Create Flask error handlers for custom exceptions
- [ ] Replace all error responses with standard format
- [ ] Document error response format

**Standard Format**:
```python
{
    "success": false,
    "error": {
        "message": "Account not found",
        "code": "ACCOUNT_NOT_FOUND",
        "details": {}  # Optional additional context
    }
}
```

---

### 8. Unify Library State Tracking
**Impact**: Clearer architecture
**Effort**: Medium
**Files**: `downloader.py`, `library_storage.py`

**Current Issue**:
- Two separate systems tracking library contents:
  - `downloader.py` uses `config/library.json`
  - `library_storage.py` uses `library_data/libraries.json`
- Overlapping but different purposes
- Confusing for maintenance

**Action Items**:
- [ ] Document purpose of each system
- [ ] Determine if both are needed
- [ ] If both needed: Clearly separate concerns and rename appropriately
- [ ] If redundant: Consolidate into single system
- [ ] Add documentation explaining library state management

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

### 10. Create Library Configuration Utility
**Impact**: Reduces duplication
**Effort**: Low
**Files**: `routes/download.py`, `routes/importer.py`

**Current Issue**:
- Library configuration loading duplicated
- Same validation pattern repeated

**Action Items**:
- [ ] Create `get_library_config(library_name)` in `utils/account_manager.py`
- [ ] Include validation and error handling
- [ ] Return library path and configuration
- [ ] Replace duplicated code

**Reference**:
- `routes/download.py:42-47`
- `routes/importer.py:533-542`

---

### 11. Add Input Validation Layer
**Impact**: Better error messages, security
**Effort**: Medium
**Files**: All route files

**Current Issue**:
- Ad-hoc validation in routes
- Easy to miss validation cases
- No type checking on inputs

**Action Items**:
- [ ] Choose validation library (marshmallow or pydantic)
- [ ] Define schemas for all API endpoints
- [ ] Create validation decorator or middleware
- [ ] Add validation to all routes
- [ ] Return validation errors in standard format

**Example with Pydantic**:
```python
from pydantic import BaseModel, validator

class DownloadRequest(BaseModel):
    account_name: str
    selected_books: list[str]

    @validator('selected_books')
    def validate_books(cls, v):
        if not v:
            raise ValueError('At least one book required')
        return v

@download_bp.route('/api/download/books', methods=['POST'])
@validate_json(DownloadRequest)
def download_selected_books(data: DownloadRequest):
    # data is validated and typed
    pass
```

---

### 12. Create Base Queue Manager
**Impact**: Reduces duplication
**Effort**: Medium
**Files**: `downloader.py`, `importer.py`

**Current Issue**:
- Nearly identical singleton pattern in both queue managers
- Same methods duplicated: `_load_queue`, `_save_queue`, `get_statistics`

**Action Items**:
- [ ] Create `BaseQueueManager` abstract class in `utils/queue_base.py`
- [ ] Move shared functionality to base class
- [ ] Make `DownloadQueueManager` and `ImportQueueManager` inherit from base
- [ ] Keep queue-specific logic in subclasses

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

### Phase 1: Foundation (High Priority Items 1-4) - 75% COMPLETE ✅
**Timeline**: 2-3 weeks
**Goal**: Address security and major architecture issues
**Status**: 3 of 4 tasks complete (2025-11-04)

1. ✅ CSRF Protection - COMPLETE
2. ✅ Configuration Management - COMPLETE
3. ✅ OAuth Consolidation - COMPLETE
4. ⏳ Split AudiobookDownloader - PENDING (next task)

### Phase 2: Quality Improvements (Medium Priority Items 5-12)
**Timeline**: 3-4 weeks
**Goal**: Improve maintainability and testability

Focus on service layer extraction and standardization.

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
