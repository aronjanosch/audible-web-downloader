"""
Centralized configuration management backed by SQLite.

All public method signatures are identical to the previous JSON-based
implementation so existing callers (routes, scheduler, auto-downloader)
require no changes.

Settings (naming_pattern, invitation_token) remain in settings.json and
are still managed by SettingsManager — this class does not touch them.
Auth files (config/auth/*/auth.json) are also untouched.
"""

import time
from pathlib import Path
from typing import Any, Dict, Optional

from utils.db import get_db, transaction
from utils.constants import CONFIG_DIR, AUTH_DIR


class ConfigurationError(Exception):
    """Raised when configuration operations fail"""
    pass


class ValidationError(ConfigurationError):
    """Raised when configuration data fails validation"""
    pass


class ConfigManager:
    """
    Manages accounts and library configurations using the SQLite database.
    """

    def __init__(self):
        self._ensure_directories()

    def _ensure_directories(self) -> None:
        CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        AUTH_DIR.mkdir(parents=True, exist_ok=True)

    # ========== Accounts Management ==========

    def get_accounts(self) -> Dict[str, Any]:
        """
        Load all Audible accounts.

        Returns:
            Dictionary of account data keyed by account name, each entry
            matching the old JSON shape (including nested ``auto_download``).
        """
        db = get_db()
        accounts: Dict[str, Any] = {}

        for row in db.execute("SELECT * FROM accounts ORDER BY name"):
            name = row["name"]
            accounts[name] = self._row_to_account(row, db)

        return accounts

    def save_accounts(self, accounts: Dict[str, Any]) -> None:
        """
        Persist all account data, replacing existing records.

        Args:
            accounts: Dictionary of account data keyed by account name.
        """
        with transaction() as conn:
            # Remove accounts that are no longer present
            existing = {r["name"] for r in conn.execute("SELECT name FROM accounts")}
            incoming = set(accounts.keys())
            for name in existing - incoming:
                conn.execute("DELETE FROM accounts WHERE name=?", (name,))

            for name, data in accounts.items():
                self._upsert_account(conn, name, data)

    def get_account(self, account_name: str) -> Optional[Dict[str, Any]]:
        """
        Get a specific account by name.

        Returns:
            Account data dictionary or None if not found.
        """
        db = get_db()
        row = db.execute("SELECT * FROM accounts WHERE name=?", (account_name,)).fetchone()
        if row is None:
            return None
        return self._row_to_account(row, db)

    def update_account(self, account_name: str, updates: Dict[str, Any]) -> None:
        """
        Merge ``updates`` into an existing account's data.

        Raises:
            ConfigurationError: If the account does not exist.
        """
        existing = self.get_account(account_name)
        if existing is None:
            raise ConfigurationError(f"Account '{account_name}' not found")

        # Deep-merge the auto_download sub-dict if present
        if "auto_download" in updates and "auto_download" in existing:
            merged_auto = {**existing["auto_download"], **updates["auto_download"]}
            updates = {**updates, "auto_download": merged_auto}

        merged = {**existing, **updates}

        with transaction() as conn:
            self._upsert_account(conn, account_name, merged)

    def delete_account(self, account_name: str) -> None:
        """
        Delete an account.

        Raises:
            ConfigurationError: If the account does not exist.
        """
        db = get_db()
        row = db.execute("SELECT name FROM accounts WHERE name=?", (account_name,)).fetchone()
        if row is None:
            raise ConfigurationError(f"Account '{account_name}' not found")
        with transaction() as conn:
            conn.execute("DELETE FROM accounts WHERE name=?", (account_name,))

    # ========== Libraries Management ==========

    def get_libraries(self) -> Dict[str, Any]:
        """
        Load all library configurations.

        Returns:
            Dictionary of library configurations keyed by library name.
        """
        db = get_db()
        return {
            row["name"]: {"path": row["path"], "created_at": row["created_at"]}
            for row in db.execute("SELECT * FROM libraries ORDER BY name")
        }

    def save_libraries(self, libraries: Dict[str, Any]) -> None:
        """
        Persist all library configurations, replacing existing records.
        """
        with transaction() as conn:
            existing = {r["name"] for r in conn.execute("SELECT name FROM libraries")}
            incoming = set(libraries.keys())
            for name in existing - incoming:
                conn.execute("DELETE FROM libraries WHERE name=?", (name,))

            for name, data in libraries.items():
                conn.execute(
                    """
                    INSERT INTO libraries (name, path, created_at)
                    VALUES (?,?,?)
                    ON CONFLICT(name) DO UPDATE SET path=excluded.path
                    """,
                    (name, data.get("path", ""), data.get("created_at", time.time())),
                )

    def get_library(self, library_name: str) -> Optional[Dict[str, Any]]:
        """
        Get a specific library configuration by name.

        Returns:
            Library configuration dictionary or None if not found.
        """
        db = get_db()
        row = db.execute("SELECT * FROM libraries WHERE name=?", (library_name,)).fetchone()
        if row is None:
            return None
        return {"path": row["path"], "created_at": row["created_at"]}

    def update_library(self, library_name: str, updates: Dict[str, Any]) -> None:
        """
        Update specific fields of a library configuration.

        Raises:
            ConfigurationError: If the library does not exist.
        """
        existing = self.get_library(library_name)
        if existing is None:
            raise ConfigurationError(f"Library '{library_name}' not found")
        merged = {**existing, **updates}
        with transaction() as conn:
            conn.execute(
                "UPDATE libraries SET path=?, created_at=? WHERE name=?",
                (merged.get("path", ""), merged.get("created_at", time.time()), library_name),
            )

    def delete_library(self, library_name: str) -> None:
        """
        Delete a library configuration.

        Raises:
            ConfigurationError: If the library does not exist.
        """
        db = get_db()
        row = db.execute("SELECT name FROM libraries WHERE name=?", (library_name,)).fetchone()
        if row is None:
            raise ConfigurationError(f"Library '{library_name}' not found")
        with transaction() as conn:
            conn.execute("DELETE FROM libraries WHERE name=?", (library_name,))

    # ========== Settings Management ==========
    # Settings (naming_pattern, invitation_token) remain in settings.json.
    # These methods delegate to that file for backward compatibility.

    def get_settings(self) -> Dict[str, Any]:
        import json
        settings_file = CONFIG_DIR / "settings.json"
        if not settings_file.exists():
            return {}
        try:
            with open(settings_file, "r", encoding="utf-8") as fh:
                return json.load(fh)
        except (json.JSONDecodeError, IOError):
            return {}

    def save_settings(self, settings: Dict[str, Any]) -> None:
        import json
        settings_file = CONFIG_DIR / "settings.json"
        settings_file.parent.mkdir(parents=True, exist_ok=True)
        tmp = settings_file.with_suffix(".tmp")
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(settings, fh, indent=2, ensure_ascii=False)
        tmp.replace(settings_file)

    def update_setting(self, key: str, value: Any) -> None:
        settings = self.get_settings()
        settings[key] = value
        self.save_settings(settings)

    # ========== Validation ==========

    def validate_account(self, account_data: Dict[str, Any]) -> bool:
        """
        Validate account data structure.

        Returns:
            True if valid.

        Raises:
            ValidationError: If account data is invalid.
        """
        for field in ("region", "authenticated"):
            if field not in account_data:
                raise ValidationError(f"Account missing required field: {field}")

        valid_regions = {"us", "uk", "de", "fr", "jp", "it", "in", "ca", "au", "es"}
        if account_data["region"] not in valid_regions:
            raise ValidationError(f"Invalid region: {account_data['region']}")

        if not isinstance(account_data["authenticated"], bool):
            raise ValidationError("Field 'authenticated' must be boolean")

        return True

    def validate_library(self, library_config: Dict[str, Any]) -> bool:
        """
        Validate library configuration structure.

        Returns:
            True if valid.

        Raises:
            ValidationError: If library configuration is invalid.
        """
        if "path" not in library_config:
            raise ValidationError("Library missing required field: path")
        return True

    # ========== Private helpers ==========

    def _row_to_account(self, row: Any, db: Any) -> Dict[str, Any]:
        """Convert a DB row + rules query into the old JSON-shaped dict."""
        name = row["name"]
        rules = [
            {"field": r["field"], "value": r["value"], "library_name": r["library_name"]}
            for r in db.execute(
                "SELECT field, value, library_name FROM auto_download_rules "
                "WHERE account_name=? ORDER BY position",
                (name,),
            )
        ]
        account: Dict[str, Any] = {
            "region": row["region"],
            "authenticated": bool(row["authenticated"]),
        }
        if row["pending_invitation_token"]:
            account["pending_invitation_token"] = row["pending_invitation_token"]

        # Reconstruct the nested auto_download dict (matches old accounts.json shape)
        account["auto_download"] = {
            "enabled": bool(row["auto_dl_enabled"]),
            "interval_hours": row["auto_dl_interval_hours"],
            "rules": rules,
            "default_library_name": row["auto_dl_default_library"],
            "last_run": row["auto_dl_last_run"],
            "last_run_result": row["auto_dl_last_run_result"],
        }
        return account

    def _upsert_account(self, conn: Any, name: str, data: Dict[str, Any]) -> None:
        """Insert or replace a single account and its rules."""
        auto_dl = data.get("auto_download") or {}
        conn.execute(
            """
            INSERT INTO accounts
                (name, region, authenticated,
                 auto_dl_enabled, auto_dl_interval_hours,
                 auto_dl_default_library,
                 auto_dl_last_run, auto_dl_last_run_result,
                 pending_invitation_token)
            VALUES (?,?,?,?,?,?,?,?,?)
            ON CONFLICT(name) DO UPDATE SET
                region                   = excluded.region,
                authenticated            = excluded.authenticated,
                auto_dl_enabled          = excluded.auto_dl_enabled,
                auto_dl_interval_hours   = excluded.auto_dl_interval_hours,
                auto_dl_default_library  = excluded.auto_dl_default_library,
                auto_dl_last_run         = excluded.auto_dl_last_run,
                auto_dl_last_run_result  = excluded.auto_dl_last_run_result,
                pending_invitation_token = excluded.pending_invitation_token
            """,
            (
                name,
                data.get("region", "us"),
                1 if data.get("authenticated") else 0,
                1 if auto_dl.get("enabled") else 0,
                auto_dl.get("interval_hours", 6),
                auto_dl.get("default_library_name"),
                auto_dl.get("last_run"),
                auto_dl.get("last_run_result"),
                data.get("pending_invitation_token"),
            ),
        )
        # Replace rules: delete existing, re-insert in order
        conn.execute("DELETE FROM auto_download_rules WHERE account_name=?", (name,))
        for position, rule in enumerate(auto_dl.get("rules") or []):
            if not isinstance(rule, dict):
                continue
            conn.execute(
                """
                INSERT INTO auto_download_rules
                    (account_name, position, field, value, library_name)
                VALUES (?,?,?,?,?)
                """,
                (name, position, rule.get("field", ""), rule.get("value", ""), rule.get("library_name", "")),
            )


# Global singleton instance
_config_manager: Optional[ConfigManager] = None


def get_config_manager() -> ConfigManager:
    """Return the global ConfigManager singleton."""
    global _config_manager
    if _config_manager is None:
        _config_manager = ConfigManager()
    return _config_manager
