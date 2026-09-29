/**
 * importer.js — M4B file import workflow: scan → match → execute
 * Loaded on the /import page only.
 */

let _scannedFiles = [];
let _matchedFiles = [];
let _progressInterval = null;

// ── Step Navigation ──

function _showStep(n) {
    [1, 2, 3].forEach(i => {
        const el = document.getElementById(`importStep${i}`);
        if (el) el.hidden = i !== n;
    });
    const bar = document.getElementById('importBar');
    if (bar && n !== 2) bar.hidden = true;
    _updateStepIndicator(n);
}

function _updateStepIndicator(activeStep) {
    [1, 2, 3].forEach(i => {
        const item = document.getElementById(`stepItem${i}`);
        if (!item) return;
        item.classList.toggle('active', i === activeStep);
        item.classList.toggle('done', i < activeStep);
        const circle = item.querySelector('.step-circle');
        if (circle) circle.textContent = i < activeStep ? '✓' : String(i);
    });
    const line1 = document.getElementById('stepLine1');
    const line2 = document.getElementById('stepLine2');
    if (line1) line1.className = `step-line ${activeStep > 1 ? 'done' : ''}`;
    if (line2) line2.className = `step-line ${activeStep > 2 ? 'done' : ''}`;
}

// ── Step 1: Scan ──

async function scanDirectory() {
    const sourcePath = document.getElementById('sourcePath')?.value?.trim();
    const targetLibrary = document.getElementById('targetLibrary')?.value;
    const accountName = AppState.get('currentAccount');

    if (!sourcePath) { showToast('Please enter a source directory path', 'warning'); return; }
    if (!targetLibrary) { showToast('Please select a target library', 'warning'); return; }

    const btn = document.getElementById('scanDirectoryBtn');
    const restore = setButtonLoading(btn, 'Scanning…');

    try {
        const result = await apiCall('/api/importer/scan', {
            method: 'POST',
            body: JSON.stringify({
                source_path: sourcePath,
                library_path: targetLibrary,
                account_name: accountName
            })
        });

        _scannedFiles = result.files || [];
        _renderScanResults(_scannedFiles, result.count, result.total_size);
        document.getElementById('scanResults')?.removeAttribute('hidden');

    } catch (err) {
        showToast('Scan failed: ' + err.message, 'danger');
    } finally {
        restore();
    }
}

function _renderScanResults(files, count, totalSize) {
    const tbody = document.getElementById('scannedFilesTable');
    if (!tbody) return;

    document.getElementById('fileCount').textContent = count || files.length;
    document.getElementById('totalSize').textContent = _formatSize(totalSize);

    tbody.innerHTML = '';
    files.forEach((f, idx) => {
        const row = document.createElement('div');
        row.className = 'imp-row scan';
        row.innerHTML = `
            <input type="checkbox" class="imp-check scan-file-cb" data-idx="${idx}" checked aria-label="Select ${escapeHtml(_basename(f.file_path))}">
            <div class="imp-file" title="${escapeHtml(f.file_path)}">${escapeHtml(_basename(f.file_path))}</div>
            <div>${escapeHtml(f.title || '—')}</div>
            <div class="dim">${escapeHtml(f.author || '—')}</div>
            <div class="dim">${_formatSize(f.file_size)}</div>
        `;
        tbody.appendChild(row);
    });

    _updateMatchCount();

    tbody.querySelectorAll('.scan-file-cb').forEach(cb => {
        cb.addEventListener('change', _updateMatchCount);
    });
}

function _updateMatchCount() {
    const count = document.querySelectorAll('.scan-file-cb:checked').length;
    const el = document.getElementById('selectedForMatchCount');
    if (el) el.textContent = count;
}

function _getSelectedFiles() {
    const checked = document.querySelectorAll('.scan-file-cb:checked');
    return Array.from(checked).map(cb => _scannedFiles[parseInt(cb.dataset.idx)]);
}

// ── Step 2: Match ──

