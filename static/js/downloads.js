/**
 * downloads.js — SSE connection, download status bar (all pages), downloads page rendering
 */

let _eventSource = null;
let _reconnectTimeout = null;
let _disconnectedSince = null;
let _sseReconnectAttempt = 0;

// ── SSE Connection ──

function connectSSE() {
    // The progress stream is admin-only; signed-out, invite and member pages must not retry a 401/403.
    if (document.body.dataset.role !== 'admin') return;
    if (_eventSource) { _eventSource.close(); _eventSource = null; }

    _eventSource = new EventSource('/api/download/progress-stream');

    _eventSource.onmessage = function (event) {
        try {
            AppState.updateDownloads(JSON.parse(event.data));
        } catch (e) {
            console.warn('download progress-stream parse error', e, event.data?.slice?.(0, 200));
        }
        _disconnectedSince = null;
        _sseReconnectAttempt = 0;
        if (_reconnectTimeout) { clearTimeout(_reconnectTimeout); _reconnectTimeout = null; }
    };

    _eventSource.onerror = function () {
        _disconnectedSince = _disconnectedSince || Date.now();
        _scheduleReconnect();
    };
}

function _scheduleReconnect() {
    if (_reconnectTimeout) return;
    const delayMs = Math.min(60000, 3000 * Math.pow(2, _sseReconnectAttempt));
    _sseReconnectAttempt += 1;
    _reconnectTimeout = setTimeout(() => {
        _reconnectTimeout = null;
        if (_disconnectedSince && Date.now() - _disconnectedSince > 10000)
            showToast('Download stream reconnecting…', 'warning', 3000);
        connectSSE();
    }, delayMs);
}

// ── Shared summary helpers (used by nav pill, drawer and downloads page) ──

const DL_DONE_STATES = ['converted', 'completed', 'error'];
const DL_WAIT_STATES = ['pending', 'retrying', 'license_requested', 'license_granted'];
const DL_STEPS = ['Download', 'Decrypt', 'Convert', 'Tag', 'Audiobookshelf'];

function _dlPct(d) {
    const n = Number(d.progress_percent);
    return Number.isFinite(n) ? Math.max(0, Math.min(100, n)) : 0;
}

function _dlKind(d) {
    const state = d.state || 'pending';
    if (state === 'error') return 'failed';
    if (state === 'converted' || state === 'completed') return 'done';
    if (DL_WAIT_STATES.includes(state)) return 'waiting';
    return 'active';
}

function _dlCoverClass(key) {
    let h = 0;
    const str = String(key || '');
    for (let i = 0; i < str.length; i++) h = (h * 31 + str.charCodeAt(i)) >>> 0;
    return 'cover-c' + (h % 12);
}

function _dlCoverHtml(d, key, cls) {
    return d.cover_url
        ? `<img src="${escapeHtml(d.cover_url)}" class="${cls}" alt="">`
        : `<div class="${cls} ${_dlCoverClass(key)}" aria-hidden="true"></div>`;
}

function _dlStage(d) {
    return { downloading: 'Downloading', download_complete: 'Downloaded', decrypting: 'Decrypting',
             converting: 'Converting', pending: 'Waiting', retrying: 'Retrying',
             license_requested: 'Requesting license', license_granted: 'License granted',
             converted: 'Done', completed: 'Done', error: 'Failed' }[d.state || 'pending'] || 'Waiting';
}

function _dlStepsDone(d) {
    switch (d.state) {
        case 'download_complete': case 'decrypting': return 1;
        case 'converting': return 2;
        case 'converted': case 'completed': return DL_STEPS.length;
        default: return 0;
    }
}

function summarizeDownloads(downloads) {
    const out = { active: [], waiting: [], done: [], failed: [], speed: 0, eta: 0, progress: 0 };
    Object.entries(downloads || {}).forEach(([asin, d]) => {
        const item = { asin, ...d };
        const kind = _dlKind(item);
        out[kind].push(item);
        if (kind === 'active') {
            out.speed += Number(d.speed) || 0;
            out.eta = Math.max(out.eta, Number(d.eta) || 0);
        }
    });
    const live = out.active.concat(out.waiting);
    if (live.length) out.progress = live.reduce((t, d) => t + _dlPct(d), 0) / live.length;
    return out;
}

function _fmtWho(d) {
    return d.downloaded_by_account || '';
}

// ── Nav pill + badge ──

// ── Pause / resume / retry ──

function _syncPauseControls(paused) {
    document.querySelectorAll('[data-queue-pause]').forEach(btn => {
        btn.textContent = paused ? 'Resume' : 'Pause all';
        btn.setAttribute('aria-pressed', String(paused));
    });
}

async function toggleQueuePause() {
    const paused = !!AppState.get('paused');
    try {
        await apiCall(paused ? '/api/download/resume' : '/api/download/pause', { method: 'POST' });
        // The SSE stream confirms within a second; reflect it immediately for responsiveness.
        AppState.updateDownloads({ downloads: AppState.get('downloads'), stats: AppState.get('downloadStats'), paused: !paused });
    } catch (e) {
        showToast('Could not ' + (paused ? 'resume' : 'pause') + ' the queue: ' + e.message, 'danger');
    }
}

async function retryDownload(asin, btn) {
    if (btn) btn.disabled = true;
    try {
        await apiCall('/api/download/retry/' + encodeURIComponent(asin), { method: 'POST' });
    } catch (e) {
        showToast('Retry failed: ' + e.message, 'danger');
        if (btn) btn.disabled = false;
    }
}

