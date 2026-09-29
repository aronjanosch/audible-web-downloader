// ── Auto-Download ──────────────────────────────────────────────
let _autoDownloadData = {};
let _routableFields = [];
// Per-account working copy of rules (mutated by the UI before saving)
const _accountRules = {};

async function loadAutoDownloadStatus() {
    try {
        const res = await apiCall('/api/auto-download');
        _autoDownloadData = res.accounts || {};
        _routableFields = res.routable_fields || [];
    } catch (e) {
        _autoDownloadData = {};
        _routableFields = [];
    }
}

async function renderAutoDownloadAccounts() {
    const container = document.getElementById('autoDownloadAccountList');
    if (!container) return;

    await loadAutoDownloadStatus();
    const accountData = AppState.get('accountData') || {};
    const libraries = AppState.get('libraries') || {};
    const libNames = Object.keys(libraries);

    const authenticatedAccounts = Object.entries(accountData).filter(([, a]) => a.authenticated);

    if (authenticatedAccounts.length === 0) {
        container.innerHTML = '<p class="text-muted small">No authenticated accounts. Add and authenticate an account first.</p>';
        return;
    }

    container.innerHTML = '';
    authenticatedAccounts.forEach(([name, acc]) => {
        const cfg = _autoDownloadData[name] || {};
        // Seed the working rules copy from persisted config
        _accountRules[name] = (cfg.rules || []).map(r => ({ ...r }));
        container.appendChild(_buildAccountCard(name, acc, cfg, libNames));
    });
}

function _buildAccountCard(name, acc, cfg, libNames) {
    const enabled = cfg.enabled || false;
    const intervalHours = cfg.interval_hours || 6;
    const defaultLib = cfg.default_library_name || '';
    const lastRun = cfg.last_run ? new Date(cfg.last_run).toLocaleString() : 'Never';
    const lastResult = cfg.last_run_result || '';
    const nextRun = cfg.next_run ? new Date(cfg.next_run).toLocaleString() : null;

    const intervalOptions = [6, 12, 24, 48].map(h =>
        `<option value="${h}" ${h === intervalHours ? 'selected' : ''}>${h}h</option>`
    ).join('');

    const defaultLibOptions = ['', ...libNames].map(lib =>
        `<option value="${_escHtml(lib)}" ${lib === defaultLib ? 'selected' : ''}>${_escHtml(lib || '— skip unmatched books —')}</option>`
    ).join('');

    const card = document.createElement('div');
    card.className = 'panel mb-3';
    card.dataset.accountName = name;
    card.innerHTML = `
        <div class="d-flex align-items-center justify-content-between mb-3">
            <div>
                <span class="fw-semibold">${_escHtml(name)}</span>
                <span class="text-muted small ms-2">${_escHtml(acc.region?.toUpperCase() || '')}</span>
            </div>
            <div class="form-check form-switch mb-0">
                <label class="form-check-label small">
                    <input class="form-check-input auto-dl-toggle" type="checkbox" role="switch"
                           ${enabled ? 'checked' : ''}> Enabled
                </label>
            </div>
        </div>

        <div class="row g-2 mb-3">
            <div class="col-auto">
                <label class="form-label small fw-semibold mb-1">Check every
                    <select class="form-select form-select-sm auto-dl-interval" style="width:auto">
                        ${intervalOptions}
                    </select>
                </label>
            </div>
        </div>

        <div class="mb-1">
            <span class="small fw-semibold">Library routing rules</span>
            <span class="text-muted small ms-1">(first match wins)</span>
        </div>
        <div class="auto-dl-rules-container mb-2"></div>
        <button type="button" class="btn btn-outline-secondary btn-sm auto-dl-add-rule mb-3">
            <i class="fas fa-plus me-1"></i>Add rule
        </button>

        <div class="mb-3">
            <label class="form-label small fw-semibold mb-1">Default library
                <select class="form-select form-select-sm auto-dl-default-lib" style="max-width:260px">
                    ${defaultLibOptions}
                </select>
            </label>
            <div class="text-muted" style="font-size:0.75rem;margin-top:3px">
                Books not matched by any rule — leave empty to skip them
            </div>
        </div>

        <div class="d-flex gap-2 align-items-center mb-2">
            <button class="btn btn-primary btn-sm auto-dl-save">Save</button>
            <button class="btn btn-outline-secondary btn-sm auto-dl-run-now" title="Run now">
                <i class="fas fa-play me-1"></i>Run now
            </button>
        </div>

        <div class="text-muted" style="font-size:0.75rem;">
            Last run: <strong>${_escHtml(lastRun)}</strong>${lastResult ? ' — ' + _escHtml(lastResult) : ''}
            ${nextRun ? `<span class="ms-3">Next: <strong>${_escHtml(nextRun)}</strong></span>` : ''}
        </div>
    `;

    // Render initial rules rows
    const rulesContainer = card.querySelector('.auto-dl-rules-container');
    _renderRulesRows(rulesContainer, name, libNames);

    // Add rule
    card.querySelector('.auto-dl-add-rule').addEventListener('click', () => {
        _accountRules[name].push({ field: _routableFields[0] || 'language', value: '', library_name: libNames[0] || '' });
        _renderRulesRows(rulesContainer, name, libNames);
    });

    // Save
    card.querySelector('.auto-dl-save').addEventListener('click', async () => {
        const isEnabled = card.querySelector('.auto-dl-toggle').checked;
        const intervalHrs = parseInt(card.querySelector('.auto-dl-interval').value);
        const defaultLibName = card.querySelector('.auto-dl-default-lib').value;
        const rules = _accountRules[name] || [];

        if (isEnabled && rules.length === 0 && !defaultLibName) {
            showToast('Add at least one rule or a default library before enabling.', 'warning');
            return;
        }

        for (const [i, r] of rules.entries()) {
            if (!r.value.trim()) {
                showToast(`Rule ${i + 1}: value cannot be empty.`, 'warning');
                return;
            }
            if (!r.library_name) {
                showToast(`Rule ${i + 1}: please select a library.`, 'warning');
                return;
            }
        }

        try {
            await apiCall(`/api/accounts/${encodeURIComponent(name)}/auto-download`, {
                method: 'PUT',
                body: JSON.stringify({
                    enabled: isEnabled,
                    interval_hours: intervalHrs,
                    rules,
                    default_library_name: defaultLibName || null,
                })
            });
            showToast(`Auto-download saved for ${name}.`, 'success');
            await renderAutoDownloadAccounts();
        } catch (err) {
            showToast('Failed to save: ' + err.message, 'danger');
        }
    });

    // Run now
    card.querySelector('.auto-dl-run-now').addEventListener('click', async () => {
        try {
            await apiCall(`/api/accounts/${encodeURIComponent(name)}/auto-download/trigger`, { method: 'POST' });
            showToast(`Auto-download triggered for ${name}. Check Downloads for progress.`, 'info');
        } catch (err) {
            showToast('Failed to trigger: ' + err.message, 'danger');
        }
    });

    return card;
}

