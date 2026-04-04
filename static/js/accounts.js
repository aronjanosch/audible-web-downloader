/**
 * accounts.js — Account loading, selection, creation, deletion, auth check
 */

/**
 * Load all accounts from API and trigger unified library load if any are authenticated.
 */
async function loadAccounts() {
    try {
        const accounts = await apiCall('/api/accounts');
        AppState.set('accountData', accounts);
        document.dispatchEvent(new CustomEvent('accounts:loaded', { detail: accounts }));
        return accounts;
    } catch (err) {
        console.error('loadAccounts failed:', err);
        return {};
    }
}

/**
 * Redirect to Audible OAuth login for the given account.
 */
function authenticateAccount(accountName) {
    if (!accountName) return;
    window.location.href = `/auth/login/${accountName}`;
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
