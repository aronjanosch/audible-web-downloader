/**
 * onboarding.js — First-run setup wizard
 * Shown when no accounts exist. 3 steps: Add Account → Authenticate → Add Library
 */

const ONBOARDING_KEY = 'audible_onboarding_step';

let _wizardActive = false;
let _onboardingAccountName = null;

async function initOnboarding() {
    try {
        const accounts = await apiCall('/api/accounts');
        const hasAccounts = Object.keys(accounts).length > 0;

        if (hasAccounts) {
            // Check if coming back from auth step
            const step = localStorage.getItem(ONBOARDING_KEY);
            if (step === '2') {
                // Re-check if account is now authenticated
                const names = Object.keys(accounts);
                const authResult = await apiCall('/api/auth/check', {
                    method: 'POST',
                    body: JSON.stringify({ account_name: names[0] })
                });
                if (authResult.authenticated) {
                    localStorage.setItem(ONBOARDING_KEY, '3');
                    _showWizard(3);
                    _wizardActive = true;
                    return;
                }
            }
            // Normal state — don't show wizard
            _hideWizard();
            return;
        }

        // No accounts → show wizard
        _showWizard(1);
        _wizardActive = true;
    } catch (err) {
        console.error('initOnboarding failed:', err);
        _hideWizard();
    }
}

function _showWizard(step) {
    const wizard = document.getElementById('onboardingWizard');
    const libraryContent = document.getElementById('libraryContent');
    const welcomeMessage = document.getElementById('welcomeMessage');

    if (wizard) wizard.hidden = false;
    if (libraryContent) libraryContent.hidden = true;
    if (welcomeMessage) welcomeMessage.hidden = true;

    // Show the right step
    [1, 2, 3].forEach(n => {
        const el = document.getElementById(`wizardStep${n}`);
        if (el) el.hidden = n !== step;
    });

    // Update step indicator circles and lines
    [1, 2, 3].forEach(n => {
        const circle = document.getElementById(`wizardCircle${n}`);
        if (!circle) return;
        const item = circle.closest('.step-item');
        if (!item) return;
        item.classList.toggle('active', n === step);
        item.classList.toggle('done', n < step);
    });
    [1, 2].forEach(n => {
        const line = document.getElementById(`wizardLine${n}`);
        if (!line) return;
        line.classList.toggle('done', n < step);
        line.classList.toggle('active', n === step - 1);
    });

    localStorage.setItem(ONBOARDING_KEY, String(step));
}

function _hideWizard() {
    const wizard = document.getElementById('onboardingWizard');
    if (wizard) wizard.hidden = true;
    _wizardActive = false;
    localStorage.removeItem(ONBOARDING_KEY);
}

function _completeWizard() {
    _hideWizard();
    const content = document.getElementById('libraryContent');
    if (content) content.hidden = false;
    showToast('All set! Click "Load Library" to fetch your audiobooks.', 'success', 6000);
    loadAccounts();
}

// ── Step 1 → 2: Account was added ──

document.addEventListener('onboarding:accountAdded', function (e) {
    if (!_wizardActive) return;
    _onboardingAccountName = e.detail.accountName;
    localStorage.setItem(ONBOARDING_KEY, '2');
    _showWizard(2);

    // Update account name in step 2
    const nameEl = document.getElementById('wizardAccountName');
    if (nameEl) nameEl.textContent = _onboardingAccountName;
});

// ── Step 2: Authenticate button ──

document.addEventListener('DOMContentLoaded', function () {
    document.getElementById('wizardLoginBtn')?.addEventListener('click', function () {
        const name = _onboardingAccountName || document.getElementById('wizardAccountName')?.textContent;
        if (name) {
            window.location.href = `/auth/login/${name}`;
        }
    });

    document.getElementById('wizardSkipAuthBtn')?.addEventListener('click', function () {
        _showWizard(3);
    });

    // Step 3: Add library form
    document.getElementById('wizardAddLibraryForm')?.addEventListener('submit', async function (e) {
        e.preventDefault();
        const name = document.getElementById('wizardLibraryName')?.value?.trim();
        const path = document.getElementById('wizardLibraryPath')?.value?.trim();
        if (!name || !path) { showToast('Please fill in both fields', 'warning'); return; }

        const btn = this.querySelector('[type=submit]');
        const restore = btn ? setButtonLoading(btn, 'Saving…') : null;

        try {
            await apiCall('/api/libraries', {
                method: 'POST',
                body: JSON.stringify({ library_name: name, library_path: path })
            });
            await loadLibraries();
            _completeWizard();
        } catch (err) {
            showToast('Failed to add library: ' + err.message, 'danger');
        } finally {
            if (restore) restore();
        }
    });

    document.getElementById('wizardSkipLibraryBtn')?.addEventListener('click', function () {
        _completeWizard();
    });

    // Initialize
    initOnboarding();

    // Handle account:selected while wizard is active (returning from auth)
    document.addEventListener('account:selected', function () {
        if (localStorage.getItem(ONBOARDING_KEY) === '2') {
            initOnboarding();
        }
    });
});