async function matchFiles() {
    const selected = _getSelectedFiles();
    if (selected.length === 0) { showToast('Please select files to match', 'warning'); return; }

    const targetLibrary = document.getElementById('targetLibrary')?.value;
    const accountName = AppState.get('currentAccount');

    _showStep(2);
    document.getElementById('matchingProgress')?.removeAttribute('hidden');
    document.getElementById('matchResults')?.setAttribute('hidden', '');

    try {
        const result = await apiCall('/api/importer/match', {
            method: 'POST',
            body: JSON.stringify({
                files: selected,
                library_path: targetLibrary,
                account_name: accountName
            })
        });

        _matchedFiles = result.matched_files || [];
        document.getElementById('matchingProgress')?.setAttribute('hidden', '');
        document.getElementById('matchResults')?.removeAttribute('hidden');
        _renderMatchResults(_matchedFiles, result.stats);

    } catch (err) {
        showToast('Matching failed: ' + err.message, 'danger');
        _showStep(1);
    }
}

function _coverClass(text) {
    let h = 0;
    for (const ch of String(text || '')) h = (h * 31 + ch.charCodeAt(0)) >>> 0;
    return `cover-c${h % 12}`;
}

function _renderMatchResults(files, stats) {
    document.getElementById('matchedCount').textContent  = stats?.matched  || 0;
    document.getElementById('uncertainCount').textContent = stats?.uncertain || 0;
    document.getElementById('duplicatesCount').textContent = stats?.duplicates || 0;
    document.getElementById('notFoundCount').textContent  = stats?.not_found  || 0;
    const dupPill = document.getElementById('dupPill');
    if (dupPill) dupPill.hidden = !(stats?.duplicates > 0);

    const n = files.length;
    document.getElementById('sumFileCount').textContent = `${n} file${n === 1 ? '' : 's'}`;
    document.getElementById('sumSource').textContent = document.getElementById('sourcePath')?.value?.trim() || '';
    document.getElementById('sumLibrary').textContent = document.getElementById('targetLibrary')?.value || '';

    const container = document.getElementById('matchedFilesList');
    if (!container) return;
    container.innerHTML = '';

    files.forEach((item, idx) => {
        item.chosen = _bestProduct(item);
        const row = _buildMatchRow(item, idx);
        container.appendChild(row);
        container.appendChild(_buildPicker(idx));
    });

    const bar = document.getElementById('importBar');
    if (bar) bar.hidden = false;

    _updateImportCount();
}

/** The catalog product currently chosen for a file: auto-selected match, else best candidate. */
function _bestProduct(item) {
    const result = item.match_result || {};
    return result.selected_match || (result.matches || [])[0] || null;
}

function _authorNames(product) {
    const a = product && product.authors;
    if (Array.isArray(a)) return a.map(x => (x && x.name) || x).filter(Boolean).join(', ');
    return a || '';
}

function _confidenceFor(item) {
    if (item.manual) return 1;
    const result = item.match_result || {};
    const product = item.chosen;
    if (product && result.match_confidences && product.asin in result.match_confidences) {
        return result.match_confidences[product.asin];
    }
    return result.confidence || 0;
}

