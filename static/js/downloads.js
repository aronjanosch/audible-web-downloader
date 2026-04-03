/**
 * downloads.js — SSE connection, download status bar (all pages), downloads page rendering
 */

let _eventSource = null;
let _reconnectTimeout = null;
let _disconnectedSince = null;

// ── SSE Connection ──

function connectSSE() {
    if (_eventSource) {
        _eventSource.close();
        _eventSource = null;
    }

    _eventSource = new EventSource('/api/download/progress-stream');

    _eventSource.onmessage = function (event) {
        try {
            const data = JSON.parse(event.data);
            AppState.updateDownloads(data);
        } catch (e) {
            console.error('SSE parse error:', e);
        }
        _disconnectedSince = null;
        if (_reconnectTimeout) {
            clearTimeout(_reconnectTimeout);
            _reconnectTimeout = null;
        }
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
        // Only show toast if disconnected for > 10s
        if (_disconnectedSince && Date.now() - _disconnectedSince > 10000) {
            showToast('Download stream reconnecting…', 'warning', 3000);
        }
        connectSSE();
    }, 3000);
}

// ── Download Status Bar ──

document.addEventListener('appstate:downloadschange', function (e) {
    _updateDownloadBar(e.detail.downloads, e.detail.stats);
    if (document.getElementById('activeDownloads')) {
        _renderDownloadsPage(e.detail.downloads, e.detail.stats);
    }
    _updateNavPill(e.detail.stats);
});

