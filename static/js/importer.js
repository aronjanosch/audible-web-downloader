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
    _updateStepIndicator(n);
}

function _updateStepIndicator(activeStep) {
    [1, 2, 3].forEach(i => {
        const item = document.getElementById(`stepItem${i}`);
        if (!item) return;
        item.classList.toggle('active', i === activeStep);
        item.classList.toggle('done', i < activeStep);
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
        const tr = document.createElement('tr');
        tr.innerHTML = `
            <td><input type="checkbox" class="form-check-input scan-file-cb" data-idx="${idx}" checked></td>
            <td class="small text-truncate" style="max-width:200px" title="${f.file_path}">${_basename(f.file_path)}</td>
            <td class="small">${f.title || '—'}</td>
            <td class="small">${f.author || '—'}</td>
            <td class="small text-nowrap">${_formatSize(f.file_size)}</td>
        `;
        tbody.appendChild(tr);
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

function _renderMatchResults(files, stats) {
    // Update stat cards
    document.getElementById('matchedCount').textContent  = stats?.matched  || 0;
    document.getElementById('uncertainCount').textContent = stats?.uncertain || 0;
    document.getElementById('duplicatesCount').textContent = stats?.duplicates || 0;
    document.getElementById('notFoundCount').textContent  = stats?.not_found  || 0;

    const container = document.getElementById('matchedFilesList');
    if (!container) return;

    container.innerHTML = '';

    files.forEach((item, idx) => {
        const match = item.match_result;
        const confidence = match?.confidence || 0;
        const isDuplicate = item.duplicate_status === 'duplicate';
        const isNotFound = !match || match.no_match;

        const card = document.createElement('div');
        card.className = `match-item mb-3 ${isDuplicate ? 'duplicate' : isNotFound ? 'not-found' : confidence < 0.8 ? 'uncertain' : ''}`;
        card.innerHTML = `
            <div class="match-item-header">
                <div class="d-flex align-items-center gap-2">
                    <input type="checkbox" class="form-check-input match-file-cb" data-idx="${idx}" ${item.selected !== false && !isDuplicate && !isNotFound ? 'checked' : ''}>
                    <strong class="small">${_basename(item.file_info?.file_path || '')}</strong>
                </div>
                <div class="d-flex gap-2 align-items-center">
                    ${isDuplicate ? '<span class="badge bg-danger">Duplicate</span>' : ''}
                    ${isNotFound  ? '<span class="badge bg-secondary">Not Found</span>' : ''}
                    ${!isNotFound && !isDuplicate ? `<span class="match-confidence ${confidence >= 0.9 ? 'high' : confidence >= 0.7 ? 'medium' : 'low'}">${Math.round(confidence * 100)}%</span>` : ''}
                </div>
            </div>
            <div class="match-item-body">
                <div class="row g-2">
                    <div class="col-md-6">
                        <div class="small text-muted fw-bold mb-1">Local File</div>
                        <div class="small">${item.file_info?.title || '—'}</div>
                        <div class="small text-muted">${item.file_info?.author || ''}</div>
                    </div>
                    <div class="col-md-6">
                        <div class="small text-muted fw-bold mb-1">Audible Match</div>
                        ${match && !match.no_match ? `
                            <div class="small">${match.title || '—'}</div>
                            <div class="small text-muted">${match.authors || ''}</div>
                        ` : '<div class="small text-muted">No match found</div>'}
                    </div>
                </div>
            </div>
        `;
        container.appendChild(card);
    });

    _updateImportCount();
    container.querySelectorAll('.match-file-cb').forEach(cb => {
        cb.addEventListener('change', _updateImportCount);
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
            audible_product: item.match_result
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
            bar.textContent = `${pct}%`;
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
    Object.entries(imports).forEach(([key, item]) => {
        const el = document.createElement('div');
        el.className = `import-progress-item state-${item.state || 'pending'}`;
        el.innerHTML = `
            <div class="import-progress-info">
                <div class="import-progress-title">${item.title || key}</div>
                <div class="import-progress-sub">${_stateLabel(item.state)}</div>
                ${item.error ? `<div class="text-danger small mt-1"><i class="fas fa-exclamation-triangle me-1"></i>${item.error}</div>` : ''}
            </div>
            <span class="state-badge state-${item.state}">${_stateLabel(item.state)}</span>
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
