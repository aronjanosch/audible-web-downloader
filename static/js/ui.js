/**
 * ui.js — UI utilities: toasts, loading states, helpers
 */

/**
 * Show a Bootstrap toast notification.
 * @param {string} message  HTML allowed
 * @param {'success'|'danger'|'warning'|'info'} type
 * @param {number} duration  ms, 0 = manual dismiss
 */
function showToast(message, type = 'info', duration = 5000) {
    const container = document.getElementById('toastContainer');
    if (!container) return;

    const icons = {
        success: 'fa-check-circle',
        danger: 'fa-exclamation-circle',
        warning: 'fa-exclamation-triangle',
        info: 'fa-info-circle'
    };

    const id = 'toast-' + Date.now();
    const toastEl = document.createElement('div');
    toastEl.id = id;
    toastEl.className = `toast align-items-center text-white bg-${type} border-0`;
    toastEl.setAttribute('role', 'alert');
    toastEl.setAttribute('aria-live', 'assertive');
    toastEl.setAttribute('aria-atomic', 'true');
    toastEl.innerHTML = `
        <div class="d-flex">
            <div class="toast-body d-flex align-items-center gap-2">
                <i class="fas ${icons[type] || icons.info}"></i>
                <span>${message}</span>
            </div>
            <button type="button" class="btn-close btn-close-white me-2 m-auto" data-bs-dismiss="toast" aria-label="Close"></button>
        </div>
    `;

    container.appendChild(toastEl);

    const toast = new bootstrap.Toast(toastEl, {
        autohide: duration > 0,
        delay: duration
    });
    toast.show();

    toastEl.addEventListener('hidden.bs.toast', () => toastEl.remove());
}

// Legacy compatibility aliases
function showAlert(message, type = 'info') {
    showToast(message, type === 'error' ? 'danger' : type);
}

function showBottomNotification(message, type = 'info', duration = 5000) {
    showToast(message, type === 'error' ? 'danger' : type, duration);
}

function hideBottomNotification() {} // no-op, toasts auto-dismiss

/**
 * Set a button into loading state and return a restore function.
 * @param {HTMLElement} btn
 * @param {string} loadingText
 * @returns {function} call to restore the button
 */
function setButtonLoading(btn, loadingText = 'Loading...') {
    const originalHTML = btn.innerHTML;
    const wasDisabled = btn.disabled;
    btn.disabled = true;
    btn.innerHTML = `<span class="spinner-border spinner-border-sm me-2" role="status" aria-hidden="true"></span>${loadingText}`;
    return function restore() {
        btn.disabled = wasDisabled;
        btn.innerHTML = originalHTML;
    };
}

/**
 * Copy text to clipboard and temporarily update button label.
 */
async function copyToClipboard(text, btn) {
    try {
        await navigator.clipboard.writeText(text);
        if (btn) {
            const orig = btn.innerHTML;
            btn.innerHTML = '<i class="fas fa-check"></i> Copied!';
            setTimeout(() => { btn.innerHTML = orig; }, 2000);
        }
        return true;
    } catch {
        return false;
    }
}

/**
 * Format bytes to human-readable string.
 */
function formatBytes(bytes) {
    if (!bytes || bytes === 0) return '0 B';
    const k = 1024;
    const sizes = ['B', 'KB', 'MB', 'GB'];
    const i = Math.floor(Math.log(bytes) / Math.log(k));
    return parseFloat((bytes / Math.pow(k, i)).toFixed(1)) + ' ' + sizes[i];
}

/**
 * Format seconds to human-readable duration.
 */
function formatDuration(seconds) {
    if (!seconds || seconds <= 0) return '-';
    const m = Math.floor(seconds / 60);
    const s = Math.floor(seconds % 60);
    if (m > 60) {
        const h = Math.floor(m / 60);
        return `${h}h ${m % 60}m`;
    }
    return m > 0 ? `${m}m ${s}s` : `${s}s`;
}

/**
 * Format minutes to "Xh Ym" string.
 */
function formatMinutes(mins) {
    if (!mins) return '';
    const h = Math.floor(mins / 60);
    const m = mins % 60;
    return h > 0 ? `${h}h ${m}m` : `${m}m`;
}

/**
 * Format download speed in bytes/sec to human string.
 */
function formatSpeed(bytesPerSec) {
    if (!bytesPerSec || bytesPerSec <= 0) return '';
    return formatBytes(bytesPerSec) + '/s';
}
