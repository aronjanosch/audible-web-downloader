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

### Frontend Architecture

- **templates/base.html** - Bootstrap 5 base template with responsive design
- **static/** - CSS and JavaScript assets
- Modern vanilla JavaScript frontend that communicates with backend via REST API

### Data Management

- **accounts.json** - Persisted account configurations and authentication status
- **downloads/download_states.json** - Download state tracking for resume/retry functionality
- **.audible_{account_name}/auth.json** - Encrypted Audible authentication tokens per account

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
3. **File Download** - Streaming download with chunk processing
4. **FFmpeg Conversion** - AAX to M4B with key/IV from decrypted voucher
5. **Metadata Enhancement** - Fetches additional book details and embeds comprehensive metadata

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

- **Account data**: `.audible_{account_name}/` directories for per-account authentication
- **Downloads**: `downloads/{sanitized_book_title}/` with both source (.aaxc) and converted (.m4b) files
- **Temporary files**: Voucher files (.json) and metadata files created during processing
- **State persistence**: `downloads/download_states.json` for tracking download progress

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