function _renderRulesRows(container, accountName, libNames) {
    const rules = _accountRules[accountName] || [];

    if (rules.length === 0) {
        container.innerHTML = '<p class="text-muted small mb-2">No rules yet — all books go to the default library.</p>';
        return;
    }

    container.innerHTML = '';

    // Header row
    const header = document.createElement('div');
    header.className = 'd-flex gap-2 mb-1';
    header.style.fontSize = '0.75rem';
    header.innerHTML = `
        <div style="width:130px" class="text-muted fw-semibold">Field</div>
        <div style="flex:1" class="text-muted fw-semibold">Contains</div>
        <div style="width:170px" class="text-muted fw-semibold">Library</div>
        <div style="width:74px"></div>
    `;
    container.appendChild(header);

    rules.forEach((rule, idx) => {
        const row = document.createElement('div');
        row.className = 'd-flex gap-2 mb-1 align-items-center';

        const fieldOptions = _routableFields.map(f =>
            `<option value="${_escHtml(f)}" ${f === rule.field ? 'selected' : ''}>${_escHtml(f)}</option>`
        ).join('');
        const libOptions = ['', ...libNames].map(lib =>
            `<option value="${_escHtml(lib)}" ${lib === rule.library_name ? 'selected' : ''}>${_escHtml(lib || '— select —')}</option>`
        ).join('');

        row.innerHTML = `
            <select class="form-select form-select-sm rule-field" style="width:130px">${fieldOptions}</select>
            <input type="text" class="form-control form-control-sm rule-value" placeholder="e.g. german"
                   value="${_escHtml(rule.value)}" style="flex:1">
            <select class="form-select form-select-sm rule-library" style="width:170px">${libOptions}</select>
            <div class="d-flex gap-1" style="width:74px">
                <button class="btn btn-outline-secondary btn-sm rule-up px-2" title="Move up" ${idx === 0 ? 'disabled' : ''}>
                    <i class="fas fa-arrow-up"></i>
                </button>
                <button class="btn btn-outline-secondary btn-sm rule-down px-2" title="Move down" ${idx === rules.length - 1 ? 'disabled' : ''}>
                    <i class="fas fa-arrow-down"></i>
                </button>
                <button class="btn btn-outline-danger btn-sm rule-delete px-2" title="Remove rule">
                    <i class="fas fa-times"></i>
                </button>
            </div>
        `;

        // Sync changes back to working array immediately
        row.querySelector('.rule-field').addEventListener('change', e => { rules[idx].field = e.target.value; });
        row.querySelector('.rule-value').addEventListener('input', e => { rules[idx].value = e.target.value; });
        row.querySelector('.rule-library').addEventListener('change', e => { rules[idx].library_name = e.target.value; });

        row.querySelector('.rule-up').addEventListener('click', () => {
            if (idx === 0) return;
            [rules[idx - 1], rules[idx]] = [rules[idx], rules[idx - 1]];
            _renderRulesRows(container, accountName, libNames);
        });
        row.querySelector('.rule-down').addEventListener('click', () => {
            if (idx === rules.length - 1) return;
            [rules[idx], rules[idx + 1]] = [rules[idx + 1], rules[idx]];
            _renderRulesRows(container, accountName, libNames);
        });
        row.querySelector('.rule-delete').addEventListener('click', () => {
            rules.splice(idx, 1);
            _renderRulesRows(container, accountName, libNames);
        });

        container.appendChild(row);
    });
}

