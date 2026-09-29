"""Invite-to-library journey with Audible's external OAuth boundary simulated."""
import re
import time


def test_invited_member_sees_own_library(tmp_path, monkeypatch):
    import utils.constants as constants
    import utils.db as db
    import utils.scheduler as scheduler
    import routes.invite as invite_routes
    import routes.auth as auth_routes
    from utils.config_manager import get_config_manager

    previous_path = db._db_path
    previous_conn = getattr(db._local, 'conn', None)
    db._local.conn = None
    monkeypatch.setattr(constants, 'DB_FILE', tmp_path / 'household.db')
    monkeypatch.setattr(scheduler, 'init_scheduler', lambda app: None)
    monkeypatch.setattr(invite_routes.settings_manager, 'validate_invitation_token', lambda token: token == 'invited')
    monkeypatch.setenv('SECRET_KEY', 'test-only-secret')
    monkeypatch.setenv('ADMIN_PASSWORD', 'admin-password-123')
    try:
        from app import create_app
        app = create_app()
        app.config.update(TESTING=True, SESSION_COOKIE_SECURE=False)
        client = app.test_client()
        invitation = client.get('/invite/invited')
        assert invitation.status_code == 200
        csrf = re.search(r'name="csrf-token" content="([^"]+)"', invitation.get_data(as_text=True)).group(1)
        registration = client.post('/invite/invited/add-account', json={
            'account_name': 'charlie', 'region': 'us', 'username': 'charlie',
            'password': 'charlie-password-123',
        }, headers={'X-CSRFToken': csrf})
        assert registration.status_code == 200
        assert registration.json['auth_url'].endswith('/charlie')

        # Audible OAuth is external. Model its successful result and a returned purchase.
        manager = get_config_manager()
        manager.update_account('charlie', {'authenticated': True})
        token_file = tmp_path / 'auth.json'
        token_file.write_text('{}')
        monkeypatch.setattr(auth_routes, 'get_auth_file_path', lambda name: token_file)
        monkeypatch.setattr(auth_routes, 'get_cached_library', lambda name: [
            {'asin': 'NEWBOOK', 'title': 'First purchase', 'authors': 'A. Writer'}
        ])

        page = client.get('/')
        assert page.status_code == 200
        assert 'Your books, at home.' in page.get_data(as_text=True)
        assert 'charlie' in page.get_data(as_text=True)
        assert 'id="autoToggle" type="button" class="switch" role="switch" aria-checked="true"' in page.get_data(as_text=True)
        response = client.get('/api/library/all')
        assert response.status_code == 200
        assert response.json['library'][0]['title'] == 'First purchase'
        assert response.json['library'][0]['account_names'] == ['charlie']

        # A member can pause and resume downloads for only their account.
        import routes.scheduler as scheduler_routes
        monkeypatch.setattr(scheduler_routes, 'update_job', lambda *args: None)
        monkeypatch.setattr(scheduler_routes, 'get_next_run_time', lambda *args: None)
        db.get_db().execute(
            "INSERT INTO libraries (name,path,created_at) VALUES ('home',?,0)",
            (str(tmp_path / 'books'),),
        )
        db.get_db().commit()
        csrf = re.search(r'name="csrf-token" content="([^"]+)"', page.get_data(as_text=True)).group(1)
        response = client.put('/api/accounts/charlie/auto-download', json={
            'enabled': False, 'interval_hours': 6, 'rules': []
        }, headers={'X-CSRFToken': csrf})
        assert response.status_code == 200
        response = client.put('/api/accounts/charlie/auto-download', json={
            'enabled': True, 'interval_hours': 1, 'rules': []
        }, headers={'X-CSRFToken': csrf})
        assert response.status_code == 200
        assert manager.get_account('charlie')['auto_download']['enabled'] is True
        assert 'every 1 hour' in client.get('/').get_data(as_text=True)
    finally:
        conn = getattr(db._local, 'conn', None)
        if conn is not None:
            conn.close()
        db._local.conn = previous_conn
        db._db_path = previous_path
