"""
APScheduler wrapper for the auto-download feature.
The BackgroundScheduler runs jobs in daemon threads alongside Flask.
"""
import logging
from apscheduler.schedulers.background import BackgroundScheduler

logger = logging.getLogger(__name__)

_scheduler: BackgroundScheduler | None = None


def init_scheduler(app) -> None:
    """
    Create and start the BackgroundScheduler, then register one interval job
    for every account that has auto_download.enabled == True.
    Stores the scheduler on app.scheduler for later use.
    """
    global _scheduler

    _scheduler = BackgroundScheduler(daemon=True)
    _scheduler.start()
    app.scheduler = _scheduler

    from utils.config_manager import get_config_manager
    config_manager = get_config_manager()
    accounts = config_manager.get_accounts()

    for account_name, account_data in accounts.items():
        auto_download = account_data.get('auto_download', {})
        if auto_download.get('enabled') and account_data.get('authenticated'):
            update_job(app, account_name, auto_download)

    logger.info("Scheduler started (%d auto-download job(s) registered)", len(_scheduler.get_jobs()))


def update_job(app, account_name: str, auto_download_config: dict) -> None:
    """
    Add, replace, or remove the interval job for *account_name* based on whether
    auto_download is enabled. Library routing is resolved at runtime inside the job,
    so no library path is needed here.
    """
    from utils.auto_downloader import run_auto_download
    from utils.config_manager import get_config_manager

    scheduler = _get_scheduler(app)
    job_id = f"auto_download_{account_name}"

    if scheduler.get_job(job_id):
        scheduler.remove_job(job_id)

    if not auto_download_config.get('enabled'):
        logger.info("Auto-download disabled for '%s', job removed", account_name)
        return

    config_manager = get_config_manager()
    account = config_manager.get_account(account_name)
    if not account or not account.get('authenticated'):
        logger.warning("Cannot schedule auto-download for unauthenticated account '%s'", account_name)
        return

    region = account.get('region', 'us')
    rules = auto_download_config.get('rules', [])
    default_library_name = auto_download_config.get('default_library_name') or None
    interval_hours = int(auto_download_config.get('interval_hours', 6))

    if not rules and not default_library_name:
        logger.warning(
            "Auto-download for '%s': no rules and no default library — job not scheduled",
            account_name
        )
        return

    scheduler.add_job(
        run_auto_download,
        trigger='interval',
        hours=interval_hours,
        id=job_id,
        replace_existing=True,
        kwargs={
            'account_name': account_name,
            'region': region,
            'rules': rules,
            'default_library_name': default_library_name,
            'app': app,
        },
        misfire_grace_time=3600,
    )

    rule_summary = f"{len(rules)} rule(s)" + (f" + default '{default_library_name}'" if default_library_name else "")
    logger.info("Auto-download scheduled for '%s' every %dh (%s)", account_name, interval_hours, rule_summary)


def trigger_now(app, account_name: str) -> None:
    """Submit a one-off auto-download job for *account_name* that runs immediately."""
    from utils.auto_downloader import run_auto_download
    from utils.config_manager import get_config_manager

    config_manager = get_config_manager()
    account = config_manager.get_account(account_name)
    if not account:
        raise ValueError(f"Account '{account_name}' not found")
    if not account.get('authenticated'):
        raise ValueError(f"Account '{account_name}' is not authenticated")

    region = account.get('region', 'us')
    auto_download = account.get('auto_download', {})
    rules = auto_download.get('rules', [])
    default_library_name = auto_download.get('default_library_name') or None

    if not rules and not default_library_name:
        raise ValueError("No library rules configured. Add at least one rule or a default library.")

    scheduler = _get_scheduler(app)
    scheduler.add_job(
        run_auto_download,
        trigger='date',
        id=f"auto_download_{account_name}_manual",
        replace_existing=True,
        kwargs={
            'account_name': account_name,
            'region': region,
            'rules': rules,
            'default_library_name': default_library_name,
            'app': app,
        },
    )
    logger.info("Manual auto-download triggered for '%s'", account_name)


def get_next_run_time(app, account_name: str):
    """Return the next scheduled run time for an account's job, or None."""
    scheduler = _get_scheduler(app)
    job = scheduler.get_job(f"auto_download_{account_name}")
    if job and job.next_run_time:
        return job.next_run_time.isoformat()
    return None


def _get_scheduler(app) -> BackgroundScheduler:
    return getattr(app, 'scheduler', None) or _scheduler
