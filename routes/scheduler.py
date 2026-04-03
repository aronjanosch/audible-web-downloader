from flask import Blueprint, request, current_app
from utils.config_manager import get_config_manager
from utils.errors import success_response, AccountNotFoundError, ValidationError
from utils.scheduler import update_job, trigger_now, get_next_run_time
from utils.auto_downloader import ROUTABLE_FIELDS

scheduler_bp = Blueprint('scheduler', __name__)
config_manager = get_config_manager()


@scheduler_bp.route('/api/auto-download', methods=['GET'])
def get_auto_download_status():
    """Return auto-download config and next_run_time for all accounts."""
    accounts = config_manager.get_accounts()
    result = {}
    for account_name, account_data in accounts.items():
        auto_download = account_data.get('auto_download', {})
        result[account_name] = {
            **auto_download,
            'next_run': get_next_run_time(current_app._get_current_object(), account_name),
        }
    return success_response({'accounts': result, 'routable_fields': list(ROUTABLE_FIELDS)})


@scheduler_bp.route('/api/accounts/<account_name>/auto-download', methods=['PUT'])
def configure_auto_download(account_name: str):
    """Configure auto-download settings for an account."""
    account = config_manager.get_account(account_name)
    if account is None:
        raise AccountNotFoundError(account_name)

    data = request.get_json() or {}
    enabled = bool(data.get('enabled', False))
    default_library_name = (data.get('default_library_name') or '').strip() or None
    rules = data.get('rules', [])

    try:
        interval_hours = int(data.get('interval_hours', 6))
        if interval_hours < 1:
            raise ValueError
    except (TypeError, ValueError):
        raise ValidationError('interval_hours must be a positive integer')

    # Validate rules structure
    if not isinstance(rules, list):
        raise ValidationError('rules must be a list')
    for i, rule in enumerate(rules):
        if not isinstance(rule, dict):
            raise ValidationError(f'rule[{i}] must be an object')
        if rule.get('field') not in ROUTABLE_FIELDS:
            raise ValidationError(
                f'rule[{i}].field must be one of: {", ".join(ROUTABLE_FIELDS)}'
            )
        if not (rule.get('value') or '').strip():
            raise ValidationError(f'rule[{i}].value must not be empty')
        if not (rule.get('library_name') or '').strip():
            raise ValidationError(f'rule[{i}].library_name must not be empty')

    if enabled and not rules and not default_library_name:
        raise ValidationError(
            'Add at least one rule or a default library before enabling auto-download'
        )

    existing = account.get('auto_download', {})
    auto_download_config = {
        **existing,
        'enabled': enabled,
        'interval_hours': interval_hours,
        'rules': rules,
        'default_library_name': default_library_name,
    }
    config_manager.update_account(account_name, {'auto_download': auto_download_config})
    update_job(current_app._get_current_object(), account_name, auto_download_config)

    return success_response({
        'account_name': account_name,
        'auto_download': auto_download_config,
        'next_run': get_next_run_time(current_app._get_current_object(), account_name),
    })


@scheduler_bp.route('/api/accounts/<account_name>/auto-download/trigger', methods=['POST'])
def trigger_auto_download(account_name: str):
    """Immediately run an auto-download sync for the account."""
    account = config_manager.get_account(account_name)
    if account is None:
        raise AccountNotFoundError(account_name)

    if not account.get('authenticated'):
        raise ValidationError(f"Account '{account_name}' is not authenticated")

    try:
        trigger_now(current_app._get_current_object(), account_name)
    except ValueError as exc:
        raise ValidationError(str(exc))

    return success_response({'message': f"Auto-download triggered for '{account_name}'"}, status_code=202)
