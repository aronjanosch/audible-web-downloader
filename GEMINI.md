# Gemini Code Assistant Context

## Project Overview

This project is a Flask-based web application for downloading and managing Audible audiobooks. It allows users to securely authenticate with their Audible accounts, browse their library, and download books in M4B format. The application features a modern, responsive UI built with Bootstrap and vanilla JavaScript.

### Key Technologies

*   **Backend:** Python, Flask
*   **Frontend:** HTML, CSS, JavaScript, Bootstrap 5
*   **Authentication:** Official Audible Python library
*   **Audio Processing:** FFmpeg
*   **Dependencies:** Flask, Flask-WTF, audible, requests, mutagen, python-dotenv, pycryptodome

### Architecture

The application follows a modular architecture using Flask Blueprints to organize routes.

*   `app.py`: Main application factory.
*   `run.py`: Application entry point.
*   `routes/`: Contains blueprints for different application areas:
    *   `main.py`: Core application routes (index, account management).
    *   `auth.py`: Audible authentication routes.
    *   `download.py`: Book download routes.
*   `templates/`: HTML templates for the user interface.
*   `static/`: Static assets (CSS, JavaScript).
*   `downloads/`: Directory for downloaded audiobooks.

### Data persistence

*   **`config/audible.db`** — SQLite file holding accounts, libraries, download queue, book/download history, scan cache, and related data (`utils/db.py`, `utils/config_manager.py`).
*   **`config/settings.json`** — UI settings and the reusable family invitation token (not stored in the DB).
*   **`config/auth/<account>/auth.json`** — Per-account Audible OAuth credentials.

## Building and Running

### Prerequisites

*   Python 3.8+
*   FFmpeg
*   `uv` (recommended) or `pip`

### Installation

1.  **Install dependencies:**
    ```bash
    # Using uv (recommended)
    uv sync

    # Or using pip
    pip install -r requirements.txt
    ```

### Running the Application

1.  **Start the Flask server:**
    ```bash
    # Using uv
    uv run python run.py

    # Or using python directly
    python run.py
    ```
2.  **Access the application:**
    Open a web browser and navigate to `http://localhost:5000`.

### Running in Development Mode

To run the application in development mode with debugging enabled:

```bash
FLASK_ENV=development python run.py
```

## Development Conventions

*   **Code Style:** The project follows standard Python conventions (PEP 8).
*   **Modularity:** Functionality is organized into Flask Blueprints for better separation of concerns.
*   **Configuration:** Application configuration is managed in `app.py` and can be customized using environment variables.
*   **Error Handling:** The application includes custom error pages for 404 and 500 errors.
*   **API:** The frontend communicates with the backend through a set of RESTful API endpoints.
