"""Admin household overview: member health, needs-attention list and activity."""

import time

from flask import Blueprint, jsonify, render_template

from utils.config_manager import get_config_manager
from utils.db import get_db
from utils.token_health import account_health, ago

household_bp = Blueprint('household', __name__)


@household_bp.app_template_global('token_health')
def token_health(account_name):
    account = get_config_manager().get_account(account_name) or {}
    return account_health(account_name, account)


def _initials(name):
    letters = ''.join(part[0] for part in name.replace('_', ' ').replace('-', ' ').split() if part)
    return (letters or name[:2]).upper()[:2]


def build_overview():
    db = get_db()
    accounts = get_config_manager().get_accounts()
    users = {row['account_name']: row['role'] for row in
             db.execute("SELECT account_name, role FROM users WHERE account_name IS NOT NULL")}
    counts = {row['account_name']: row['n'] for row in
              db.execute("SELECT account_name, COUNT(*) AS n FROM account_books GROUP BY account_name")}
    members, attention = [], []
    for name, account in accounts.items():
        health = account_health(name, account)
        entry = {
            'name': name, 'initials': _initials(name), 'region': str(account.get('region', '')).upper(),
            'role': 'Member' if users.get(name) else 'Invited', 'books': counts.get(name, 0),
            'state': health['state'], 'label': health['label'], 'detail': health['detail'],
            'percent': health['percent'],
            'auto_download': bool(account.get('auto_download', {}).get('enabled')),
        }
        members.append(entry)
        if health['needs_attention']:
            attention.append(entry)
    attention.sort(key=lambda e: (e['state'] != 'err', e['name']))

    now = time.time()
    activity = []
    for row in db.execute(
            "SELECT title, downloaded_by_account AS who, updated_at FROM books "
            "WHERE status='downloaded' ORDER BY updated_at DESC LIMIT 8"):
        activity.append((row['updated_at'], 'ok',
                         f"{row['title']} finished" + (f" for {row['who']}" if row['who'] else '')))
    for row in db.execute(
            "SELECT e.created_at, e.account_name, e.kind, e.detail FROM account_events e "
            "ORDER BY e.created_at DESC LIMIT 8"):
        if row['kind'] == 'auth_lost':
            activity.append((row['created_at'], 'err', f"{row['account_name']}'s Audible authorization was rejected, downloads paused"))
        elif row['kind'] == 'duplicate_avoided':
            title = (row['detail'] or '').split('|', 1)[-1] or 'a title'
            activity.append((row['created_at'], 'warn', f"Skipped {title} for {row['account_name']}, already in the household"))
        elif row['kind'] == 'auth_restored':
            activity.append((row['created_at'], 'ok', f"{row['account_name']} reconnected Audible"))
    for row in db.execute(
            # Cutoff per account computed once (a correlated MIN() per row was O(n^2) for big libraries).
            "WITH cutoff AS (SELECT account_name, MIN(first_seen_at) + 3600 AS after "
            "FROM account_books GROUP BY account_name) "
            "SELECT ab.account_name, b.title, ab.first_seen_at FROM account_books ab "
            "JOIN cutoff c ON c.account_name = ab.account_name AND ab.first_seen_at > c.after "
            "JOIN books b ON b.asin = ab.asin "
            "ORDER BY ab.first_seen_at DESC LIMIT 6"):
        activity.append((row['first_seen_at'], 'info', f"{row['account_name']} bought {row['title']}"))
    for name, account in accounts.items():
        auto = account.get('auto_download', {})
        if auto.get('last_run'):
            try:
                from datetime import datetime
                stamp = datetime.fromisoformat(auto['last_run']).timestamp()
            except ValueError:
                continue
            activity.append((stamp, 'warn', f"Auto-download for {name}: {auto.get('last_run_result') or 'ran'}"))
    activity.sort(key=lambda item: item[0], reverse=True)

    on_disk = db.execute("SELECT COUNT(*) AS n FROM books WHERE status='downloaded'").fetchone()['n']
    from utils.events import duplicates_avoided_since
    avoided = duplicates_avoided_since(7 * 86400)
    return {
        'summary': {'members': len(members), 'on_disk': on_disk, 'duplicates_avoided': avoided},
        'attention': attention,
        'members': members,
        'activity': [{'kind': kind, 'text': text, 'when': ago(ts, now)} for ts, kind, text in activity[:8]],
    }


@household_bp.route('/household')
def household_page():
    return render_template('household.html')


@household_bp.route('/api/household/overview')
def household_overview():
    return jsonify(build_overview())
