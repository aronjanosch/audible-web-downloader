/**
 * theme.js — Light/dark mode: persists preference, syncs toggle UI
 */
(function () {
    const STORAGE_KEY = 'audible-downloader-theme';

    function currentTheme() {
        return document.documentElement.getAttribute('data-bs-theme') === 'dark'
            ? 'dark'
            : 'light';
    }

    function syncToggleUi(theme) {
        const btn = document.getElementById('themeToggleBtn');
        if (!btn) return;
        const icon = btn.querySelector('i');
        if (icon) {
            icon.className = theme === 'dark' ? 'fas fa-sun' : 'fas fa-moon';
        }
        const label = theme === 'dark' ? 'Switch to light mode' : 'Switch to dark mode';
        btn.title = label;
        btn.setAttribute('aria-label', label);
    }

    function toggleTheme() {
        const next = currentTheme() === 'dark' ? 'light' : 'dark';
        document.documentElement.setAttribute('data-bs-theme', next);
        try {
            localStorage.setItem(STORAGE_KEY, next);
        } catch (e) {
            /* ignore quota / private mode */
        }
        syncToggleUi(next);
    }

    document.addEventListener('DOMContentLoaded', function () {
        const btn = document.getElementById('themeToggleBtn');
        if (btn) {
            btn.addEventListener('click', toggleTheme);
        }
        syncToggleUi(currentTheme());
    });
})();
