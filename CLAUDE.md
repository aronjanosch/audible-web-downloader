# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

This is a Flask-based web application for downloading and managing Audible audiobooks. The application provides secure authentication with Audible accounts, library browsing, and downloads books with automatic conversion from AAX to M4B format while preserving metadata.

## Build Commands

```bash
# Install dependencies with uv (recommended)
uv sync

# Install with pip (alternative)
pip install -r requirements.txt

# Run the application
uv run python run.py
# or
python run.py

# Run in development mode with debugging
FLASK_ENV=development python run.py
```

The application runs on `http://localhost:5000` by default.

## Development Guidelines

- Always use uv for dependencies and to run the python code
- Follow Flask application factory pattern with blueprints
- Use early returns for error conditions to avoid deeply nested if statements  
- Implement proper error handling with user-friendly messages
- Use descriptive variable names with auxiliary verbs (e.g., is_authenticated, has_downloads)
- Prefer functional programming; avoid unnecessary classes except for Flask views

## Architecture

The application follows a **modular Flask architecture** using blueprints for route organization:

### Core Components

- **app.py** - Flask application factory with CSRF protection and blueprint registration
- **run.py** - Application entry point
- **auth.py** - Audible authentication handler using official Audible library with OAuth flow
- **downloader.py** - Complex audiobook download orchestration with state management, concurrent downloads, and FFmpeg conversion

### Flask Blueprints (routes/)

- **main.py** - Account management, library display, and core API endpoints
- **auth.py** - Authentication routes for Audible OAuth
- **download.py** - Download management and batch processing routes
- **invite.py** - Family sharing invitation routes (not behind authentication middleware)
- **library.py** - Library management and synchronization routes

### Frontend Architecture

