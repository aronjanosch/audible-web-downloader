/**
 * accounts.js — Account loading, selection, creation, deletion, auth check
 */

/**
 * Load all accounts from API and trigger unified library load if any are authenticated.
 */
async function loadAccounts() {
    try {
        const [accounts, sessionInfo] = await Promise.all([
            apiCall('/api/accounts'),
            apiCall('/api/session').catch(() => ({ current_account: null })),
        ]);

        AppState.set('accountData', accounts);

        let current = sessionInfo?.current_account ?? null;
        const names = Object.keys(accounts);
        if (current && !accounts[current]) {
            current = null;
        }
        if (!current && names.length === 1) {
            const only = names[0];
            await apiCall(`/api/accounts/${encodeURIComponent(only)}/select`, { method: 'POST' });
            current = only;
        }
        AppState.set('currentAccount', current);

        document.dispatchEvent(new CustomEvent('accounts:loaded', { detail: accounts }));
        return accounts;
    } catch (err) {
        console.error('loadAccounts failed:', err);
        return {};
    }
}

/**
 * Set the active account (server session + AppState).
 */
async function selectAccount(accountName) {
    if (!accountName) return;
    try {
        await apiCall(`/api/accounts/${encodeURIComponent(accountName)}/select`, { method: 'POST' });
        AppState.set('currentAccount', accountName);
        showToast(`Active account: ${accountName}`, 'success');
        document.dispatchEvent(new CustomEvent('accounts:active-changed', { detail: { accountName } }));
    } catch (err) {
        showToast('Failed to set active account: ' + err.message, 'danger');
    }
}

/**
 * Redirect to Audible OAuth login for the given account.
 */
function authenticateAccount(accountName) {
    const name = accountName || AppState.get('currentAccount');
    if (!name) {
        showToast('Select an account first', 'warning');
        return;
    }
    window.location.href = `/auth/login/${name}`;
}

/**
 * Add a new account using inputs inside `root` (wizard card or modal).
 */
async function addAccountFromForm(root) {
    const scope = root && root.querySelector ? root : document;
    const nameInput = scope.querySelector('#modalAccountName') || scope.querySelector('#wizardAccountName');
    const regionInput = scope.querySelector('#modalAccountRegion') || scope.querySelector('#wizardAccountRegion');
    const submitBtn =
        scope.querySelector('#modalSubmitAddAccount') || scope.querySelector('#wizardSubmitAddAccount');

    const accountName = nameInput?.value?.trim();
    const region = regionInput?.value || 'us';

    if (!accountName) {
        showToast('Please enter an account name', 'warning');
        return;
    }

    const restore = submitBtn ? setButtonLoading(submitBtn, 'Adding…') : null;

    try {
        await apiCall('/api/accounts', {
            method: 'POST',
            body: JSON.stringify({ account_name: accountName, region }),
        });

        const modalEl = document.getElementById('addAccountModal');
        const modal = modalEl ? bootstrap.Modal.getInstance(modalEl) : null;
        if (modal) modal.hide();

        document.getElementById('modalAddAccountForm')?.reset();
        document.getElementById('wizardAddAccountForm')?.reset();

        const accounts = await loadAccounts();

        showToast(`Account "${accountName}" added!`, 'success');

        if (Object.keys(accounts).length === 1) {
            document.dispatchEvent(new CustomEvent('onboarding:accountAdded', { detail: { accountName } }));
        }
    } catch (err) {
        showToast('Failed to add account: ' + err.message, 'danger');
    } finally {
        if (restore) restore();
    }
}

/**
 * Delete an account by name.
 */
async function deleteAccount(accountName) {
    if (!accountName) {
        accountName = AppState.get('currentAccount');
    }
    if (!accountName) {
        showToast('Please select an account first', 'warning');
        return;
    }

    if (!confirm(`Delete account "${accountName}"?\n\nThis removes all authentication data.`)) return;

    try {
        await apiCall(`/api/accounts/${encodeURIComponent(accountName)}`, { method: 'DELETE' });
        showToast(`Account "${accountName}" deleted`, 'success');
        await loadAccounts();
    } catch (err) {
        showToast('Failed to delete account: ' + err.message, 'danger');
    }
}