function _buildMatchRow(item, idx, keepChecked) {
    const product = item.chosen;
    const confidence = product ? _confidenceFor(item) : 0;
    const isDuplicate = !item.manual && !!item.duplicate_status;
    const isNotFound = !product;
    const confident = !isDuplicate && !isNotFound && confidence >= 0.8;
    const checked = keepChecked !== undefined ? keepChecked : (item.selected !== false && !isDuplicate && confident);
    const filePath = item.file_info?.file_path || '';
    const fileSize = item.file_info?.file_size;

    const row = document.createElement('div');
    row.className = 'imp-row match';
    row.dataset.idx = idx;
    const title = isNotFound ? 'No match found' : (product.title || '—');
    const author = isNotFound ? 'Search Audible' : _authorNames(product);
    const confClass = isNotFound || isDuplicate ? 'none' : confidence >= 0.8 ? '' : 'mid';
    const confText = isNotFound ? '–' : isDuplicate ? 'Duplicate' : Math.round(confidence * 100) + '%';
    const actLabel = isNotFound ? 'Search' : isDuplicate ? 'Skip' : confident ? 'Change' : 'Confirm';
    row.innerHTML = `
        <input type="checkbox" class="imp-check match-file-cb" data-idx="${idx}" ${checked ? 'checked' : ''} ${isNotFound ? 'disabled' : ''} aria-label="Import ${escapeHtml(_basename(filePath))}">
        <div><div class="imp-file">${escapeHtml(_basename(filePath))}</div><div class="imp-sub">${escapeHtml(_formatSize(fileSize))}</div></div>
        <span class="imp-arrow" aria-hidden="true">→</span>
        <div class="imp-match">
            <div class="imp-cover ${isNotFound ? 'none' : _coverClass(title)}"></div>
            <div><div class="imp-match-title">${escapeHtml(title)}</div><div class="imp-sub">${escapeHtml(author)}</div></div>
        </div>
        <div class="imp-conf ${confClass}">${escapeHtml(confText)}</div>
        <button type="button" class="imp-act" data-act="${actLabel.toLowerCase()}">${actLabel}</button>
    `;
    row.querySelector('.match-file-cb').addEventListener('change', _updateImportCount);
    row.querySelector('.imp-act').addEventListener('click', () => _onRowAction(row, idx));
    return row;
}

function _onRowAction(row, idx) {
    const act = row.querySelector('.imp-act').dataset.act;
    const cb = row.querySelector('.match-file-cb');
    if (act === 'confirm') {
        cb.checked = true;
        _refreshRow(idx, true);
    } else if (act === 'skip') {
        cb.checked = false;
        _updateImportCount();
    } else {
        // 'change' and 'search' both open the picker: candidates + free-text Audible search.
        _togglePicker(idx);
    }
    _updateImportCount();
}

function _refreshRow(idx, checked) {
    const old = document.querySelector(`#matchedFilesList .imp-row[data-idx="${idx}"]`);
    if (!old) return;
    const item = _matchedFiles[idx];
    const wasChecked = checked !== undefined ? checked : old.querySelector('.match-file-cb').checked;
    const fresh = _buildMatchRow(item, idx, wasChecked);
    old.replaceWith(fresh);
    _updateImportCount();
}

function _buildPicker(idx) {
    const item = _matchedFiles[idx];
    const box = document.createElement('div');
    box.className = 'imp-picker';
    box.dataset.idx = idx;
    box.hidden = true;
    const stem = _basename(item.file_info?.file_path || '').replace(/\.m4b$/i, '').replace(/[_\-.]+/g, ' ').trim();
    box.innerHTML = `
        <form class="imp-picker-form">
            <input type="search" class="form-control form-control-sm" aria-label="Search Audible" value="${escapeHtml(stem)}">
            <button type="submit" class="btn btn-sm btn-primary">Search Audible</button>
        </form>
        <div class="imp-picker-results" role="list"></div>`;
    box.querySelector('form').addEventListener('submit', e => {
        e.preventDefault();
        _runPickerSearch(idx, box);
    });
    return box;
}

function _togglePicker(idx) {
    const box = document.querySelector(`#matchedFilesList .imp-picker[data-idx="${idx}"]`);
    if (!box) return;
    box.hidden = !box.hidden;
    if (box.hidden) return;
    const item = _matchedFiles[idx];
    const results = box.querySelector('.imp-picker-results');
    if (!results.children.length) {
        const candidates = (item.match_result?.matches || []).slice(0, 5);
        if (candidates.length) _renderPickerResults(idx, box, candidates);
        else _runPickerSearch(idx, box);
    }
    box.querySelector('input').focus();
}