- **templates/base.html** - Bootstrap 5 base template with responsive design
- **static/** - CSS and JavaScript assets
- Modern vanilla JavaScript frontend that communicates with backend via REST API

### Data Management

- **config/accounts.json** - Persisted account configurations, authentication status, and optional pending_invitation_token for single-account invites
- **config/libraries.json** - Library paths and configurations
- **config/settings.json** - Application settings including naming patterns and general invitation token
- **config/auth/{account_name}/auth.json** - Audible authentication tokens per account
- **downloads/** - Temporary download directory for AAX files, vouchers, and working files
- **downloads/download_states.json** - Download state tracking for resume/retry functionality

## Key Dependencies

- **audible >= 0.10.0** - Official Audible API client for authentication and library access
- **flask >= 3.1.2** - Web framework with WTF CSRF protection
- **mutagen >= 1.47.0** - Audio file metadata manipulation for M4B tagging
- **pycryptodome** - AES decryption for Audible license vouchers
- **httpx** - Async HTTP client for concurrent downloads
- **FFmpeg** (external) - Required for AAX to M4B conversion with key/IV decryption

## Authentication Flow

The application implements Audible's external browser OAuth flow:
1. Creates region-specific Audible client with locale configuration
2. Initiates external browser authentication via `audible.Authenticator.from_login_external()`
3. Saves encrypted authentication tokens to `.audible_{account_name}/auth.json`
4. Validates authentication by testing library API calls

## Family Sharing Feature

The application includes a **family sharing system** that allows the application owner to invite family members to add their Audible accounts without needing access to the main application.

### Architecture

- **Token-based invitation system** - No user accounts required for family members
- **Permanent reusable invitation links** - One link for all family members
- **Cryptographically secure tokens** - 32-byte URL-safe base64 tokens (~256 bits entropy)
- **Separate OAuth flow** - Family members complete Audible authentication independently
- **Owner control** - All added accounts are owned by the application owner

### Invitation Flows

**Two invitation modes are available:**

#### 1. General Invitation Link (Self-Service)
Family members create their own account name and authenticate:

1. **Owner generates invitation link** - Link displayed in "Family Sharing" modal (sidebar button)
2. **Owner shares link** - Via secure messaging within family group
3. **Family member visits link** - `/invite/{token}` route (not behind auth middleware)
4. **Account creation** - Family member enters account name and selects region
5. **Audible OAuth** - Reuses existing external browser OAuth flow
6. **Account added** - New account appears in owner's account list with full control

#### 2. Single-Account Invitation (Admin-Controlled)
Owner creates account, generates unique link for one user to authenticate:

1. **Owner creates account** - Adds account via "Add New Account" form in sidebar
2. **Owner generates account invite** - Clicks "Generate Invite Link" button for unauthenticated account
3. **Owner shares account-specific link** - Via secure messaging to specific family member
4. **Family member visits link** - `/invite/account/{token}` route (not behind auth middleware)
5. **Audible OAuth** - Authenticates pre-created account (no account creation step)
6. **Account authenticated** - Account status updates to authenticated, invitation link auto-revoked

### Implementation Details

**Token Management** (`settings.py`):
- Token stored in `config/settings.json` as `invitation_token`
- Generated on first run using `secrets.token_urlsafe(32)`
- Validated using constant-time comparison (`secrets.compare_digest`)
- Can be regenerated by owner (invalidates old link)

**General Invitation Routes** (`routes/invite.py`):
- `/invite/{token}` - Landing page with account creation form
- `/invite/{token}/add-account` - POST endpoint to create account
- `/invite/{token}/auth/login/{account_name}` - Start OAuth flow
- `/invite/{token}/auth/login-page/{session_id}` - OAuth page display
- `/invite/{token}/auth/callback/{session_id}` - OAuth callback handler
- `/invite/{token}/auth/status/{session_id}` - Status polling endpoint
- `/invite/{token}/success/{account_name}` - Success page

**Single-Account Invitation Routes** (`routes/invite.py`):
- `/invite/account/{token}` - Landing page for specific account
- `/invite/account/{token}/auth/login` - Start OAuth flow for account
- `/invite/account/{token}/auth/login-page/{session_id}` - OAuth page display
- `/invite/account/{token}/auth/callback/{session_id}` - OAuth callback handler
- `/invite/account/{token}/auth/status/{session_id}` - Status polling endpoint
- `/invite/account/{token}/success/{account_name}` - Success page

**API Endpoints** (`routes/main.py`):
- `GET /api/settings/invitation-link` - Retrieve general invitation URL
- `POST /api/settings/regenerate-invitation-token` - Generate new general token
- `POST /api/settings/set-invitation-token` - Set custom general invitation token
- `POST /api/accounts/{account_name}/generate-invite-link` - Generate account-specific invite link
- `POST /api/accounts/{account_name}/revoke-invite-link` - Revoke account-specific invite link

**Templates** (`templates/invite/`):
- `landing.html` - General invitation: Account creation form with region selection
- `login.html` - General invitation: Audible OAuth flow page
- `success.html` - General invitation: Confirmation page after account addition
- `account_landing.html` - Single-account: Landing page showing account details
- `account_login.html` - Single-account: Audible OAuth flow page
- `account_success.html` - Single-account: Confirmation page after authentication
- `account_already_authenticated.html` - Single-account: Error page for already-authenticated accounts
- `invalid_token.html` - Error page for invalid/expired tokens

### Security Considerations

**Authentik Integration (Recommended):**
- **All routes protected**: Main admin panel AND invitation routes behind Authentik authentication
- **Role-based access control**: Admin users get full access, family users restricted to `/invite/*` paths only
- **Centralized access management**: Create users in Authentik, assign to groups
- **Audit trail**: All access attempts logged in Authentik
- **See `AUTHENTIK_SETUP.md`** for complete setup guide

**Token Security:**
- 256-bit entropy makes brute-force attacks computationally infeasible
- Constant-time comparison prevents timing attacks
- Tokens used to identify invitation links, not for authentication

**Account Ownership:**
- All accounts added via invitation belong to the application owner
- Family members authenticate to Authentik (not Audible) to access invitation pages
- Owner has full control (select, authenticate, download, remove)

**User Groups:**
- `audible-admins` - Full access to admin panel and invitation pages
- `audible-family` - Limited access to `/invite/*` paths only

### Traefik Integration with Authentik

**RECOMMENDED CONFIGURATION:** Use Authentik's authorization policies for path-based access control.

**Simple Docker Compose labels (single router):**
```yaml
# Single router with Authentik middleware for all routes
- "traefik.http.routers.audible.rule=Host(`audible.yourdomain.com`)"
- "traefik.http.routers.audible.middlewares=authentik@docker"
- "traefik.http.routers.audible.entrypoints=websecure"
- "traefik.http.routers.audible.tls.certresolver=letsencrypt"
```

**Authentik Policy** (configured in Authentik, not Traefik):
- Admins: Access all paths
- Family: Access only `/invite/*` paths
- Authorization enforced by Authentik proxy provider

See `AUTHENTIK_SETUP.md` for step-by-step Authentik configuration guide.

### Usage Notes

**Setup (One-time per family member):**
1. Create Authentik user for family member
2. Add user to `audible-family` group
3. Send family member their Authentik login credentials

**General Invitation Link (Self-Service):**
1. Click "Manage Invitation Link" button in sidebar "Family Sharing" section
2. Generate or view invitation link (auto-generated on first use)
3. Optional: Set custom token for memorable URL
4. Copy and share link with family members via secure messaging
5. Family member clicks link → redirected to Authentik login → logs in with their credentials
6. Family member creates account name, completes Audible OAuth
7. New accounts appear in your account dropdown

**Single-Account Invitation (Admin-Controlled):**
1. Add new account via "Add New Account" form (specify name and region)
2. Select the unauthenticated account from dropdown
3. Click "Generate Invite Link" button (appears for unauthenticated accounts)
4. Copy account-specific link from modal
5. Share link with specific family member
6. Family member clicks link → redirected to Authentik login → logs in with their credentials
7. Family member authenticates the pre-named account via Audible OAuth
8. Account updates to authenticated status, invitation link auto-revoked

**Account Management:**
- All accounts (self-created, general invite, single-account invite) appear in dropdown
- Switch between accounts to download from different libraries
- Remove accounts as needed
- Revoke family member access by removing from Authentik group or deleting user

## Download Architecture

The **AudiobookDownloader** class implements a sophisticated download system:

### State Management
- **Persistent state tracking** in JSON with atomic updates
- **Resume capability** for interrupted downloads
- **Retry logic** with exponential backoff

### Concurrency Control
- **Semaphore-based download limiting** (default: 3 concurrent downloads)
- **Single-threaded decryption** via decrypt semaphore to prevent resource conflicts

### Processing Pipeline
1. **License Request** - Requests download license from Audible API with quality settings
2. **Voucher Decryption** - AES decryption of license voucher using device-specific keys
3. **File Download** - Streaming download to temporary directory (`downloads/{title}/`)
4. **FFmpeg Conversion** - AAX to M4B conversion in temp directory
5. **Metadata Enhancement** - Fetches additional book details and embeds comprehensive metadata
6. **Library Import** - Moves completed M4B to library following naming pattern structure
7. **Cleanup** - Removes temporary files (AAX, vouchers, metadata) from downloads directory

## API Endpoints

- `GET /` - Main application interface
- `GET /api/accounts` - List saved accounts
- `POST /api/accounts` - Add new account
- `POST /api/accounts/<name>/select` - Select active account
- `POST /api/auth/authenticate` - Start Audible authentication
- `POST /api/library/fetch` - Fetch user's library
- `POST /api/download/books` - Download selected books
- `GET /api/library/search` - Search library with filtering

## File Structure Conventions

- **Account data**: `config/auth/{account_name}/` directories for per-account authentication
- **Temporary downloads**: `downloads/{sanitized_title}/` - Working directory for AAX files, vouchers, and metadata
- **Library location**: Configured library path with folder-based structure (e.g., `library/Author/Series/Vol 1 - Year - Title {Narrator}/Title.m4b`)
  - Each book gets its own folder named according to the naming pattern
  - M4B file(s) are placed inside the folder for Audiobookshelf compatibility
- **State persistence**: `downloads/download_states.json` for tracking download progress

### Download vs Library Separation

The application maintains a clean separation between temporary working files and the organized library:

- **downloads/** - Temporary files during processing (AAX, vouchers, conversion artifacts)
- **library/** - Final M4B files only, organized in folders by naming pattern
  - Each book has its own folder created from the naming pattern
  - M4B files are placed inside these folders for Audiobookshelf compatibility
- After successful conversion, M4B is moved from downloads to library
- Cleanup removes all temporary files, keeping only the final M4B in library

## External Dependencies

- **FFmpeg** - Required system dependency for AAX to M4B conversion
  - Ubuntu/Debian: `sudo apt install ffmpeg`
  - macOS: `brew install ffmpeg`  
  - Windows: Download from FFmpeg official website
- **Python 3.13+** - Runtime requirement as specified in pyproject.toml

## Development Commands

```bash
# Development mode with debugging
FLASK_ENV=development uv run python run.py

# Check code style and run tests (if available)
uv run pytest  # Run tests if test files exist
```