function _escHtml(str) {
    return String(str ?? '').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');
}

// ── Main init ───────────────────────────────────────────────────
// Render accounts list on the settings page
document.addEventListener('DOMContentLoaded', async function () {
    await loadAccounts();
    await _loadHealth();
    _renderSettingsAccounts();
    _initTabHash();
    _initAppearance();

    document.addEventListener('appstate:change', function(e) {
        if (e.detail.key === 'accountData' || e.detail.key === 'currentAccount') _loadHealth().then(_renderSettingsAccounts);
    });
    document.addEventListener('accounts:active-changed', function() {
        _renderSettingsAccounts();
    });
    document.getElementById('tab-libraries')?.addEventListener('shown.bs.tab', loadLibraries);
    loadLibraries();

    // Load auto-download tab when it becomes active
    document.getElementById('tab-autodownload')?.addEventListener('shown.bs.tab', async function() {
        await loadLibraries();
        await renderAutoDownloadAccounts();
    });

    // Add library form on this page
    document.getElementById('settingsAddLibraryForm')?.addEventListener('submit', async function(e) {
        e.preventDefault();
        const name = document.getElementById('settingsLibraryName')?.value?.trim();
        const path = document.getElementById('settingsLibraryPath')?.value?.trim();
        if (!name || !path) return;

        try {
            await apiCall('/api/libraries', {
                method: 'POST',
                body: JSON.stringify({ library_name: name, library_path: path })
            });
            showToast('Library added!', 'success');
            this.reset();
            await loadLibraries();
        } catch (err) {
            showToast('Failed to add library: ' + err.message, 'danger');
        }
    });
});

// ── Accounts with token health (design 1e) ──────────────────────
const _AVATAR_COLORS = ['#c9761a', '#3d4a6b', '#8a3b2e', '#2f5d50', '#5b3f5e', '#2d6a73'];
let _healthByName = {};

async function _loadHealth() {
    try {
        const data = await apiCall('/api/household/overview');
        _healthByName = {};
        (data.members || []).forEach(m => { _healthByName[m.name] = m; });
    } catch (e) {
        _healthByName = {};
    }
}

function _initials(name) {
    const parts = String(name).replace(/[_-]/g, ' ').split(/\s+/).filter(Boolean);
    const letters = parts.length > 1 ? parts.map(p => p[0]).join('') : String(name).slice(0, 2);
    return letters.slice(0, 2).toUpperCase();
}

function _el(tag, cls, text) {
    const n = document.createElement(tag);
    if (cls) n.className = cls;
    if (text != null) n.textContent = text;
    return n;
}

