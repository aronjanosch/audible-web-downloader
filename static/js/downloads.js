/**
 * downloads.js — SSE connection, download status bar (all pages), downloads page rendering
 */

let _eventSource = null;
let _reconnectTimeout = null;
let _disconnectedSince = null;

// ── SSE Connection ──

function connectSSE() {
    if (_eventSource) { _eventSource.close(); _eventSource = null; }

    _eventSource = new EventSource('/api/download/progress-stream');

    _eventSource.onmessage = function (event) {
        try { AppState.updateDownloads(JSON.parse(event.data)); } catch (e) {}
        _disconnectedSince = null;
        if (_reconnectTimeout) { clearTimeout(_reconnectTimeout); _reconnectTimeout = null; }
    };

    _eventSource.onerror = function () {
        _disconnectedSince = _disconnectedSince || Date.now();
        _scheduleReconnect();
    };
}

function _scheduleReconnect() {
    if (_reconnectTimeout) return;
    _reconnectTimeout = setTimeout(() => {
        _reconnectTimeout = null;
        if (_disconnectedSince && Date.now() - _disconnectedSince > 10000)
            showToast('Download stream reconnecting…', 'warning', 3000);
        connectSSE();
    }, 3000);
}

// ── Download Status Bar ──

document.addEventListener('appstate:downloadschange', function (e) {
    _updateDownloadBar(e.detail.downloads, e.detail.stats);
    if (document.getElementById('inProgressList')) {
        _renderDownloadsPage(e.detail.downloads);
    }
    _updateNavPill(e.detail.stats);
});

function _updateDownloadBar(downloads, stats) {
    const bar = document.getElementById('downloadStatusBar');
    if (!bar) return;

    const active = stats?.active || 0;
    const queued = stats?.queued || 0;
    const completed = stats?.completed || 0;
    const hasActivity = (active + queued) > 0 || completed > 0;

    if (hasActivity) {
        document.documentElement.style.setProperty('--download-bar-height', '44px');
        bar.classList.add('visible');

        let totalSpeed = 0, maxEta = 0;
        Object.values(downloads).forEach(d => {
            if (d.state === 'downloading') {
                totalSpeed += d.speed || 0;
                if (d.eta > maxEta) maxEta = d.eta;
            }
        });

        bar.querySelector('.bar-active').textContent = active;
        bar.querySelector('.bar-queued').textContent = queued;
        bar.querySelector('.bar-completed').textContent = completed;

        const speedEl = bar.querySelector('.bar-speed');
        if (speedEl) speedEl.textContent = totalSpeed > 0 ? formatSpeed(totalSpeed) : '';
        const etaEl = bar.querySelector('.bar-eta');
        if (etaEl) etaEl.textContent = maxEta > 0 ? 'ETA ' + formatDuration(maxEta) : '';
    } else {
        document.documentElement.style.setProperty('--download-bar-height', '0px');
        bar.classList.remove('visible');
    }
}

function _updateNavPill(stats) {
    const pill = document.getElementById('downloadNavPill');
    if (!pill) return;
    const total = (stats?.active || 0) + (stats?.queued || 0);
    const countEl = pill.querySelector('.pill-count');
    if (total > 0) {
        pill.classList.add('active');
        if (countEl) { countEl.textContent = total; countEl.style.display = 'inline'; }
    } else {
        pill.classList.remove('active');
        if (countEl) countEl.style.display = 'none';
    }
}

// ── Downloads Page Rendering ──

function _renderDownloadsPage(downloads) {
    const inProgressEl = document.getElementById('inProgressList');
    const doneEl = document.getElementById('doneList');
    if (!inProgressEl) return;

    const inProgress = [], done = [];

    Object.entries(downloads).forEach(([asin, d]) => {
        const state = d.state || 'pending';
        if (['converted', 'completed', 'error'].includes(state)) {
            done.push({ asin, ...d });
        } else {
            inProgress.push({ asin, ...d });
        }
    });

    const ipCount = document.getElementById('inProgressCount');
    const dCount = document.getElementById('doneCount');
    if (ipCount) ipCount.textContent = inProgress.length;
    if (dCount) dCount.textContent = done.length;

    _renderSection(inProgressEl, inProgress);
    _renderSection(doneEl, done);
}

function _renderSection(container, items) {
    if (!container) return;

    if (items.length === 0) {
        container.innerHTML = '<div class="downloads-empty">Nothing here yet</div>';
        return;
    }

    // Keyed update — only re-render changed items
    const existing = {};
    container.querySelectorAll('[data-asin]').forEach(el => { existing[el.dataset.asin] = el; });

    items.forEach(d => {
        if (existing[d.asin]) {
            _updateDownloadItemEl(existing[d.asin], d);
            delete existing[d.asin];
        } else {
            container.appendChild(_createDownloadItemEl(d));
        }
    });

    Object.values(existing).forEach(el => el.remove());
}

function _createDownloadItemEl(d) {
    const el = document.createElement('div');
    el.dataset.asin = d.asin;
    _updateDownloadItemEl(el, d);
    return el;
}

function _updateDownloadItemEl(el, d) {
    const state = d.state || 'pending';
    const pct = d.progress_percent || 0;
    const isDone = ['converted', 'completed', 'error'].includes(state);

    const stateLabel = {
        pending: 'Pending', retrying: 'Retrying',
        license_requested: 'License', license_granted: 'License OK',
        downloading: 'Downloading', download_complete: 'Downloaded',
        decrypting: 'Decrypting', converting: 'Converting',
        converted: 'Done', completed: 'Done', error: 'Error'
    }[state] || state;

    el.className = `download-item state-${state}`;
    el.innerHTML = `
        <div class="download-item-inner">
            ${d.cover_url
                ? `<img src="${d.cover_url}" class="download-cover" alt="">`
                : `<div class="download-cover-placeholder"><i class="fas fa-headphones"></i></div>`}
            <div class="download-info">
                <div class="d-flex justify-content-between align-items-start mb-1">
                    <div class="download-title flex-grow-1 me-2">${d.title || d.asin}</div>
                    <span class="state-badge state-${state}">${stateLabel}</span>
                </div>
                ${d.author ? `<div class="download-author">${d.author}</div>` : ''}
                ${!isDone ? `
                <div class="download-progress-bar-track">
                    <div class="download-progress-bar-fill" style="width:${pct}%"></div>
                </div>
                <div class="download-stats">
                    ${pct > 0 ? `<span class="download-stat">${pct.toFixed(1)}%</span>` : ''}
                    ${d.speed ? `<span class="download-stat">${formatSpeed(d.speed)}</span>` : ''}
                    ${d.eta ? `<span class="download-stat">ETA ${formatDuration(d.eta)}</span>` : ''}
                </div>` : ''}
                ${d.error ? `<div class="download-error"><i class="fas fa-exclamation-triangle me-1"></i>${d.error}</div>` : ''}
            </div>
        </div>
    `;
}

// ── Init ──

document.addEventListener('DOMContentLoaded', function () {
    connectSSE();

    document.getElementById('clearDoneBtn')?.addEventListener('click', async function () {
        try {
            await apiCall('/api/download/clear-completed', { method: 'POST' });
        } catch (e) {
            showToast('Failed to clear: ' + e.message, 'danger');
        }
    });
});
