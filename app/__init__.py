"""
Application package for Audible Book Downloader
"""
from flask import Flask, render_template
from flask_wtf.csrf import CSRFProtect
import logging
import os
from pathlib import Path


def create_app():
    """Application factory pattern for Flask"""
    app = Flask(__name__, 
                template_folder='../templates',
                static_folder='../static')

    from utils.logging_config import configure_logging
    configure_logging()

    # Configuration
    secret_key = os.environ.get('SECRET_KEY')
    weak_keys = {'', 'change-me', 'changeme', 'dev', 'secret'}
    if not secret_key or secret_key.strip().lower() in weak_keys:
        if os.environ.get('FLASK_ENV') == 'development' or os.environ.get('AUDIBLE_ALLOW_EPHEMERAL_KEY') == '1':
            import secrets
            secret_key = secrets.token_hex(32)
            logging.getLogger(__name__).warning(
                "No usable SECRET_KEY set; using a random key. Sessions reset on restart.")
        else:
            raise RuntimeError(
                "SECRET_KEY is not set (or is a placeholder). Generate one with "
                "`python -c \"import secrets; print(secrets.token_urlsafe(48))\"` "
                "and export it before starting. For local development set FLASK_ENV=development.")
    app.config['SECRET_KEY'] = secret_key
    app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024

    # Behind a reverse proxy, trust X-Forwarded-* only when told how many hops to trust.
    proxies = os.environ.get('TRUSTED_PROXIES', '').strip()
    if proxies.isdigit() and int(proxies) > 0:
        from werkzeug.middleware.proxy_fix import ProxyFix
        hops = int(proxies)
        app.wsgi_app = ProxyFix(app.wsgi_app, x_for=hops, x_proto=hops, x_host=hops)
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

    from utils.web_perf import install_web_perf
    install_web_perf(app)

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
    from routes.household import household_bp
    from routes.health import health_bp

    app.register_blueprint(main_bp)
    app.register_blueprint(auth_bp)
    app.register_blueprint(download_bp)
    app.register_blueprint(library_bp)
    app.register_blueprint(invite_bp)
    app.register_blueprint(importer_bp)
    app.register_blueprint(scheduler_bp)
    app.register_blueprint(books_bp)
    app.register_blueprint(security_bp)
    app.register_blueprint(household_bp)
    app.register_blueprint(health_bp)

    from utils.scheduler import init_scheduler
    init_scheduler(app)

    import atexit

    def _stop_scheduler():
        scheduler = getattr(app, 'scheduler', None)
        if scheduler is not None and getattr(scheduler, 'running', False):
            scheduler.shutdown(wait=False)

    atexit.register(_stop_scheduler)

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
