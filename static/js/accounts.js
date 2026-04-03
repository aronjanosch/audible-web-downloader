/**
 * accounts.js — Account loading, selection, creation, deletion, auth check
 */

/**
 * Load all accounts from API and update the navbar account selector.
 * Auto-selects if only one account exists.
 */
async function loadAccounts() {
    try {
        const accounts = await apiCall('/api/accounts');
        AppState.set('accountData', accounts);
        _updateAccountSelector(accounts);

        const names = Object.keys(accounts);
        if (names.length === 1) {
            const select = document.getElementById('accountSelect');
            if (select && select.value !== names[0]) {
                select.value = names[0];
                await selectAccount(names[0]);
            }
        }

        return accounts;
    } catch (err) {
        console.error('loadAccounts failed:', err);
        return {};
    }
}

function _updateAccountSelector(accounts) {
    const select = document.getElementById('accountSelect');
    if (!select) return;

    const current = select.value;
    select.innerHTML = '<option value="">Select account…</option>';

    Object.entries(accounts).forEach(([name, info]) => {
        const opt = document.createElement('option');
        opt.value = name;
        opt.textContent = name;
        opt.dataset.region = info.region;
        opt.dataset.authenticated = info.authenticated;
        select.appendChild(opt);
    });

    if (current && accounts[current]) select.value = current;
}

/**
 * Select an account — calls API, updates AppState, checks auth.
 */
async function selectAccount(accountName) {
    if (!accountName) {
        AppState.set('currentAccount', null);
        AppState.set('isAuthenticated', false);
        _updateStatusDot(false, true);
        document.dispatchEvent(new CustomEvent('account:cleared'));
        return;
    }

    try {
        await apiCall(`/api/accounts/${accountName}/select`, { method: 'POST' });
        AppState.set('currentAccount', accountName);
        await checkAuthentication(accountName);
        document.dispatchEvent(new CustomEvent('account:selected', { detail: { accountName } }));
    } catch (err) {
        showToast('Failed to select account: ' + err.message, 'danger');
    }
}

/**
 * Check if the given account is authenticated; update AppState and UI.
 */
async function checkAuthentication(accountName) {
    try {
        const result = await apiCall('/api/auth/check', {
            method: 'POST',
            body: JSON.stringify({ account_name: accountName })
        });

        const auth = result.authenticated;
        AppState.set('isAuthenticated', auth);
        _updateStatusDot(auth, false);
        document.dispatchEvent(new CustomEvent('auth:statusChanged', { detail: { authenticated: auth, accountName } }));
        return auth;
    } catch (err) {
        console.error('checkAuthentication failed:', err);
        return false;
    }
}

function _updateStatusDot(authenticated, noAccount) {
    const dot = document.getElementById('accountStatusDot');
    if (!dot) return;
    dot.className = 'account-status-dot ' + (noAccount ? 'no-account' : authenticated ? 'authenticated' : 'unauthenticated');
    dot.title = noAccount ? 'No account selected' : authenticated ? 'Authenticated' : 'Not authenticated — click Login';
}

/**
 * Add a new account via the modal form.
 */
async function addAccount() {
    const nameInput = document.getElementById('accountName');
    const regionInput = document.getElementById('accountRegion');

    const accountName = nameInput?.value?.trim();
    const region = regionInput?.value || 'us';

    if (!accountName) {
        showToast('Please enter an account name', 'warning');
        return;
    }

    const btn = document.getElementById('submitAddAccount');
    const restore = btn ? setButtonLoading(btn, 'Adding…') : null;

    try {
        await apiCall('/api/accounts', {
            method: 'POST',
            body: JSON.stringify({ account_name: accountName, region })
        });

        // Close modal
        const modal = bootstrap.Modal.getInstance(document.getElementById('addAccountModal'));
        if (modal) modal.hide();

        document.getElementById('addAccountForm')?.reset();

        const accounts = await loadAccounts();

        // Auto-select the new account
        const select = document.getElementById('accountSelect');
        if (select) {
            select.value = accountName;
            await selectAccount(accountName);
        }

        showToast(`Account "${accountName}" added!`, 'success');

        // If first account, signal to dismiss onboarding wizard step 1
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
 * Delete the currently selected account.
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
        await apiCall(`/api/accounts/${accountName}`, { method: 'DELETE' });
        showToast(`Account "${accountName}" deleted`, 'success');
        await loadAccounts();
        AppState.set('currentAccount', null);
        AppState.set('isAuthenticated', false);
        _updateStatusDot(false, true);

        const select = document.getElementById('accountSelect');
        if (select) select.value = '';

        document.dispatchEvent(new CustomEvent('account:cleared'));
    } catch (err) {
        showToast('Failed to delete account: ' + err.message, 'danger');
    }
}

/**
 * Redirect to Audible OAuth login for current account.
 */
function authenticateAccount(accountName) {
    const name = accountName || AppState.get('currentAccount');
    if (!name) return;
    window.location.href = `/auth/login/${name}`;
}

// ── Account Invite Modal ──

let _currentAccountForInvite = null;

async function openAccountInviteModal(accountName) {
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
    // Generate invite link button
    document.getElementById('generateAccountInviteLinkBtn')?.addEventListener('click', async function () {
        if (!_currentAccountForInvite) return;
        try {
            const data = await apiCall(`/api/accounts/${_currentAccountForInvite}/generate-invite-link`, { method: 'POST' });
            _showAccountInviteLink(data.invitation_url);
            showToast('Invitation link generated!', 'success');
        } catch (err) {
            showToast('Failed to generate link: ' + err.message, 'danger');
        }
    });

    // Copy link button
    document.getElementById('copyAccountInviteLinkBtn')?.addEventListener('click', function () {
        const val = document.getElementById('accountInviteLinkDisplay')?.value;
        if (val) copyToClipboard(val, this);
    });

    // Revoke link button
    document.getElementById('revokeAccountInviteBtn')?.addEventListener('click', async function () {
        if (!_currentAccountForInvite) return;
        if (!confirm('Revoke invitation link?')) return;
        try {
            await apiCall(`/api/accounts/${_currentAccountForInvite}/revoke-invite-link`, { method: 'POST' });
            _hideAccountInviteLink();
            showToast('Invitation link revoked', 'success');
        } catch (err) {
            showToast('Failed to revoke link: ' + err.message, 'danger');
        }
    });
}

// ── Init event listeners that are needed on all pages ──

document.addEventListener('DOMContentLoaded', function () {
    // Account selector change
    document.getElementById('accountSelect')?.addEventListener('change', function () {
        selectAccount(this.value || null);
    });

    // Add account button (opens modal)
    document.getElementById('addAccountBtn')?.addEventListener('click', function () {
        new bootstrap.Modal(document.getElementById('addAccountModal')).show();
    });

    // Submit add account form
    document.getElementById('submitAddAccount')?.addEventListener('click', function () {
        const form = document.getElementById('addAccountForm');
        if (form?.checkValidity()) {
            addAccount();
        } else {
            form?.reportValidity();
        }
    });

    // Setup account invite modal
    setupAccountInviteModal();
});
