/**
 * library.js — Library fetching, rendering, filtering, selection, download trigger
 * Loaded on the index page only.
 */

// ── Library State ──

async function loadLibraryState() {
    try {
        const result = await apiCall('/api/library/state');
        if (result.success) {
            AppState.set('libraryStateAsins', new Set(result.asins));
        }
    } catch (err) {
        console.error('loadLibraryState failed:', err);
    }
}

async function fetchLibrary() {
    const accountName = AppState.get('currentAccount');
    if (!accountName) return;

    const btn = document.getElementById('refreshLibraryBtn');
    const restore = btn ? setButtonLoading(btn, 'Loading…') : null;
    _showLoading(true);

    try {
        await loadLibraryState();

        const result = await apiCall('/api/library/fetch', {
            method: 'POST',
            body: JSON.stringify({ account_name: accountName })
        });

        AppState.set('library', result.library || []);
        populateFilterDropdowns(result.library || []);
        showToast(`Loaded ${result.library?.length || 0} books`, 'success', 3000);
    } catch (err) {
        showToast('Failed to load library: ' + err.message, 'danger');
    } finally {
        if (restore) restore();
        _showLoading(false);
    }
}

async function fetchAllLibraries() {
    const btn = document.getElementById('loadAllLibrariesBtn');
    const restore = btn ? setButtonLoading(btn, 'Loading…') : null;
    _showLoading(true);

    try {
        await loadLibraryState();

        const result = await apiCall('/api/library/all');
        AppState.set('isUnifiedView', true);
        AppState.set('library', result.library || []);
        populateFilterDropdowns(result.library || []);
        showToast(`Loaded ${result.library?.length || 0} books from all accounts`, 'success', 3000);
    } catch (err) {
        showToast('Failed to load libraries: ' + err.message, 'danger');
    } finally {
        if (restore) restore();
        _showLoading(false);
    }
}

async function syncLibrary() {
    const libraryName = AppState.get('currentLibraryName');
    if (!libraryName) {
        showToast('Please select a library first', 'warning');
        return;
    }

    const btn = document.getElementById('syncLibraryBtn');
    const restore = btn ? setButtonLoading(btn, '') : null;

    try {
        await apiCall('/api/library/sync', {
            method: 'POST',
            body: JSON.stringify({ library_name: libraryName })
        });
        await loadLibraryState();
        renderLibrary();
        showToast('Library synced', 'success', 3000);
    } catch (err) {
        showToast('Sync failed: ' + err.message, 'danger');
    } finally {
        if (restore) restore();
    }
}

// ── Rendering ──

function renderLibrary() {
    const library = AppState.get('library');
    const filters = AppState.getFilters();
    const libraryStateAsins = AppState.get('libraryStateAsins');

    let books = library;

    // Search
    if (filters.search) {
        const q = filters.search.toLowerCase();
        books = books.filter(b =>
            b.title?.toLowerCase().includes(q) ||
            b.authors?.toLowerCase().includes(q)
        );
    }

    // Dropdown filters
    if (filters.author)    books = books.filter(b => b.authors === filters.author);
    if (filters.language)  books = books.filter(b => b.language === filters.language);
    if (filters.narrator)  books = books.filter(b => b.narrator === filters.narrator);
    if (filters.series)    books = books.filter(b => b.series === filters.series);
    if (filters.publisher) books = books.filter(b => b.publisher === filters.publisher);
    if (filters.year)      books = books.filter(b => b.release_year === filters.year);
    if (filters.account)   books = books.filter(b => b.account_name === filters.account);
    if (filters.hideDownloaded) books = books.filter(b => !libraryStateAsins.has(b.asin));

    _displayBooks(books);
    _updateBookCount(books.length, library.length);
    _updateFilterActiveCount();
}

function _displayBooks(books) {
    const grid = document.getElementById('libraryGrid');
    const list = document.getElementById('libraryList');
    const noBooks = document.getElementById('noBooksMessage');
    const viewMode = AppState.get('viewMode');
    const selectedAsins = AppState.get('selectedAsins');

    if (!grid && !list) return;

    if (books.length === 0) {
        if (noBooks) noBooks.hidden = false;
        if (grid) grid.innerHTML = '';
        if (list) list.innerHTML = '';
        return;
    }

    if (noBooks) noBooks.hidden = true;

    if (viewMode === 'card') {
        if (grid) grid.style.display = '';
        if (list) { list.style.display = 'none'; list.innerHTML = ''; }
        if (grid) {
            grid.innerHTML = '';
            books.forEach(book => grid.appendChild(_createBookCard(book, selectedAsins)));
        }
    } else {
        if (list) list.style.display = '';
        if (grid) { grid.style.display = 'none'; grid.innerHTML = ''; }
        if (list) {
            list.innerHTML = '';
            books.forEach(book => list.appendChild(_createBookListItem(book, selectedAsins)));
        }
    }
}

