from flask import Flask, render_template, request, jsonify, session, redirect, url_for, flash
from flask_wtf.csrf import CSRFProtect
import os
import json
from pathlib import Path
import asyncio
from auth import authenticate_account, fetch_library, AudibleAuth
from downloader import download_books

def create_app():
    """Application factory pattern for Flask"""
    app = Flask(__name__)
    
    # Configuration
    app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'dev-secret-key-change-in-production')
    app.config['ACCOUNTS_FILE'] = "config/accounts.json"
    app.config['DOWNLOADS_DIR'] = "downloads"
    app.config['LOCAL_LIBRARY_PATH'] = os.environ.get('LOCAL_LIBRARY_PATH', '')
    
    # Initialize extensions
    csrf = CSRFProtect(app)
    
    # Ensure required directories exist
    Path(app.config['DOWNLOADS_DIR']).mkdir(exist_ok=True)
    Path('config').mkdir(exist_ok=True)
    
    # Register blueprints
    from routes.main import main_bp
    from routes.auth import auth_bp
    from routes.download import download_bp
    from routes.library import library_bp
    from routes.invite import invite_bp

    app.register_blueprint(main_bp)
    app.register_blueprint(auth_bp)
    app.register_blueprint(download_bp)
    app.register_blueprint(library_bp)
    app.register_blueprint(invite_bp)

    # Exempt API endpoints from CSRF protection (after blueprints are registered)
    csrf.exempt(app.blueprints.get('main'))
    csrf.exempt(app.blueprints.get('auth'))
    csrf.exempt(app.blueprints.get('download'))
    csrf.exempt(app.blueprints.get('library'))
    csrf.exempt(app.blueprints.get('invite'))
    
    # Error handlers
    @app.errorhandler(404)
    def not_found_error(error):
        return render_template('errors/404.html'), 404
    
    @app.errorhandler(500)
    def internal_error(error):
        return render_template('errors/500.html'), 500
    
    return app

if __name__ == '__main__':
    app = create_app()
    app.run(debug=True, host='0.0.0.0', port=5505) 