// ── Account Invite Modal ──

let _currentAccountForInvite = null;

async function openAccountInviteModal(accountName) {
    if (!accountName) return;
    _currentAccountForInvite = accountName;

    try {
        const accounts = await apiCall('/api/accounts');
        const account = accounts[accountName];
        if (!account) return;

        document.getElementById('accountInviteAccountName').textContent = accountName;
        document.getElementById('accountInviteDisplayName').textContent = accountName;
        document.getElementById('accountInviteRegion').textContent = account.region.toUpperCase();

        if (account.pending_invitation_token) {
            const url = window.location.origin + '/invite/account/' + account.pending_invitation_token;
            _showAccountInviteLink(url);
        } else {
            _hideAccountInviteLink();
        }

        new bootstrap.Modal(document.getElementById('accountInviteModal')).show();
    } catch (err) {
        showToast('Failed to load account details: ' + err.message, 'danger');
    }
}

function _showAccountInviteLink(url) {
    const el = document.getElementById('accountInviteLinkDisplay');
    if (el) el.value = url;
    document.getElementById('accountInviteLinkSection')?.removeAttribute('style');
    const gen = document.getElementById('generateAccountInviteSection');
    if (gen) gen.style.display = 'none';
}

function _hideAccountInviteLink() {
    const link = document.getElementById('accountInviteLinkSection');
    if (link) link.style.display = 'none';
    document.getElementById('generateAccountInviteSection')?.removeAttribute('style');
}

function setupAccountInviteModal() {
    document.getElementById('generateAccountInviteLinkBtn')?.addEventListener('click', async function () {
        if (!_currentAccountForInvite) return;
        try {
            const data = await apiCall(`/api/accounts/${encodeURIComponent(_currentAccountForInvite)}/generate-invite-link`, { method: 'POST' });
            _showAccountInviteLink(data.invitation_url);
            showToast('Invitation link generated!', 'success');
        } catch (err) {
            showToast('Failed to generate link: ' + err.message, 'danger');
        }
    });

    document.getElementById('copyAccountInviteLinkBtn')?.addEventListener('click', function () {
        const val = document.getElementById('accountInviteLinkDisplay')?.value;
        if (val) copyToClipboard(val, this);
    });

    document.getElementById('revokeAccountInviteBtn')?.addEventListener('click', async function () {
        if (!_currentAccountForInvite) return;
        if (!confirm('Revoke invitation link?')) return;
        try {
            await apiCall(`/api/accounts/${encodeURIComponent(_currentAccountForInvite)}/revoke-invite-link`, { method: 'POST' });
            _hideAccountInviteLink();
            showToast('Invitation link revoked', 'success');
        } catch (err) {
            showToast('Failed to revoke link: ' + err.message, 'danger');
        }
    });
}

// ── Init event listeners that are needed on all pages ──

document.addEventListener('DOMContentLoaded', function () {
    document.querySelectorAll('.js-open-add-account-modal').forEach(function (btn) {
        btn.addEventListener('click', function () {
            const el = document.getElementById('addAccountModal');
            if (!el) return;
            bootstrap.Modal.getOrCreateInstance(el).show();
        });
    });

    document.getElementById('modalSubmitAddAccount')?.addEventListener('click', function () {
        const form = document.getElementById('modalAddAccountForm');
        if (form?.checkValidity()) {
            addAccountFromForm(document.getElementById('addAccountModal'));
        } else {
            form?.reportValidity();
        }
    });

    document.getElementById('wizardSubmitAddAccount')?.addEventListener('click', function () {
        const form = document.getElementById('wizardAddAccountForm');
        if (form?.checkValidity()) {
            addAccountFromForm(document.getElementById('wizardStep1') || form);
        } else {
            form?.reportValidity();
        }
    });

    setupAccountInviteModal();
});