function _formatDuration(mins) {
    if (!mins) return '';
    const h = Math.floor(mins / 60);
    const m = mins % 60;
    return h > 0 ? `${h}h ${m}m` : `${m}m`;
}

function _createBookCard(book, selectedAsins) {
    const inLibrary = AppState.get('libraryStateAsins').has(book.asin);
    const isSelected = selectedAsins.has(book.asin);
    const isUnified = AppState.get('isUnifiedView');

    const div = document.createElement('div');
    div.innerHTML = `
        <div class="book-card${isSelected ? ' selected' : ''}${inLibrary ? ' in-library' : ''}" data-asin="${book.asin}" tabindex="0" role="checkbox" aria-checked="${isSelected}">
            <div class="book-cover-wrap">
                ${book.cover_url
                    ? `<img src="${book.cover_url}" alt="${_esc(book.title)}" loading="lazy">`
                    : `<div class="book-cover-placeholder"><i class="fas fa-headphones"></i></div>`}
                ${inLibrary ? '<span class="book-in-library-chip">In Library</span>' : ''}
                <div class="book-checkbox-wrap">
                    <input type="checkbox" class="form-check-input" ${isSelected ? 'checked' : ''} tabindex="-1" aria-hidden="true">
                </div>
                <div class="book-status-overlay" id="overlay_${book.asin}"></div>
            </div>
            <div class="book-card-body">
                <div class="book-card-title">${_esc(book.title)}</div>
                <div class="book-card-author">${_esc(book.authors || '')}</div>
                ${isUnified && book.account_name ? `<div class="book-account-badge">${_esc(book.account_name)}</div>` : ''}
            </div>
        </div>
    `;

    const card = div.firstElementChild;
    card.addEventListener('click', () => _toggleSelection(book.asin));
    card.addEventListener('keydown', e => { if (e.key === ' ' || e.key === 'Enter') { e.preventDefault(); _toggleSelection(book.asin); } });

    return card;
}

function _createBookListItem(book, selectedAsins) {
    const inLibrary = AppState.get('libraryStateAsins').has(book.asin);
    const isSelected = selectedAsins.has(book.asin);
    const isUnified = AppState.get('isUnifiedView');

    const item = document.createElement('div');
    item.className = `book-list-item${isSelected ? ' selected' : ''}`;
    item.dataset.asin = book.asin;
    item.setAttribute('role', 'checkbox');
    item.setAttribute('aria-checked', isSelected);
    item.setAttribute('tabindex', '0');

    item.innerHTML = `
        <input type="checkbox" class="form-check-input flex-shrink-0" ${isSelected ? 'checked' : ''} aria-hidden="true" tabindex="-1">
        ${book.cover_url
            ? `<img src="${book.cover_url}" class="book-list-cover" alt="" loading="lazy">`
            : `<div class="book-list-cover-placeholder"><i class="fas fa-headphones"></i></div>`}
        <div class="book-list-info">
            <div class="book-list-title">${_esc(book.title)}</div>
            <div class="book-list-author">${_esc(book.authors || '')}</div>
            ${book.length_mins ? `<div class="book-list-duration">${_formatDuration(book.length_mins)}</div>` : ''}
        </div>
        <div class="book-list-status">
            ${inLibrary ? '<span class="badge bg-success"><i class="fas fa-check"></i> In Library</span>' : ''}
            ${isUnified && book.account_name ? `<span class="badge bg-secondary ms-1">${_esc(book.account_name)}</span>` : ''}
        </div>
    `;

    item.addEventListener('click', e => {
        if (e.target.type !== 'checkbox') _toggleSelection(book.asin);
    });
    item.querySelector('input[type=checkbox]').addEventListener('change', () => _toggleSelection(book.asin));
    item.addEventListener('keydown', e => { if (e.key === ' ' || e.key === 'Enter') { e.preventDefault(); _toggleSelection(book.asin); } });

    return item;
}