async function _runPickerSearch(idx, box) {
    const query = box.querySelector('input').value.trim();
    const results = box.querySelector('.imp-picker-results');
    if (!query) return;
    const account = AppState.get('currentAccount');
    const region = ((AppState.get('accountData') || {})[account] || {}).region || 'us';
    results.textContent = 'Searching…';
    try {
        const data = await apiCall('/api/importer/search-manual', {
            method: 'POST',
            body: JSON.stringify({
                file_path: _matchedFiles[idx].file_info?.file_path,
                search_query: query,
                account_name: account,
                region,
                library_path: document.getElementById('targetLibrary')?.value
            })
        });
        _renderPickerResults(idx, box, data.results || []);
    } catch (err) {
        results.textContent = 'Search failed: ' + err.message;
    }
}

function _renderPickerResults(idx, box, products) {
    const results = box.querySelector('.imp-picker-results');
    results.replaceChildren();
    if (!products.length) { results.textContent = 'No results. Try a different title or author.'; return; }
    products.forEach(product => {
        const line = document.createElement('div');
        line.className = 'imp-picker-item';
        line.setAttribute('role', 'listitem');
        const info = document.createElement('div');
        const t = document.createElement('div');
        t.className = 'imp-match-title';
        t.textContent = product.title || '—';
        const a = document.createElement('div');
        a.className = 'imp-sub';
        a.textContent = [_authorNames(product), product.release_date ? String(product.release_date).slice(0, 4) : ''].filter(Boolean).join(' · ');
        info.append(t, a);
        const use = document.createElement('button');
        use.type = 'button';
        use.className = 'imp-act';
        use.textContent = 'Use this';
        use.addEventListener('click', () => {
            const item = _matchedFiles[idx];
            item.chosen = product;
            item.manual = true;
            box.hidden = true;
            _refreshRow(idx, true);
        });
        line.append(info, use);
        results.append(line);
    });
}

function _updateImportCount() {
    const count = document.querySelectorAll('.match-file-cb:checked').length;
    const el = document.getElementById('selectedForImportCount');
    if (el) el.textContent = count;
}

// ── Step 3: Execute Import ──

async function executeImport() {
    const checkedBoxes = document.querySelectorAll('.match-file-cb:checked');
    if (checkedBoxes.length === 0) { showToast('Please select books to import', 'warning'); return; }

    const imports = Array.from(checkedBoxes).map(cb => {
        const idx = parseInt(cb.dataset.idx);
        const item = _matchedFiles[idx];
        return {
            file_path: item.file_info.file_path,
            audible_product: item.chosen
        };
    });

    const targetLibrary = document.getElementById('targetLibrary')?.value;
    const accountName = AppState.get('currentAccount');

    const btn = document.getElementById('startImportBtn');
    const restore = setButtonLoading(btn, 'Starting…');

    try {
        await apiCall('/api/importer/execute', {
            method: 'POST',
            body: JSON.stringify({
                imports,
                library_path: targetLibrary,
                account_name: accountName
            })
        });

        _showStep(3);
        _startImportProgressPolling();

    } catch (err) {
        showToast('Import failed: ' + err.message, 'danger');
    } finally {
        restore();
    }
}

function _startImportProgressPolling() {
    if (_progressInterval) clearInterval(_progressInterval);
    _progressInterval = setInterval(_pollImportProgress, 1500);
    _pollImportProgress();
}

async function _pollImportProgress() {
    try {
        const result = await apiCall('/api/importer/progress');
        const stats = result.statistics || {};
        const imports = result.imports || {};

        const activeEl     = document.getElementById('importStatActive');
        const completedEl  = document.getElementById('importStatCompleted');
        const failedEl2    = document.getElementById('importStatFailed');
        if (activeEl)    activeEl.textContent    = stats.active    || 0;
        if (completedEl) completedEl.textContent = stats.completed || 0;
        if (failedEl2)   failedEl2.textContent   = stats.failed    || 0;

        const total = stats.total_imports || 0;
        const done  = (stats.completed || 0) + (stats.failed || 0);
        const pct   = total > 0 ? Math.round((done / total) * 100) : 0;

        const bar = document.getElementById('importOverallBar');
        if (bar) {
            bar.style.width = pct + '%';
            const track = document.getElementById('importOverallTrack');
            if (track) track.setAttribute('aria-valuenow', pct);
        }

        _renderImportItems(imports);

        if (stats.batch_complete) {
            clearInterval(_progressInterval);
            _progressInterval = null;
            document.getElementById('importCompleteMsg')?.removeAttribute('hidden');
        }
    } catch (err) {
        console.error('Import progress poll failed:', err);
    }
}

