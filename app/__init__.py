"""
Application package for Audible Book Downloader
"""
from flask import Flask, render_template
from flask_wtf.csrf import CSRFProtect
import os
from pathlib import Path


def create_app():
    """Application factory pattern for Flask"""
    app = Flask(__name__, 
                template_folder='../templates',
                static_folder='../static')

    # Configuration
    secret_key = os.environ.get('SECRET_KEY')
    if not secret_key:
        import secrets
        secret_key = secrets.token_hex(32)
        print("⚠️  WARNING: No SECRET_KEY environment variable set. Using generated key.")
        print("⚠️  Set SECRET_KEY environment variable for production use.")
    app.config['SECRET_KEY'] = secret_key
    app.config['ACCOUNTS_FILE'] = "config/accounts.json"
    app.config['DOWNLOADS_DIR'] = "downloads"
    app.config['LOCAL_LIBRARY_PATH'] = os.environ.get('LOCAL_LIBRARY_PATH', '')
    
    # Initialize extensions
    csrf = CSRFProtect(app)

    # Store csrf instance in app config for use in blueprints
    app.csrf = csrf
    
    # Ensure required directories exist
    Path(app.config['DOWNLOADS_DIR']).mkdir(exist_ok=True)
    Path('config').mkdir(exist_ok=True)
    
    # Register blueprints
    from routes.main import main_bp
    from routes.auth import auth_bp
    from routes.download import download_bp
    from routes.library import library_bp
    from routes.invite import invite_bp
    from routes.importer import importer_bp

    app.register_blueprint(main_bp)
    app.register_blueprint(auth_bp)
    app.register_blueprint(download_bp)
    app.register_blueprint(library_bp)
    app.register_blueprint(invite_bp)
    app.register_blueprint(importer_bp)

    # CSRF protection is now enabled for all routes by default
    # Selectively exempt public invitation endpoints
    from routes.invite import add_account, login_callback, account_login_callback
    csrf.exempt(add_account)
    csrf.exempt(login_callback)
    csrf.exempt(account_login_callback)
    
    # Error handlers
    @app.errorhandler(404)
    def not_found_error(error):
        return render_template('errors/404.html'), 404
    
    @app.errorhandler(500)
    def internal_error(error):
        return render_template('errors/500.html'), 500
    
    return app