function _toggleSelection(asin) {
    AppState.toggleSelection(asin);
}

function _esc(str) {
    return String(str || '').replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
}

function _showLoading(show) {
    const spinner = document.getElementById('loadingSpinner');
    const grid = document.getElementById('libraryGrid');
    const list = document.getElementById('libraryList');
    if (spinner) spinner.hidden = !show;
    if (show) {
        if (grid) grid.style.display = 'none';
        if (list) list.style.display = 'none';
    }
}

function _updateBookCount(shown, total) {
    const el = document.getElementById('bookCount');
    if (!el) return;
    if (shown === total) {
        el.textContent = `${total} book${total !== 1 ? 's' : ''}`;
    } else {
        el.textContent = `${shown} of ${total}`;
    }
}

function _updateFilterActiveCount() {
    const count = AppState.countActiveFilters();
    const badge = document.getElementById('filterActiveCount');
    const toggle = document.getElementById('filterToggleBtn');
    if (badge) {
        badge.textContent = count;
        badge.style.display = count > 0 ? 'inline-flex' : 'none';
    }
    if (toggle) {
        toggle.textContent = count > 0 ? `Filters (${count})` : 'Filters';
    }
}

// ── Filter Dropdowns ──

function populateFilterDropdowns(books) {
    const unique = key => [...new Set(books.map(b => b[key]).filter(v => v && v !== 'Unknown'))].sort();

    _populateSelect('authorFilter',      unique('authors'),      'All Authors');
    _populateSelect('languageFilter',    unique('language'),     'All Languages');
    _populateSelect('narratorFilter',    unique('narrator'),     'All Narrators');
    _populateSelect('seriesFilter',      unique('series'),       'All Series');
    _populateSelect('publisherFilter',   unique('publisher'),    'All Publishers');
    _populateSelect('releaseYearFilter', unique('release_year').reverse(), 'All Years');

    const accounts = [...new Set(books.map(b => b.account_name).filter(Boolean))].sort();
    const accountFilterEl = document.getElementById('accountFilter');
    if (accountFilterEl) {
        const multiAccount = accounts.length > 1;
        accountFilterEl.hidden = !multiAccount;
        if (multiAccount) _populateSelect('accountFilter', accounts, 'All Accounts');
    }
}

function _populateSelect(id, values, placeholder) {
    const select = document.getElementById(id);
    if (!select) return;
    const current = select.value;
    select.innerHTML = `<option value="">${placeholder}</option>`;
    values.forEach(v => {
        const opt = document.createElement('option');
        opt.value = v;
        opt.textContent = v;
        select.appendChild(opt);
    });
    if (current) select.value = current;
}

function clearAllFilters() {
    AppState.resetFilters();
    ['searchInput', 'accountFilter', 'authorFilter', 'languageFilter', 'narratorFilter',
     'seriesFilter', 'publisherFilter', 'releaseYearFilter'].forEach(id => {
        const el = document.getElementById(id);
        if (el) el.value = '';
    });
    const hideEl = document.getElementById('hideDownloadedFilter');
    if (hideEl) hideEl.checked = false;
}

// ── Selection Helpers ──

function selectAllVisible() {
    const library = AppState.get('library');
    const filters = AppState.getFilters();
    const libraryStateAsins = AppState.get('libraryStateAsins');

    let books = library;
    if (filters.search) {
        const q = filters.search.toLowerCase();
        books = books.filter(b => b.title?.toLowerCase().includes(q) || b.authors?.toLowerCase().includes(q));
    }
    if (filters.author)    books = books.filter(b => b.authors === filters.author);
    if (filters.language)  books = books.filter(b => b.language === filters.language);
    if (filters.narrator)  books = books.filter(b => b.narrator === filters.narrator);
    if (filters.series)    books = books.filter(b => b.series === filters.series);
    if (filters.publisher) books = books.filter(b => b.publisher === filters.publisher);
    if (filters.year)      books = books.filter(b => b.release_year === filters.year);
    if (filters.account)   books = books.filter(b => b.account_name === filters.account);
    if (filters.hideDownloaded) books = books.filter(b => !libraryStateAsins.has(b.asin));

    AppState.selectAll(books.map(b => b.asin));
}

// ── Download ──

