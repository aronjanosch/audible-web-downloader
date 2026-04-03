/**
 * settings.js — Library management, naming pattern, family sharing
 */

// ── Libraries ──

async function loadLibraries() {
    try {
        const libraries = await apiCall('/api/libraries');
        AppState.set('libraries', libraries);
        _renderLibraryList(libraries);
        document.dispatchEvent(new CustomEvent('libraries:updated', { detail: libraries }));
        return libraries;
    } catch (err) {
        console.error('loadLibraries failed:', err);
        return {};
    }
}

function _renderLibraryList(libraries) {
    const container = document.getElementById('configuredLibraryList');
    if (!container) return;

    if (Object.keys(libraries).length === 0) {
        container.innerHTML = '<p class="text-muted small mb-0">No libraries configured yet.</p>';
        return;
    }

    container.innerHTML = '';
    Object.entries(libraries).forEach(([name, lib]) => {
        const item = document.createElement('div');
        item.className = 'd-flex justify-content-between align-items-start py-2 border-bottom';
        item.innerHTML = `
            <div class="flex-grow-1 me-2 min-width-0">
                <div class="fw-semibold small">${name}</div>
                <div class="text-muted small text-truncate" title="${lib.path}">${lib.path}</div>
            </div>
            <button class="btn btn-sm btn-outline-danger delete-lib-btn flex-shrink-0" data-name="${name}" title="Remove library">
                <i class="fas fa-trash"></i>
            </button>
        `;
        container.appendChild(item);
    });

    container.querySelectorAll('.delete-lib-btn').forEach(btn => {
        btn.addEventListener('click', () => deleteLibrary(btn.dataset.name));
    });
}

async function addLibrary(nameOrForm) {
    let libraryName, libraryPath;

    if (nameOrForm instanceof Event || !nameOrForm) {
        // Called from form submit
        libraryName = document.getElementById('libraryName')?.value?.trim();
        libraryPath = document.getElementById('libraryPath')?.value?.trim();
    } else {
        libraryName = document.getElementById('settingsLibraryName')?.value?.trim();
        libraryPath = document.getElementById('settingsLibraryPath')?.value?.trim();
    }

    if (!libraryName || !libraryPath) {
        showToast('Please enter both library name and path', 'warning');
        return;
    }

    try {
        await apiCall('/api/libraries', {
            method: 'POST',
            body: JSON.stringify({ library_name: libraryName, library_path: libraryPath })
        });

        showToast('Library added!', 'success');
        document.getElementById('addLibraryForm')?.reset();
        document.getElementById('settingsAddLibraryForm')?.reset();
        await loadLibraries();
    } catch (err) {
        showToast('Failed to add library: ' + err.message, 'danger');
    }
}

async function deleteLibrary(libraryName) {
    if (!confirm(`Remove library "${libraryName}"?\n\nFiles are NOT deleted.`)) return;

    try {
        await apiCall(`/api/libraries/${libraryName}`, { method: 'DELETE' });
        showToast('Library removed', 'success');
        await loadLibraries();
    } catch (err) {
        showToast('Failed to remove library: ' + err.message, 'danger');
    }
}

// ── Naming Pattern ──

let _namingSettings = null;

async function loadNamingSettings() {
    try {
        const data = await apiCall('/api/settings/naming');
        _namingSettings = data.settings;
        AppState.set('namingSettings', _namingSettings);
        return _namingSettings;
    } catch (err) {
        console.error('loadNamingSettings failed:', err);
        return null;
    }
}

function populateNamingModal() {
    if (!_namingSettings) return;

    const presetSelect = document.getElementById('namingPreset');
    const patternInput = document.getElementById('customPattern');

    if (presetSelect) presetSelect.value = _namingSettings.selected_preset || 'audiobookshelf';
    if (patternInput) patternInput.value = _namingSettings.naming_pattern || '';

    updatePresetDescription(_namingSettings.selected_preset);
    updatePatternPreview(_namingSettings.naming_pattern);
}

function updatePatternPreview(pattern) {
    const previewEl = document.getElementById('patternPreview');
    if (!previewEl || !pattern) return;

    const sample = {
        '{Author}': 'Terry Pratchett',
        '{Series}': 'Discworld',
        '{Title}': 'Guards! Guards!',
        '{Year}': '2019',
        '{Narrator}': 'Stephen Briggs',
        '{Publisher}': 'Audible Studios',
        '{Language}': 'en',
        '{ASIN}': 'B07X123456',
        '{Volume}': '8'
    };

    let preview = pattern;
    // Handle conditional segments [text {Placeholder}]
    preview = preview.replace(/\[([^\]]*)\]/g, (match, inner) => {
        // Check if placeholder has a value
        let resolved = inner;
        for (const [k, v] of Object.entries(sample)) {
            resolved = resolved.replace(new RegExp(k.replace(/[{}]/g, '\\$&'), 'g'), v);
        }
        return resolved.includes('{') ? '' : resolved;
    });

    for (const [k, v] of Object.entries(sample)) {
        preview = preview.replace(new RegExp(k.replace(/[{}]/g, '\\$&'), 'g'), v);
    }

    preview = preview.replace(/\/+/g, '/').replace(/^\/|\/$/g, '');
    previewEl.textContent = preview || '(invalid pattern)';
}

