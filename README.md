# Audible Book Downloader

A simple cross-platform Flask web application for downloading and converting Audible audiobooks to M4B format.

## Features

- 🔐 **Secure Authentication**: Uses Audible's official authentication system
- 📚 **Library Management**: Browse and search your entire Audible library
- ⬇️ **Batch Downloads**: Download multiple books at once
- 🔄 **Format Conversion**: Automatically converts AAX to M4B format
- 🏷️ **Metadata Preservation**: Maintains book metadata and covers
- 🌍 **Multi-Region Support**: Supports all Audible regions worldwide
- 🎨 **Modern UI**: Clean, responsive web interface

## Prerequisites

- Python 3.8 or higher
- FFmpeg (for audio conversion)
- uv (recommended) or pip for dependency management

### Installing FFmpeg

**Ubuntu/Debian:**
```bash
sudo apt update
sudo apt install ffmpeg
```

**macOS:**
```bash
brew install ffmpeg
```

**Windows:**
Download from [FFmpeg official website](https://ffmpeg.org/download.html)

## Installation

1. **Clone the repository:**
```bash
git clone <repository-url>
cd audible-streamlit
```

2. **Install dependencies using uv (recommended):**
```bash
uv sync
```

Or using pip:
```bash
pip install -r requirements.txt
```

## Usage

### Docker Deployment (Recommended for Production)

1. **Build and start the container:**
```bash
docker-compose up -d
```

2. **Access the application:**
```
http://localhost:5505
```

3. **View logs:**
```bash
docker-compose logs -f
```

4. **Stop the container:**
```bash
docker-compose down
```

**Benefits of Docker deployment:**
- Persistent configuration via mounted `config/` volume (includes auth tokens)
- Persistent downloads via mounted `downloads/` volume
- Easy updates: rebuild and restart the container
- Isolated environment with all dependencies included
- Simple backup: backup the `config/` directory (includes `audible.db`, `settings.json`, and `auth/`) and the `downloads/` folder

### Starting the Application (Local Development)

1. **Run the Flask application:**
```bash
python run.py
```

Or using uv:
```bash
uv run python run.py
```

2. **Open your browser and navigate to:**
```
http://localhost:5000
```

### Using the Application

1. **Add an Audible Account:**
   - Enter an account name (e.g., "Main Account")
   - Select your Audible region
   - Click "Add Account"

2. **Authenticate:**
   - Select your account from the dropdown
   - Click "Authenticate"
   - Follow the authentication process in your browser
   - Complete any verification steps (2FA, CAPTCHA, etc.)

3. **Load Your Library:**
   - After authentication, click "Refresh Library"
   - Wait for your books to load

4. **Download Books:**
   - Search and browse your library
   - Select books you want to download
   - Choose download settings (cleanup AAX files)
   - Click "Download Selected"

### File Locations

- **Downloads**: `./downloads/` directory
- **Configuration**: `./config/` directory
  - `audible.db` - SQLite database (accounts, libraries, download queue, book state, scan cache, library API cache, etc.)
  - `settings.json` - Naming patterns, family-sharing invitation token, and other app settings
  - `auth/{account_name}/auth.json` - Audible authentication tokens per account
- **Legacy files** (optional): Older installs may still have `accounts.json`, `libraries.json`, or `library.json` under `config/`. They are not the live source of truth after migration; the app uses `audible.db`.

## Supported Regions

- 🇺🇸 United States (us)
- 🇬🇧 United Kingdom (uk)
- 🇩🇪 Germany (de)
- 🇫🇷 France (fr)
- 🇨🇦 Canada (ca)
- 🇮🇹 Italy (it)
- 🇦🇺 Australia (au)
- 🇮🇳 India (in)
- 🇯🇵 Japan (jp)
- 🇪🇸 Spain (es)
- 🇧🇷 Brazil (br)

## Technical Details

### Architecture

- **Backend**: Flask with blueprints for modular organization
- **Frontend**: Bootstrap 5 with vanilla JavaScript
- **Authentication**: Audible's official Python library
- **Audio Processing**: FFmpeg for AAX to M4B conversion
- **Metadata**: Mutagen for audio file metadata

### API Endpoints

- `GET /` - Main application page
- `GET /api/accounts` - Get all accounts
- `POST /api/accounts` - Add new account
- `POST /api/accounts/<name>/select` - Select account
- `POST /api/auth/authenticate` - Authenticate account
- `POST /api/auth/check` - Check authentication status
- `POST /api/library/fetch` - Fetch user library
- `POST /api/download/books` - Download selected books

## Security Notes

- This application uses your personal Audible credentials
- Authentication files are stored locally and encrypted
- No data is sent to external servers except Audible
- Please respect copyright laws and terms of service

## Troubleshooting

### Common Issues

1. **FFmpeg not found:**
   - Ensure FFmpeg is installed and in your PATH
   - Restart your terminal after installation

2. **Authentication fails:**
   - Check your internet connection
   - Verify your Audible credentials
   - Try clearing browser cookies and cache

3. **Library doesn't load:**
   - Ensure you're authenticated
   - Check your Audible region selection
   - Try refreshing the library

4. **Downloads fail:**
   - Check available disk space
   - Ensure FFmpeg is working correctly
   - Verify file permissions in downloads directory

### Debug Mode

Run with debug mode for detailed error messages:
```bash
FLASK_ENV=development python run.py
```

## Development

### Project Structure

```
audible-streamlit/
├── app.py                 # Main Flask application
├── auth.py               # Authentication module
├── downloader.py         # Download and conversion logic
├── run.py               # Application entry point
├── requirements.txt     # Python dependencies
├── routes/              # Flask blueprints
│   ├── __init__.py
│   ├── main.py         # Main routes
│   ├── auth.py         # Authentication routes
│   └── download.py     # Download routes
├── templates/           # HTML templates
│   ├── base.html       # Base template
│   ├── index.html      # Main page
│   └── errors/         # Error pages
├── static/             # Static assets
└── downloads/          # Downloaded books
```

### Contributing

1. Fork the repository
2. Create a feature branch
3. Make your changes
4. Add tests if applicable
5. Submit a pull request

## License

This project is for educational purposes. Please respect Audible's terms of service and copyright laws.

## Disclaimer

This software is provided as-is without any warranties. Use at your own risk and ensure compliance with applicable laws and terms of service.