async function downloadSelectedBooks() {
    const selectedAsins = AppState.get('selectedAsins');
    if (selectedAsins.size === 0) {
        showToast('No books selected', 'warning');
        return;
    }

    const libraryName = AppState.get('currentLibraryName');
    if (!libraryName) {
        // Highlight the library selector
        const sel = document.getElementById('downloadLibrarySelect');
        if (sel) {
            sel.classList.add('is-invalid');
            setTimeout(() => sel.classList.remove('is-invalid'), 3000);
        }
        showToast('Please select a download library first', 'warning');
        return;
    }

    const btn = document.getElementById('downloadBtn');
    const count = selectedAsins.size;
    const restore = btn ? setButtonLoading(btn, `Adding ${count} to queue…`) : null;

    // Fire and forget
    apiCall('/api/download/books', {
        method: 'POST',
        body: JSON.stringify({
            selected_asins: Array.from(selectedAsins),
            cleanup_aax: AppState.get('cleanupAax'),
            library_name: libraryName
        })
    }).then(() => {
        showToast(
            `${count} book${count !== 1 ? 's' : ''} added to queue`,
            'success'
        );
        AppState.clearSelection();
    }).catch(err => {
        showToast('Download failed: ' + err.message, 'danger');
    });

    setTimeout(() => { if (restore) restore(); }, 2000);
}

// ── React to AppState ──

document.addEventListener('appstate:change', function (e) {
    if (e.detail.key === 'library' || e.detail.key === 'libraryStateAsins') {
        renderLibrary();
    }
    if (e.detail.key === 'viewMode') {
        renderLibrary();
        _updateViewButtons(e.detail.value);
    }
    if (e.detail.key === 'isUnifiedView') {
        renderLibrary();
        _updateLoadButtons();
    }
    if (e.detail.key === 'accountData') {
        _updateLoadButtons();
    }
});

document.addEventListener('appstate:filterschange', renderLibrary);

document.addEventListener('appstate:selectionchange', function () {
    const count = AppState.get('selectedAsins').size;
    const btn = document.getElementById('downloadBtn');
    if (btn) {
        btn.hidden = count === 0;
        btn.innerHTML = `<i class="fas fa-download me-2"></i>Download ${count} Book${count !== 1 ? 's' : ''}`;
    }

    // Update visible checkboxes / selection states
    document.querySelectorAll('.book-card, .book-list-item').forEach(el => {
        const asin = el.dataset.asin;
        const selected = AppState.get('selectedAsins').has(asin);
        el.classList.toggle('selected', selected);
        const cb = el.querySelector('input[type=checkbox]');
        if (cb) cb.checked = selected;
        el.setAttribute('aria-checked', selected);
    });
});

// ── Library selector change ──

document.addEventListener('libraries:updated', function (e) {
    _populateLibrarySelect(e.detail);
});

function _populateLibrarySelect(libraries) {
    const select = document.getElementById('downloadLibrarySelect');
    if (!select) return;

    const current = select.value;
    select.innerHTML = '<option value="">Select library…</option>';

    Object.entries(libraries).forEach(([name, lib]) => {
        const opt = document.createElement('option');
        opt.value = name;
        opt.textContent = name;
        select.appendChild(opt);
    });

    if (current && libraries[current]) {
        select.value = current;
        AppState.set('currentLibraryName', current);
    }
}

function _updateViewButtons(mode) {
    document.getElementById('cardViewBtn')?.classList.toggle('active', mode === 'card');
    document.getElementById('listViewBtn')?.classList.toggle('active', mode === 'list');
}

// ── Auth/account events ──

document.addEventListener('account:selected', function (e) {
    AppState.set('isUnifiedView', false);
    _showLibraryUI(true);
    AppState.set('library', []);
    AppState.resetFilters();
});

document.addEventListener('account:cleared', function () {
    AppState.set('isUnifiedView', false);
    _showLibraryUI(false);
    AppState.set('library', []);
});

document.addEventListener('auth:statusChanged', function (e) {
    _updateAuthUI(e.detail.authenticated, e.detail.accountName);
});