function updatePresetDescription(presetKey) {
    const descEl = document.getElementById('presetDescription');
    if (!descEl || !_namingSettings?.presets) return;
    const preset = _namingSettings.presets[presetKey];
    if (preset) descEl.textContent = preset.description;
}

async function saveNamingPattern() {
    const pattern = document.getElementById('customPattern')?.value?.trim();
    const preset = document.getElementById('namingPreset')?.value;

    if (!pattern) {
        showToast('Pattern cannot be empty', 'warning');
        return;
    }

    try {
        await apiCall('/api/settings/naming', {
            method: 'POST',
            body: JSON.stringify({ pattern, preset })
        });

        showToast('Naming pattern saved!', 'success');
        bootstrap.Modal.getInstance(document.getElementById('namingPatternModal'))?.hide();
        await loadNamingSettings();
    } catch (err) {
        showToast('Failed to save pattern: ' + err.message, 'danger');
    }
}

// ── Family Sharing ──

async function loadInvitationLink() {
    try {
        const data = await apiCall('/api/settings/invitation-link');
        const el = document.getElementById('invitationLinkDisplay');
        if (el && data.invitation_url) el.value = data.invitation_url;
    } catch (err) {
        const el = document.getElementById('invitationLinkDisplay');
        if (el) el.value = 'Error loading link';
    }
}

function setupFamilySharingModal() {
    document.getElementById('familySharingBtn')?.addEventListener('click', function () {
        loadInvitationLink();
        new bootstrap.Modal(document.getElementById('familySharingModal')).show();
    });

    document.getElementById('copyInviteLinkModalBtn')?.addEventListener('click', function () {
        const val = document.getElementById('invitationLinkDisplay')?.value;
        if (val) copyToClipboard(val, this);
    });

    document.getElementById('saveCustomTokenBtn')?.addEventListener('click', async function () {
        const token = document.getElementById('customInvitationToken')?.value?.trim();
        if (!token) { showToast('Please enter a token', 'warning'); return; }
        if (!/^[a-zA-Z0-9_-]+$/.test(token)) { showToast('Token can only contain letters, numbers, hyphens, underscores', 'danger'); return; }
        if (token.length < 8) { showToast('Token must be at least 8 characters', 'danger'); return; }

        try {
            await apiCall('/api/settings/set-invitation-token', {
                method: 'POST',
                body: JSON.stringify({ token })
            });
            loadInvitationLink();
            document.getElementById('customInvitationToken').value = '';
            showToast('Custom token set!', 'success');
        } catch (err) {
            showToast('Failed to set token: ' + err.message, 'danger');
        }
    });

    document.getElementById('regenerateTokenModalBtn')?.addEventListener('click', async function () {
        if (!confirm('Generate a new random token? The current invitation link will be invalidated.')) return;
        try {
            await apiCall('/api/settings/regenerate-invitation-token', { method: 'POST' });
            loadInvitationLink();
            document.getElementById('customInvitationToken').value = '';
            showToast('New random token generated!', 'success');
        } catch (err) {
            showToast('Failed to regenerate token: ' + err.message, 'danger');
        }
    });
}

// ── Naming Pattern Modal Event Setup ──

function setupNamingPatternModal() {
    document.getElementById('configureNamingBtn')?.addEventListener('click', function () {
        if (!_namingSettings) loadNamingSettings().then(populateNamingModal);
        else populateNamingModal();
        new bootstrap.Modal(document.getElementById('namingPatternModal')).show();
    });

    document.getElementById('namingPreset')?.addEventListener('change', function () {
        updatePresetDescription(this.value);
        if (this.value !== 'custom' && _namingSettings?.presets?.[this.value]) {
            const pattern = _namingSettings.presets[this.value].pattern;
            const patternInput = document.getElementById('customPattern');
            if (patternInput) {
                patternInput.value = pattern;
                updatePatternPreview(pattern);
            }
        }
    });

    document.getElementById('customPattern')?.addEventListener('input', function () {
        updatePatternPreview(this.value);
        const presetSelect = document.getElementById('namingPreset');
        if (presetSelect) presetSelect.value = 'custom';
    });

    document.getElementById('saveNamingPattern')?.addEventListener('click', saveNamingPattern);
}

// ── Library add form (Settings offcanvas / page) ──

function setupLibraryForm(formId) {
    document.getElementById(formId)?.addEventListener('submit', function (e) {
        e.preventDefault();
        addLibrary();
    });
}

// ── DOMContentLoaded ──

document.addEventListener('DOMContentLoaded', function () {
    setupFamilySharingModal();
    setupNamingPatternModal();
    setupLibraryForm('addLibraryForm');
    setupLibraryForm('settingsAddLibraryForm');
    loadLibraries();
    loadNamingSettings();

    // Settings page: delete account button
    document.getElementById('deleteAccountBtn')?.addEventListener('click', function () {
        deleteAccount(AppState.get('currentAccount'));
    });

    // Settings page: login button for selected account
    document.getElementById('loginAccountBtn')?.addEventListener('click', function () {
        authenticateAccount();
    });

    // Settings page: generate invite link for selected account
    document.getElementById('generateAccountInviteBtn')?.addEventListener('click', function () {
        const name = AppState.get('currentAccount');
        if (name) openAccountInviteModal(name);
    });

    // Settings page: cleanup aax checkbox
    document.getElementById('cleanupAax')?.addEventListener('change', function () {
        AppState.set('cleanupAax', this.checked);
    });
});
