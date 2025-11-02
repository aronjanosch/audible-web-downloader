#!/usr/bin/env python3
"""
Simple run script for the Audible Book Downloader Flask application
"""

from app import create_app

if __name__ == '__main__':
    app = create_app()
    print("🚀 Starting Audible Book Downloader...")
    print("📖 Open your browser and go to: http://localhost:5505")
    print("⚠️  Press Ctrl+C to stop the server")
    app.run(debug=True, host='0.0.0.0', port=5505) 