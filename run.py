#!/usr/bin/env python3
"""
Simple run script for the Audible Book Downloader Flask application
"""

import os
from app import create_app

if __name__ == '__main__':
    app = create_app()
    port = int(os.environ.get('PORT', 5505))
    print("🚀 Starting Audible Book Downloader...")
    print(f"📖 Open your browser and go to: http://localhost:{port}")
    print("⚠️  Press Ctrl+C to stop the server")
    app.run(debug=True, host='0.0.0.0', port=port) 