function _renderSettingsAccounts() {
    const container = document.getElementById('settingsAccountList');
    if (!container) return;

    const accountData = AppState.get('accountData') || {};
    const activeName = AppState.get('currentAccount');
    const names = Object.keys(accountData).sort((a, b) => a.localeCompare(b));
    container.replaceChildren();

    if (names.length === 0) {
        container.append(_el('p', 'text-muted', 'No accounts yet. Use “+ Add account” to get started.'));
        return;
    }

    names.forEach((name, idx) => {
        const acc = accountData[name];
        const h = _healthByName[name] || {
            state: acc.authenticated ? 'ok' : 'err',
            label: acc.authenticated ? 'Connected' : 'Not connected',
            percent: acc.authenticated ? 100 : 100,
            detail: acc.authenticated ? 'Health details unavailable' : 'Needs to reconnect Audible',
            books: null,
        };
        const card = _el('article', 'acct-card');
        card.dataset.account = name;

        const av = _el('div', 'avatar avatar-lg', _initials(name));
        av.style.background = _AVATAR_COLORS[idx % _AVATAR_COLORS.length];
        av.setAttribute('aria-hidden', 'true');

        const mid = _el('div', 'acct-mid');
        const line = _el('div', 'acct-line');
        line.append(_el('span', 'acct-name', name));
        if (activeName === name) line.append(_el('span', 'pill pill-active', 'Active'));
        const meta = [acc.region ? String(acc.region).toUpperCase() : '', h.books != null ? `${h.books} books` : ''].filter(Boolean).join(' · ');
        line.append(_el('span', 'acct-meta', meta));
        line.append(_el('span', 'pill ' + ({ ok: 'pill-ok', warn: 'pill-warn', err: 'pill-err' }[h.state] || ''), h.label));
        const track = _el('div', 'track thick acct-track');
        const fill = _el('span', 'fill ' + ({ warn: 'orange', err: 'err' }[h.state] || ''));
        fill.style.width = Math.max(0, Math.min(100, h.percent)) + '%';
        track.append(fill);
        mid.append(line, track, _el('div', 'acct-detail', h.detail));

        const actions = _el('div', 'acct-actions');
        const primary = _el('button', 'btn btn-sm acct-primary ' + (h.state === 'err' ? 'is-err' : h.state === 'warn' ? 'is-warn' : 'btn-outline-secondary'));
        primary.type = 'button';
        if (h.state === 'err') {
            primary.textContent = 'Send reconnect link';
            primary.addEventListener('click', () => openAccountInviteModal(name));
        } else {
            primary.textContent = 'Reconnect';
            primary.addEventListener('click', () => authenticateAccount(name));
        }
        const more = _el('div', 'dropdown');
        const moreBtn = _el('button', 'btn btn-sm acct-more', '⋯');
        moreBtn.type = 'button';
        moreBtn.setAttribute('data-bs-toggle', 'dropdown');
        moreBtn.setAttribute('aria-expanded', 'false');
        moreBtn.setAttribute('aria-label', `More actions for ${name}`);
        const menu = _el('ul', 'dropdown-menu dropdown-menu-end');
        const item = (label, fn, danger) => {
            const li = _el('li');
            const b = _el('button', 'dropdown-item' + (danger ? ' text-danger' : ''), label);
            b.type = 'button';
            b.addEventListener('click', fn);
            li.append(b);
            menu.append(li);
        };
        if (activeName !== name) item('Set as active', () => selectAccount(name));
        item('Generate invite link', () => openAccountInviteModal(name));
        item('Delete account', () => deleteAccount(name), true);
        more.append(moreBtn, menu);
        actions.append(primary, more);

        card.append(av, mid, actions);
        container.append(card);
    });
}

function _initTabHash() {
    const map = { accounts: 'tab-accounts', libraries: 'tab-libraries', naming: 'tab-preferences',
                  autodownload: 'tab-autodownload', audiobookshelf: 'tab-audiobookshelf',
                  invites: 'tab-invites', appearance: 'tab-appearance' };
    const wanted = map[(location.hash || '').slice(1)];
    if (wanted) bootstrap.Tab.getOrCreateInstance(document.getElementById(wanted)).show();
    document.querySelectorAll('.settings-nav-item').forEach(btn => {
        btn.addEventListener('shown.bs.tab', () => {
            const key = Object.keys(map).find(k => map[k] === btn.id);
            if (key) history.replaceState(null, '', '#' + key);
        });
    });
}

function _initAppearance() {
    const KEY = 'audible-downloader-theme';
    const sync = () => {
        const cur = document.documentElement.getAttribute('data-bs-theme') === 'dark' ? 'dark' : 'light';
        document.querySelectorAll('[data-theme-choice]').forEach(b => {
            const on = b.dataset.themeChoice === cur;
            b.classList.toggle('active', on);
            b.setAttribute('aria-pressed', String(on));
        });
    };
    document.querySelectorAll('[data-theme-choice]').forEach(b => b.addEventListener('click', () => {
        document.documentElement.setAttribute('data-bs-theme', b.dataset.themeChoice);
        try { localStorage.setItem(KEY, b.dataset.themeChoice); } catch (e) { /* ignore */ }
        sync();
    }));
    sync();
}
