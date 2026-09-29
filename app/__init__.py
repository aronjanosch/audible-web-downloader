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

    # Initialise database before importing blueprints — some blueprints
    # instantiate queue manager singletons at module level which call get_db().
    from utils.db import init_db, migrate
    from utils.constants import DB_FILE
    init_db(DB_FILE)
    migrate()

    from utils.security import bootstrap_admin, install_security
    bootstrap_admin()
    app.extensions['login_attempts'] = install_security(app, csrf)

    @app.context_processor
    def household_identity():
        from utils.security import current_user
        return {'household_user': current_user()}

    @app.cli.command('create-admin')
    def create_admin_command():
        """Create the first household admin, preserving existing Audible data."""
        import click
        from utils.db import get_db
        from utils.security import create_user
        if get_db().execute("SELECT 1 FROM users WHERE role='admin' LIMIT 1").fetchone():
            raise click.ClickException('An admin already exists')
        username = click.prompt('Admin username', default='admin')
        password = click.prompt('Admin password', hide_input=True, confirmation_prompt=True)
        try:
            create_user(username, password, 'admin')
        except ValueError as exc:
            raise click.ClickException(str(exc)) from exc
        click.echo('Admin created')

    # Register blueprints
    from routes.main import main_bp
    from routes.auth import auth_bp
    from routes.download import download_bp
    from routes.library import library_bp
    from routes.invite import invite_bp
    from routes.importer import importer_bp
    from routes.scheduler import scheduler_bp
    from routes.books import books_bp
    from routes.security import security_bp

    app.register_blueprint(main_bp)
    app.register_blueprint(auth_bp)
    app.register_blueprint(download_bp)
    app.register_blueprint(library_bp)
    app.register_blueprint(invite_bp)
    app.register_blueprint(importer_bp)
    app.register_blueprint(scheduler_bp)
    app.register_blueprint(books_bp)
    app.register_blueprint(security_bp)

    from utils.scheduler import init_scheduler
    init_scheduler(app)

    # CSRF protection is now enabled for all routes by default
    # Audible posts the OAuth result outside our page session, so only those
    # callback endpoints are exempt. The invite account form originates here
    # and must carry the normal CSRF token despite also having an invite token.
    from routes.invite import login_callback, account_login_callback
    csrf.exempt(login_callback)
    csrf.exempt(account_login_callback)
    
    # Register custom error handlers
    from utils.errors import register_error_handlers
    register_error_handlers(app)
    
    # Custom error page handlers for HTML requests
    @app.errorhandler(404)
    def not_found_error(error):
        # Check if request expects JSON
        from flask import request
        if request.path.startswith('/api/'):
            # Already handled by register_error_handlers
            return None
        return render_template('errors/404.html'), 404
    
    @app.errorhandler(500)
    def internal_error(error):
        # Check if request expects JSON
        from flask import request
        if request.path.startswith('/api/'):
            # Already handled by register_error_handlers
            return None
        return render_template('errors/500.html'), 500
    
    return app