function _updateLoadButtons() {
    const accountData = AppState.get('accountData') || {};
    const currentAccount = AppState.get('currentAccount');
    const isAuthenticated = AppState.get('isAuthenticated');
    const authenticatedCount = Object.values(accountData).filter(a => a.authenticated).length;

    const refreshBtn = document.getElementById('refreshLibraryBtn');
    const loadAllBtn = document.getElementById('loadAllLibrariesBtn');

    if (refreshBtn) refreshBtn.hidden = !(currentAccount && isAuthenticated);
    if (loadAllBtn) loadAllBtn.hidden = authenticatedCount < 2;
}

function _showLibraryUI(show) {
    const content = document.getElementById('libraryContent');
    const welcome = document.getElementById('welcomeMessage');
    const onboarding = document.getElementById('onboardingWizard');

    // Only hide/show if onboarding isn't active
    if (onboarding && !onboarding.hidden) return;

    if (content) content.hidden = !show;
    if (welcome) welcome.hidden = show;
    _updateLoadButtons();
}

function _updateAuthUI(isAuthenticated, accountName) {
    const loginBtn = document.getElementById('libraryLoginBtn');
    const downloadToSection = document.getElementById('downloadToSection');
    const authAlert = document.getElementById('libraryAuthAlert');

    if (loginBtn) loginBtn.hidden = isAuthenticated;
    if (downloadToSection) downloadToSection.hidden = !isAuthenticated;
    _updateLoadButtons();
    if (authAlert) {
        authAlert.hidden = isAuthenticated;
        if (!isAuthenticated) {
            authAlert.innerHTML = `<i class="fas fa-exclamation-triangle me-2"></i>
                Not authenticated.
                <button class="btn btn-sm btn-warning ms-2" onclick="authenticateAccount()">
                    <i class="fas fa-sign-in-alt"></i> Login to Audible
                </button>`;
        }
    }
}

// ── DOMContentLoaded ──

document.addEventListener('DOMContentLoaded', function () {
    // Search input
    document.getElementById('searchInput')?.addEventListener('input', function () {
        AppState.setFilter('search', this.value);
    });

    // Account filter
    document.getElementById('accountFilter')?.addEventListener('change', function () {
        AppState.setFilter('account', this.value);
    });

    // Load All Libraries button
    document.getElementById('loadAllLibrariesBtn')?.addEventListener('click', fetchAllLibraries);

    // Filter dropdowns
    ['authorFilter', 'languageFilter', 'narratorFilter', 'seriesFilter', 'publisherFilter', 'releaseYearFilter'].forEach(id => {
        const filterKey = id.replace('Filter', '').replace('releaseYear', 'year').replace('author', 'author');
        document.getElementById(id)?.addEventListener('change', function () {
            // Map element IDs to filter keys
            const keyMap = {
                authorFilter: 'author',
                languageFilter: 'language',
                narratorFilter: 'narrator',
                seriesFilter: 'series',
                publisherFilter: 'publisher',
                releaseYearFilter: 'year'
            };
            AppState.setFilter(keyMap[id], this.value);
        });
    });

    document.getElementById('hideDownloadedFilter')?.addEventListener('change', function () {
        AppState.setFilter('hideDownloaded', this.checked);
    });

    document.getElementById('clearFiltersBtn')?.addEventListener('click', clearAllFilters);

    // View switcher
    document.getElementById('cardViewBtn')?.addEventListener('click', () => AppState.set('viewMode', 'card'));
    document.getElementById('listViewBtn')?.addEventListener('click', () => AppState.set('viewMode', 'list'));

    // Select/clear all
    document.getElementById('selectAllVisibleBtn')?.addEventListener('click', selectAllVisible);
    document.getElementById('clearSelectionBtn')?.addEventListener('click', () => AppState.clearSelection());

    // Refresh library
    document.getElementById('refreshLibraryBtn')?.addEventListener('click', fetchLibrary);

    // Sync library
    document.getElementById('syncLibraryBtn')?.addEventListener('click', syncLibrary);

    // Download library selector
    document.getElementById('downloadLibrarySelect')?.addEventListener('change', function () {
        AppState.set('currentLibraryName', this.value);
    });

    // Download button (FAB)
    document.getElementById('downloadBtn')?.addEventListener('click', downloadSelectedBooks);

    // Login button in library header
    document.getElementById('libraryLoginBtn')?.addEventListener('click', () => authenticateAccount());

    // Filter tray toggle
    document.getElementById('filterToggleBtn')?.addEventListener('click', function () {
        const tray = document.getElementById('filterTray');
        if (tray) tray.hidden = !tray.hidden;
    });
});