function _updateDownloadBar(downloads, stats) {
    const bar = document.getElementById('downloadStatusBar');
    if (!bar) return;

    const active = stats?.active || 0;
    const queued = stats?.queued || 0;
    const completed = stats?.completed || 0;
    const failed = stats?.failed || 0;
    const hasActivity = (active + queued) > 0;

    if (hasActivity) {
        // Show bar
        document.documentElement.style.setProperty('--download-bar-height', '44px');
        bar.classList.add('visible');

        // Calculate aggregate speed and ETA from active downloads
        let totalSpeed = 0, maxEta = 0;
        Object.values(downloads).forEach(d => {
            if (d.state === 'downloading' || d.state === 'converting') {
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

    } else if ((completed + failed) > 0) {
        // Show briefly for completion state
        document.documentElement.style.setProperty('--download-bar-height', '44px');
        bar.classList.add('visible');
        bar.querySelector('.bar-active').textContent = active;
        bar.querySelector('.bar-queued').textContent = queued;
        bar.querySelector('.bar-completed').textContent = completed;
    } else {
        // Hide bar
        document.documentElement.style.setProperty('--download-bar-height', '0px');
        bar.classList.remove('visible');
    }
}

function _updateNavPill(stats) {
    const pill = document.getElementById('downloadNavPill');
    if (!pill) return;

    const active = stats?.active || 0;
    const queued = stats?.queued || 0;
    const total = active + queued;

    const countEl = pill.querySelector('.pill-count');

    if (total > 0) {
        pill.classList.add('active');
        if (countEl) {
            countEl.textContent = total;
            countEl.style.display = 'inline';
        }
    } else {
        pill.classList.remove('active');
        if (countEl) countEl.style.display = 'none';
    }
}

// ── Downloads Page Rendering ──

function _renderDownloadsPage(downloads, stats) {
    const activeEl = document.getElementById('activeDownloads');
    const queuedEl = document.getElementById('queuedDownloads');
    const completedEl = document.getElementById('completedDownloads');
    const failedEl = document.getElementById('failedDownloads');

    if (!activeEl) return;

    const groups = { active: [], queued: [], completed: [], failed: [] };

    Object.entries(downloads).forEach(([asin, d]) => {
        const state = d.state || 'pending';
        if (['completed', 'converted'].includes(state)) {
            groups.completed.push({ asin, ...d });
        } else if (state === 'error') {
            groups.failed.push({ asin, ...d });
        } else if (state === 'pending') {
            groups.queued.push({ asin, ...d });
        } else {
            groups.active.push({ asin, ...d });
        }
    });

    // Update counts
    ['active', 'queued', 'completed', 'failed'].forEach(g => {
        const el = document.getElementById(g + 'Count');
        if (el) el.textContent = groups[g].length;
    });

    // Update stat cards
    document.getElementById('statActive')    && (document.getElementById('statActive').textContent = groups.active.length);
    document.getElementById('statQueued')    && (document.getElementById('statQueued').textContent = groups.queued.length);
    document.getElementById('statCompleted') && (document.getElementById('statCompleted').textContent = groups.completed.length);
    document.getElementById('statFailed')    && (document.getElementById('statFailed').textContent = groups.failed.length);

    // Update overall progress
    const total = Object.keys(downloads).length;
    const done = groups.completed.length;
    const pct = total > 0 ? Math.round((done / total) * 100) : 0;
    const overallBar = document.getElementById('overallProgressBar');
    if (overallBar) {
        overallBar.style.width = pct + '%';
        overallBar.setAttribute('aria-valuenow', pct);
    }
    const overallText = document.getElementById('overallProgressText');
    if (overallText) overallText.textContent = `${done} / ${total} books`;

    // Render each section
    _renderSection(activeEl, groups.active, false);
    _renderSection(queuedEl, groups.queued, false);
    _renderSection(completedEl, groups.completed, true);
    _renderSection(failedEl, groups.failed, false);
}

function _renderSection(container, items, isCompleted) {
    if (!container) return;

    if (items.length === 0) {
        container.innerHTML = `
            <div class="downloads-empty py-3">
                <i class="fas fa-inbox"></i>
                <p class="mb-0 small">None</p>
            </div>`;
        return;
    }

    // Only re-render items that changed (keyed by ASIN)
    const existingItems = {};
    container.querySelectorAll('[data-asin]').forEach(el => {
        existingItems[el.dataset.asin] = el;
    });

    items.forEach(d => {
        const existing = existingItems[d.asin];
        if (existing) {
            _updateDownloadItemEl(existing, d);
            delete existingItems[d.asin];
        } else {
            const newEl = _createDownloadItemEl(d);
            container.appendChild(newEl);
        }
    });

    // Remove stale items
    Object.values(existingItems).forEach(el => el.remove());
}

function _stateLabel(state) {
    const labels = {
        pending: 'Pending',
        license_requested: 'License',
        license_granted: 'License OK',
        downloading: 'Downloading',
        download_complete: 'Downloaded',
        decrypting: 'Decrypting',
        converting: 'Converting',
        converted: 'Completed',
        completed: 'Completed',
        error: 'Error',
        retrying: 'Retrying'
    };
    return labels[state] || state;
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

    el.className = `download-item state-${state}`;
    el.innerHTML = `
        <div class="download-item-inner">
            ${d.cover_url
                ? `<img src="${d.cover_url}" class="download-cover" alt="">`
                : `<div class="download-cover-placeholder"><i class="fas fa-headphones"></i></div>`}
            <div class="download-info">
                <div class="d-flex justify-content-between align-items-start mb-1">
                    <div class="download-title flex-grow-1 me-2">${d.title || d.asin}</div>
                    <span class="state-badge state-${state} flex-shrink-0">${_stateLabel(state)}</span>
                </div>
                ${d.author ? `<div class="download-author">${d.author}</div>` : ''}
                <div class="download-progress-wrap">
                    <div class="download-progress-bar-track">
                        <div class="download-progress-bar-fill" style="width: ${pct}%"></div>
                    </div>
                </div>
                <div class="download-stats">
                    ${pct > 0 ? `<span class="download-stat"><i class="fas fa-percent"></i>${pct.toFixed(1)}%</span>` : ''}
                    ${d.downloaded_bytes ? `<span class="download-stat"><i class="fas fa-hdd"></i>${formatBytes(d.downloaded_bytes)}${d.total_bytes ? ' / ' + formatBytes(d.total_bytes) : ''}</span>` : ''}
                    ${d.speed ? `<span class="download-stat"><i class="fas fa-tachometer-alt"></i>${formatSpeed(d.speed)}</span>` : ''}
                    ${d.eta ? `<span class="download-stat"><i class="fas fa-clock"></i>ETA ${formatDuration(d.eta)}</span>` : ''}
                </div>
                ${d.error ? `<div class="download-error"><i class="fas fa-exclamation-triangle me-1"></i>${d.error}</div>` : ''}
            </div>
        </div>
    `;
}

// ── Init ──

document.addEventListener('DOMContentLoaded', function () {
    connectSSE();
});