document.addEventListener('click', function (e) {
    const pause = e.target.closest('[data-queue-pause]');
    if (pause) { toggleQueuePause(); return; }
    const retry = e.target.closest('[data-retry]');
    if (retry) retryDownload(retry.dataset.retry, retry);
});

document.addEventListener('appstate:downloadschange', function (e) {
    const sum = summarizeDownloads(e.detail.downloads);
    sum.paused = !!e.detail.paused;
    _syncPauseControls(sum.paused);
    _updateNavPill(sum);
    if (document.getElementById('downloadList')) _renderDownloadsPage(sum);
});

function _updateNavPill(sum) {
    const live = sum.active.length + sum.waiting.length;
    const pill = document.getElementById('queuePill');
    if (pill) {
        const fill = pill.querySelector('.queue-pill-fill');
        const label = document.getElementById('downloadNavLabel');
        pill.classList.toggle('idle', live === 0);
        if (fill) fill.style.width = Math.round(sum.progress) + '%';
        if (label) {
            label.textContent = sum.paused && live > 0
                ? `Paused · ${sum.waiting.length} waiting`
                : live === 0
                ? 'Queue empty'
                : `${sum.active.length || live} active` + (sum.speed > 0 ? ` · ${formatSpeed(sum.speed)}` : '');
        }
    }
    const badge = document.querySelector('#downloadNavPill .pill-count');
    if (badge) {
        badge.textContent = live;
        badge.hidden = live === 0;
    }
}

// ── Downloads Page Rendering ──

function _renderDownloadsPage(sum) {
    const list = document.getElementById('downloadList');
    if (!list) return;

    const set = (id, text) => { const el = document.getElementById(id); if (el) el.textContent = text; };
    set('statActive', sum.active.length);
    set('statSpeed', sum.speed > 0 ? formatSpeed(sum.speed) : '–');
    set('statEta', sum.eta > 0 ? '≈ ' + (sum.eta < 90 ? Math.max(1, Math.round(sum.eta)) + ' s' : Math.round(sum.eta / 60) + ' min') : '–');
    set('statToday', `${sum.done.length} ${sum.done.length === 1 ? 'book' : 'books'}`);

    const items = [].concat(sum.active, sum.waiting, sum.failed, sum.done);
    if (items.length === 0) {
        list.innerHTML = '<div class="downloads-empty">Nothing in the queue. Pick books in the library to start downloading.</div>';
        return;
    }
    list.querySelectorAll('.downloads-empty').forEach(el => el.remove());

    const existing = {};
    list.querySelectorAll('[data-asin]').forEach(el => { existing[el.dataset.asin] = el; });
    items.forEach((d, i) => {
        let el = existing[d.asin];
        if (el) delete existing[d.asin];
        else el = _createDownloadItemEl(d);
        _updateDownloadItemEl(el, d);
        if (list.children[i] !== el) list.insertBefore(el, list.children[i] || null);
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
    const kind = _dlKind(d);
    const pct = kind === 'done' ? 100 : _dlPct(d);
    const doneSteps = _dlStepsDone(d);
    const stepIdx = kind === 'active' || kind === 'waiting' ? doneSteps : -1;
    const steps = DL_STEPS.map((label, i) => {
        const cls = i < doneSteps ? 'is-done' : (i === stepIdx && kind === 'active' ? 'is-current' : '');
        return `<span class="${cls}">${i < doneSteps ? '✓ ' : ''}${escapeHtml(label)}</span>`;
    }).join('');

    let meta = '';
    if (kind === 'failed') meta = d.error || 'Download failed';
    else if (kind === 'waiting') meta = AppState.get('paused') ? 'Paused' : 'In queue';
    else if (kind === 'done') meta = 'In library';
    else {
        const bits = [];
        if (d.speed) bits.push(formatSpeed(d.speed));
        if (d.eta) bits.push(formatDuration(d.eta));
        else if (pct > 0) bits.push(pct.toFixed(0) + '%');
        meta = bits.join(' · ');
    }
    const who = _fmtWho(d);
    const barCls = kind === 'failed' ? 'err' : (kind === 'done' ? '' : 'orange');

    el.className = `dl-row kind-${kind}`;
    el.innerHTML = `
        ${_dlCoverHtml(d, d.asin || d.title, 'dl-cover')}
        <div class="dl-main">
            <div class="dl-title">${escapeHtml(d.title || d.asin)}</div>
            <div class="dl-sub">${escapeHtml(d.author || '')}${who ? ' · ' + escapeHtml(who) : ''}</div>
        </div>
        <div class="dl-progress">
            <div class="dl-steps">${steps}</div>
            <div class="track"><span class="fill ${barCls}" style="width:${pct}%"></span></div>
        </div>
        <div class="dl-status">
            <div class="dl-status-name">${escapeHtml(_dlStage(d))}</div>
            <div class="dl-status-meta">${escapeHtml(meta)}</div>
            ${kind === 'failed' ? `<button type="button" class="dl-retry" data-retry="${escapeHtml(d.asin)}">Retry</button>` : ''}
        </div>
    `;
}

// ── Init ──

document.addEventListener('DOMContentLoaded', function () {
    connectSSE();

    document.getElementById('clearFinishedBtn')?.addEventListener('click', async function () {
        try {
            await apiCall('/api/download/clear-completed', { method: 'POST' });
        } catch (e) {
            showToast('Failed to clear: ' + e.message, 'danger');
        }
    });
});