function _renderImportItems(imports) {
    const container = document.getElementById('importProgressList');
    if (!container) return;

    container.innerHTML = '';
    const pillFor = { pending: 'pill-queued', importing: 'pill-active', organizing: 'pill-active', completed: 'pill-done', error: 'pill-err', skipped: 'pill' };
    Object.entries(imports).forEach(([key, item]) => {
        const el = document.createElement('div');
        const safeState = ['pending', 'importing', 'organizing', 'completed', 'error', 'skipped'].includes(item.state) ? item.state : 'pending';
        el.className = `imp-item state-${safeState}`;
        el.innerHTML = `
            <div>
                <div class="imp-item-title">${escapeHtml(item.title || key)}</div>
                <div class="imp-item-sub">${escapeHtml(_stateLabel(item.state))}</div>
                ${item.error ? `<div class="imp-item-err">${escapeHtml(item.error)}</div>` : ''}
            </div>
            <span class="pill ${pillFor[safeState]}">${escapeHtml(_stateLabel(item.state))}</span>
        `;
        container.appendChild(el);
    });
}

function _stateLabel(state) {
    const map = {
        pending: 'Pending', importing: 'Importing', organizing: 'Organizing',
        completed: 'Completed', error: 'Error', skipped: 'Skipped'
    };
    return map[state] || state;
}

// ── Helpers ──

function _basename(path) {
    return path?.split('/').pop() || path || '';
}

function _formatSize(bytes) {
    if (!bytes) return '—';
    if (bytes < 1024) return bytes + ' B';
    if (bytes < 1048576) return (bytes / 1024).toFixed(1) + ' KB';
    return (bytes / 1048576).toFixed(1) + ' MB';
}

// ── Libraries for target selector ──

document.addEventListener('libraries:updated', function (e) {
    const select = document.getElementById('targetLibrary');
    if (!select) return;
    const current = select.value;
    select.innerHTML = '<option value="">Select library…</option>';
    Object.entries(e.detail).forEach(([name]) => {
        const opt = document.createElement('option');
        opt.value = name;
        opt.textContent = name;
        select.appendChild(opt);
    });
    if (current) select.value = current;
});

// ── DOMContentLoaded ──

document.addEventListener('DOMContentLoaded', function () {
    _showStep(1);

    document.getElementById('scanDirectoryBtn')?.addEventListener('click', scanDirectory);

    document.getElementById('selectAllScannedBtn')?.addEventListener('click', () => {
        document.querySelectorAll('.scan-file-cb').forEach(cb => { cb.checked = true; });
        _updateMatchCount();
    });

    document.getElementById('deselectAllScannedBtn')?.addEventListener('click', () => {
        document.querySelectorAll('.scan-file-cb').forEach(cb => { cb.checked = false; });
        _updateMatchCount();
    });

    document.getElementById('matchFilesBtn')?.addEventListener('click', matchFiles);

    document.getElementById('backToStep1Btn')?.addEventListener('click', () => _showStep(1));

    document.getElementById('selectAllMatchedBtn')?.addEventListener('click', () => {
        document.querySelectorAll('.match-file-cb').forEach(cb => { cb.checked = true; });
        _updateImportCount();
    });

    document.getElementById('deselectAllBtn')?.addEventListener('click', () => {
        document.querySelectorAll('.match-file-cb').forEach(cb => { cb.checked = false; });
        _updateImportCount();
    });

    document.getElementById('startImportBtn')?.addEventListener('click', executeImport);

    document.getElementById('backToStep2Btn')?.addEventListener('click', () => _showStep(2));
});
