/**
 * queue-drawer.js — slide-over download queue, opened from the top-bar queue pill.
 * Depends on downloads.js (summarizeDownloads, helpers) and ui.js (escapeHtml).
 */
(function () {
    const root = document.getElementById('queueDrawerRoot');
    const pill = document.getElementById('queuePill');
    if (!root || !pill) return;

    root.innerHTML = `
        <div class="qd-backdrop" data-qd-close></div>
        <aside class="qd-panel" id="queueDrawer" role="dialog" aria-modal="true" aria-labelledby="qdTitle" tabindex="-1">
            <div class="qd-head">
                <h2 class="qd-title" id="qdTitle">Queue</h2>
                <div class="qd-head-actions">
                    <button type="button" class="qd-pause" data-queue-pause aria-pressed="false">Pause all</button>
                    <button type="button" class="qd-close" data-qd-close aria-label="Close queue">✕</button>
                </div>
            </div>
            <div class="qd-summary" id="qdSummary"></div>
            <div id="qdActive" class="d-flex flex-column gap-3" style="gap:20px!important"></div>
            <div id="qdWaiting"></div>
            <div id="qdDone"></div>
            <a class="qd-link" href="/downloads">Open full queue →</a>
        </aside>`;

    const panel = document.getElementById('queueDrawer');
    let lastFocus = null;

    function isOpen() { return root.classList.contains('open'); }

    function open() {
        if (isOpen()) return;
        lastFocus = document.activeElement;
        render();
        _syncPauseControls(!!AppState.get('paused'));
        root.classList.add('open');
        pill.setAttribute('aria-expanded', 'true');
        panel.focus();
    }

    function close() {
        if (!isOpen()) return;
        root.classList.remove('open');
        pill.setAttribute('aria-expanded', 'false');
        if (lastFocus && lastFocus.focus) lastFocus.focus();
    }

    function focusables() {
        return [...panel.querySelectorAll('a[href], button:not([disabled])')];
    }

    function line(cls, left, right) {
        return `<div class="qd-line ${cls}"><span>${escapeHtml(left)}</span><span>${escapeHtml(right)}</span></div>`;
    }

    function render() {
        const sum = summarizeDownloads(AppState.get('downloads'));
        const bits = [`${sum.active.length} active`, `${sum.waiting.length} waiting`];
        if (AppState.get('paused')) bits.unshift('Paused');
        if (sum.speed > 0) bits.push(formatSpeed(sum.speed));
        if (sum.eta > 0) bits.push(`about ${sum.eta < 90 ? Math.max(1, Math.round(sum.eta)) + ' s' : Math.round(sum.eta / 60) + ' min'} left`);
        document.getElementById('qdSummary').textContent = bits.join(' · ');

        document.getElementById('qdActive').innerHTML = sum.active.length ? sum.active.map(d => {
            const pct = _dlPct(d);
            const meta = [pct ? Math.round(pct) + '%' : '', d.speed ? formatSpeed(d.speed) : ''].filter(Boolean).join(' · ');
            return `<div class="qd-item">
                ${_dlCoverHtml(d, d.asin || d.title, 'qd-cover')}
                <div class="qd-item-main">
                    <div class="qd-item-title">${escapeHtml(d.title || d.asin)}</div>
                    <div class="qd-item-who">${escapeHtml(_fmtWho(d))}</div>
                    <div class="track"><span class="fill" style="width:${pct}%"></span></div>
                    <div class="qd-item-foot"><span>${escapeHtml(_dlStage(d))}</span><span>${escapeHtml(meta)}</span></div>
                </div>
            </div>`;
        }).join('') : '<div class="qd-empty">Nothing downloading right now.</div>';

        document.getElementById('qdWaiting').innerHTML = sum.waiting.length
            ? `<div class="qd-section-label">WAITING</div><div class="qd-lines" style="margin-top:16px">${
                sum.waiting.map(d => line('', d.title || d.asin, _fmtWho(d))).join('')}</div>` : '';

        const finished = sum.failed.concat(sum.done);
        document.getElementById('qdDone').innerHTML = finished.length
            ? `<div class="qd-section-label">DONE TODAY</div><div class="qd-lines" style="margin-top:16px">${
                sum.failed.map(d => line('err', d.title || d.asin, 'Failed')).join('')}${
                sum.done.map(d => line('ok', d.title || d.asin, '✓ In library')).join('')}</div>` : '';
    }

    pill.addEventListener('click', () => (isOpen() ? close() : open()));
    root.addEventListener('click', e => { if (e.target.closest('[data-qd-close]')) close(); });
    document.addEventListener('keydown', e => {
        if (!isOpen()) return;
        if (e.key === 'Escape') { e.preventDefault(); close(); return; }
        if (e.key === 'Tab') {
            const f = focusables();
            if (!f.length) return;
            const first = f[0], last = f[f.length - 1];
            if (e.shiftKey && (document.activeElement === first || document.activeElement === panel)) { e.preventDefault(); last.focus(); }
            else if (!e.shiftKey && document.activeElement === last) { e.preventDefault(); first.focus(); }
        }
    });
    document.addEventListener('appstate:downloadschange', () => { if (isOpen()) render(); });
})();
