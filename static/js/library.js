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

async function loadHousehold() {
    try {
        const result = await apiCall('/api/library/household');
        AppState.set('household', result.books || {});
        AppState.set('absConfigured', !!result.abs_configured);
    } catch (err) {
        console.error('loadHousehold failed:', err);
    }
}

async function fetchLibrary() {
    const accountName = AppState.get('currentAccount');
    if (!accountName) return;

    const btn = document.getElementById('refreshLibraryBtn');
    const restore = btn ? setButtonLoading(btn, 'Loading…') : null;
    _showLoading(true);

    try {
        await Promise.all([loadLibraryState(), loadHousehold()]);

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

async function fetchAllLibraries(force = false) {
    const btn = document.getElementById('refreshLibraryBtn');
    const restore = btn ? setButtonLoading(btn, 'Syncing…') : null;
    _showLoading(true);
    _showLibraryUI(true);

    try {
        await Promise.all([loadLibraryState(), loadHousehold()]);

        const url = force ? '/api/library/all?force=true' : '/api/library/all';
        const result = await apiCall(url);
        AppState.set('isUnifiedView', true);
        AppState.set('lastSyncedAt', Date.now());
        AppState.set('library', result.library || []);
        populateFilterDropdowns(result.library || []);
        if (force) showToast(`Refreshed — ${result.library?.length || 0} books`, 'success', 3000);
    } catch (err) {
        showToast('Failed to load library: ' + err.message, 'danger');
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
        await Promise.all([loadLibraryState(), loadHousehold()]);
        renderLibrary();
        showToast('Library synced', 'success', 3000);
    } catch (err) {
        showToast('Sync failed: ' + err.message, 'danger');
    } finally {
        if (restore) restore();
    }
}

// ── Status model ──

const _PALETTE = 12;
const _ACTIVE_STATES = new Set(['license_requested', 'license_granted', 'downloading', 'download_complete', 'decrypting']);
const _WAITING_STATES = new Set(['pending', 'retrying']);
const _MB_PER_MIN = 0.48; // ~64 kbps m4b, used only for the "≈ size" estimate
const _SKIP_DUPES_KEY = 'audible-skip-duplicates';

function _hash(str) {
    let h = 0;
    for (let i = 0; i < str.length; i++) h = (h * 31 + str.charCodeAt(i)) | 0;
    return Math.abs(h);
}

function _coverClass(book) {
    return 'cover-c' + (_hash(book.asin || book.title || '') % _PALETTE);
}

function _owners(book) {
    return (book.account_names && book.account_names.length) ? book.account_names : (book.account_name ? [book.account_name] : []);
}

/** new | downloaded | downloading | queued | duplicate */
function _bookStatus(book) {
    const live = (AppState.get('downloads') || {})[book.asin];
    if (live) {
        if (_ACTIVE_STATES.has(live.state)) return 'downloading';
        if (_WAITING_STATES.has(live.state)) return 'queued';
    }
    if (AppState.get('libraryStateAsins').has(book.asin)) return 'downloaded';
    if (_owners(book).length > 1) return 'duplicate';
    return 'new';
}

const _PILLS = {
    new: ['New', 'pill-new'],
    downloaded: ['Downloaded', 'pill-done'],
    downloading: ['Downloading', 'pill-active'],
    queued: ['Queued', 'pill-queued'],
    duplicate: ['Duplicate', 'pill-dup']
};

/** {label, cls} or null when Audiobookshelf is not configured */
function _absState(book) {
    if (!AppState.get('absConfigured')) return null;
    const h = (AppState.get('household') || {})[book.asin];
    const st = h && h.abs;
    if (st === 'matched') return { label: 'In Audiobookshelf', cls: 'abs-ok' };
    if (st === 'pending') return { label: 'Scanning', cls: 'abs-scan' };
    if (st === 'ambiguous') return { label: 'Check match', cls: 'abs-scan' };
    if (h && h.status === 'downloaded' && !st) return { label: 'Scanning', cls: 'abs-scan' };
    return { label: 'Not in ABS', cls: 'abs-none' };
}

function _estimateBytes(book) {
    const h = (AppState.get('household') || {})[book.asin];
    if (h && h.size_bytes) return h.size_bytes;
    return (book.length_mins || 0) * _MB_PER_MIN * 1024 * 1024;
}

function _formatBytes(bytes) {
    if (!bytes) return '';
    const gb = bytes / (1024 ** 3);
    if (gb >= 1) return gb.toFixed(1) + ' GB';
    return Math.max(1, Math.round(bytes / (1024 ** 2))) + ' MB';
}

// ── Filtering ──

function _matchesSearch(b, q) {
    return [b.title, b.authors, b.narrator, b.asin].some(v => v && String(v).toLowerCase().includes(q));
}

/** Apply every filter except the status tab. */
function _filterBooks(ignoreStatus) {
    const filters = AppState.getFilters();
    const libraryStateAsins = AppState.get('libraryStateAsins');
    let books = AppState.get('library');

    if (filters.search) {
        const q = filters.search.toLowerCase();
        books = books.filter(b => _matchesSearch(b, q));
    }
    if (filters.author)    books = books.filter(b => b.authors === filters.author);
    if (filters.language)  books = books.filter(b => b.language === filters.language);
    if (filters.narrator)  books = books.filter(b => b.narrator === filters.narrator);
    if (filters.series)    books = books.filter(b => b.series === filters.series);
    if (filters.publisher) books = books.filter(b => b.publisher === filters.publisher);
    if (filters.year)      books = books.filter(b => b.release_year === filters.year);
    if (filters.account)   books = books.filter(b => _owners(b).includes(filters.account));
    if (filters.hideDownloaded) books = books.filter(b => !libraryStateAsins.has(b.asin));
    return books;
}

function _byStatusTab(books, tab) {
    switch (tab) {
        case 'new':        return books.filter(b => _bookStatus(b) === 'new');
        case 'downloaded': return books.filter(b => _bookStatus(b) === 'downloaded');
        case 'queued':     return books.filter(b => ['queued', 'downloading'].includes(_bookStatus(b)));
        case 'duplicate':  return books.filter(b => _owners(b).length > 1);
        default:           return books;
    }
}

function _sortBooks(books, mode) {
    if (!mode) {
        // Default order is 'recently added': newest purchase first when Audible supplies the date.
        return books.some(b => b.purchase_date)
            ? books.slice().sort((a, b) => (b.purchase_date || '').localeCompare(a.purchase_date || ''))
            : books;
    }
    const by = {
        title:   (a, b) => (a.title || '').localeCompare(b.title || ''),
        author:  (a, b) => (a.authors || '').localeCompare(b.authors || '') || (a.title || '').localeCompare(b.title || ''),
        release: (a, b) => (b.release_date || '').localeCompare(a.release_date || ''),
        length:  (a, b) => (b.length_mins || 0) - (a.length_mins || 0)
    }[mode];
    return by ? books.slice().sort(by) : books;
}

function _visibleBooks() {
    const filters = AppState.getFilters();
    return _sortBooks(_byStatusTab(_filterBooks(), filters.status), filters.sort);
}

// ── Rendering ──

function renderLibrary() {
    const library = AppState.get('library');
    const books = _visibleBooks();

    _displayBooks(books);
    _updateBookCount(books.length, library.length);
    _updateFilterActiveCount();
    _renderStatusTabs();
    _updateSubtitle();
    _updateSelectionBar();
}

function _renderStatusTabs() {
    const host = document.getElementById('statusTabs');
    if (!host) return;
    const active = AppState.getFilters().status || '';
    const base = _filterBooks();
    const defs = [
        ['', 'All', base.length],
        ['new', 'New', _byStatusTab(base, 'new').length],
        ['downloaded', 'Downloaded', _byStatusTab(base, 'downloaded').length],
        ['queued', 'Queued', _byStatusTab(base, 'queued').length],
        ['duplicate', 'Duplicates', _byStatusTab(base, 'duplicate').length]
    ];
    host.replaceChildren();
    defs.forEach(([key, label, n]) => {
        const btn = document.createElement('button');
        btn.type = 'button';
        btn.className = 'status-tab' + (key === active ? ' active' : '');
        btn.setAttribute('role', 'tab');
        btn.setAttribute('aria-selected', key === active ? 'true' : 'false');
        btn.dataset.status = key;
        btn.append(label + ' ');
        const count = document.createElement('span');
        count.className = 'n';
        count.textContent = n;
        btn.appendChild(count);
        btn.addEventListener('click', () => AppState.setFilter('status', key));
        host.appendChild(btn);
    });
    const newBtn = document.getElementById('selectAllNewBtn');
    if (newBtn) {
        const newCount = defs[1][2];
        newBtn.textContent = `Select all ${newCount} new`;
        newBtn.disabled = newCount === 0;
        newBtn.style.visibility = newCount === 0 ? 'hidden' : '';
    }
}

function _relativeTime(ts) {
    const mins = Math.round((Date.now() - ts) / 60000);
    if (mins < 1) return 'just now';
    if (mins < 60) return `${mins} min ago`;
    const h = Math.round(mins / 60);
    if (h < 24) return `${h} h ago`;
    return `${Math.round(h / 24)} d ago`;
}

function _updateSubtitle() {
    const el = document.getElementById('librarySub');
    if (!el) return;
    const library = AppState.get('library');
    const accounts = new Set(library.flatMap(_owners));
    const n = library.length;
    let text = `${n} book${n !== 1 ? 's' : ''}`;
    if (accounts.size) text += ` from ${accounts.size} account${accounts.size !== 1 ? 's' : ''}`;
    const at = AppState.get('lastSyncedAt');
    if (at) text += ` · synced ${_relativeTime(at)}`;
    el.textContent = text;
}

function _displayBooks(books) {
    const grid = document.getElementById('libraryGrid');
    const list = document.getElementById('libraryList');
    const series = document.getElementById('librarySeries');
    const noBooks = document.getElementById('noBooksMessage');
    const viewMode = AppState.get('viewMode');
    const selectedAsins = AppState.get('selectedAsins');

    // Always clear: each render rebuilds its view (chunked below), never appends to a previous one.
    const show = (el, on) => { if (el) { el.style.display = on ? '' : 'none'; el.replaceChildren(); } };
    _lazyStop();

    if (books.length === 0) {
        if (noBooks) noBooks.hidden = false;
        show(grid, false); show(list, false); show(series, false);
        return;
    }
    if (noBooks) noBooks.hidden = true;

    show(grid, viewMode === 'card');
    show(list, viewMode === 'list');
    show(series, viewMode === 'series');

    // Nodes are created in chunks (see _lazyRender) so a 3000-book library paints immediately.
    const selected = () => AppState.get('selectedAsins');
    if (viewMode === 'card' && grid) {
        const wrap = document.createElement('div');
        wrap.className = 'book-grid';
        grid.appendChild(wrap);
        _lazyRender(grid, books.map(book => () => wrap.appendChild(_createBookCard(book, selected()))));
    } else if (viewMode === 'list' && list) {
        const rows = document.createElement('div');
        rows.className = 'book-rows';
        list.appendChild(rows);
        _lazyRender(list, books.map(book => () => rows.appendChild(_createBookListItem(book, selected()))));
    } else if (viewMode === 'series' && series) {
        _renderSeries(series, books);
    }
}

// ── Chunked rendering ──
// The first LAZY_CHUNK books render synchronously; the rest are appended as a sentinel below the
// last rendered node approaches the viewport. Data-driven state (selection, counts, "select all")
// never reads the DOM, so behaviour is identical to rendering everything at once.
const LAZY_CHUNK = 120;
let _lazyObserver = null;

function _lazyStop() {
    if (_lazyObserver) { _lazyObserver.disconnect(); _lazyObserver = null; }
}

function _lazyRender(host, units) {
    _lazyStop();
    let next = 0;
    const run = count => { for (const end = Math.min(units.length, next + count); next < end; next++) units[next](); };
    run(LAZY_CHUNK);
    if (next >= units.length) return;
    if (typeof IntersectionObserver === 'undefined') { run(units.length); return; }
    const sentinel = document.createElement('div');
    sentinel.className = 'lazy-sentinel';
    sentinel.style.height = '1px';
    host.appendChild(sentinel);
    const fill = () => {
        while (next < units.length && sentinel.getBoundingClientRect().top < window.innerHeight + 1200) run(LAZY_CHUNK);
        if (next >= units.length) { _lazyStop(); sentinel.remove(); } else host.appendChild(sentinel);
    };
    _lazyObserver = new IntersectionObserver(entries => { if (entries.some(e => e.isIntersecting)) fill(); },
        { rootMargin: '1200px 0px' });
    _lazyObserver.observe(sentinel);
}

// Insert before the lazy sentinel so it stays last in its host.
function _lazyPlace(host, node) {
    const sentinel = host.querySelector(':scope > .lazy-sentinel');
    if (sentinel) host.insertBefore(node, sentinel); else host.appendChild(node);
}

function _seriesIndex(book) {
    const sd = Array.isArray(book.series_data) ? book.series_data[0] : null;
    const n = sd && parseFloat(sd.sequence);
    return Number.isFinite(n) ? n : Infinity;
}

function _renderSeries(host, books) {
    const groups = new Map();
    books.forEach(b => {
        const key = b.series || '';
        if (!groups.has(key)) groups.set(key, []);
        groups.get(key).push(b);
    });
    const keys = [...groups.keys()].sort((a, b) => (a === '' ? 1 : b === '' ? -1 : a.localeCompare(b)));
    const units = [];
    keys.forEach(key => {
        const items = groups.get(key);
        if (key) items.sort((a, b) => _seriesIndex(a) - _seriesIndex(b));
        let grid = null;
        items.forEach(book => units.push(() => {
            if (!grid) {   // section is created with its first book
                const section = document.createElement('section');
                section.className = 'series-group';
                const head = document.createElement('div');
                head.className = 'series-head';
                const h = document.createElement('h3');
                h.textContent = key || 'Standalone';
                const count = document.createElement('span');
                count.textContent = `${items.length} book${items.length !== 1 ? 's' : ''}`;
                head.append(h, count);
                grid = document.createElement('div');
                grid.className = 'book-grid';
                section.append(head, grid);
                _lazyPlace(host, section);
            }
            grid.appendChild(_createBookCard(book, AppState.get('selectedAsins')));
        }));
    });
    _lazyRender(host, units);
}

function _formatDuration(mins) {
    if (!mins) return '';
    const h = Math.floor(mins / 60);
    const m = mins % 60;
    return h > 0 ? `${h}h ${m}m` : `${m}m`;
}

function _firstSurname(authors) {
    const first = String(authors || '').split(',')[0].trim();
    const parts = first.split(/\s+/);
    return parts[parts.length - 1] || '';
}

function _statusPill(book) {
    const st = _bookStatus(book);
    const [label, cls] = _PILLS[st];
    return `<span class="pill ${cls}">${_esc(label)}</span>`;
}

function _absHtml(book) {
    const abs = _absState(book);
    return abs ? `<span class="abs-state ${abs.cls}"><span class="dot"></span>${_esc(abs.label)}</span>` : '';
}

function _createBookCard(book, selectedAsins) {
    const isSelected = selectedAsins.has(book.asin);
    const owners = _owners(book);
    const showOwners = AppState.get('isUnifiedView') && owners.length > 0;

    const el = document.createElement('div');
    el.innerHTML = `
        <div class="book${isSelected ? ' selected' : ''}" data-asin="${_esc(book.asin)}" tabindex="0" role="checkbox" aria-checked="${isSelected}" aria-label="${_esc(book.title)}">
            <div class="book-cover ${book.cover_url ? '' : _coverClass(book)}">
                ${book.cover_url
                    ? `<img src="${_esc(book.cover_url)}" alt="" width="200" height="200" loading="lazy" decoding="async">`
                    : `<span class="cv-author">${_esc(_firstSurname(book.authors))}</span><span class="cv-title">${_esc(book.title)}</span>`}
                <span class="book-check" aria-hidden="true">✓</span>
            </div>
            <div class="book-meta">
                <div class="book-title">${_esc(book.title)}</div>
                <div class="book-author">${_esc(book.authors || '')}</div>
                <div class="book-status">${_statusPill(book)}${_absHtml(book)}</div>
                ${showOwners ? `<div class="book-owners">${_esc(owners.join(', '))}</div>` : ''}
            </div>
        </div>
    `;
    const card = el.firstElementChild;
    card.addEventListener('click', () => _toggleSelection(book.asin));
    card.addEventListener('keydown', e => { if (e.key === ' ' || e.key === 'Enter') { e.preventDefault(); _toggleSelection(book.asin); } });
    return card;
}

function _createBookListItem(book, selectedAsins) {
    const isSelected = selectedAsins.has(book.asin);
    const owners = _owners(book);
    const item = document.createElement('div');
    item.className = `book-row${isSelected ? ' selected' : ''}`;
    item.dataset.asin = book.asin;
    item.setAttribute('role', 'checkbox');
    item.setAttribute('aria-checked', isSelected);
    item.setAttribute('tabindex', '0');

    const sub = [book.authors, _formatDuration(book.length_mins), AppState.get('isUnifiedView') ? owners.join(', ') : '']
        .filter(Boolean).join(' · ');
    item.innerHTML = `
        <span class="row-check" aria-hidden="true">✓</span>
        <span class="row-cover ${book.cover_url ? '' : _coverClass(book)}">${book.cover_url ? `<img src="${_esc(book.cover_url)}" alt="" width="200" height="200" loading="lazy" decoding="async">` : ''}</span>
        <div class="row-info">
            <div class="row-title">${_esc(book.title)}</div>
            <div class="row-sub">${_esc(sub)}</div>
        </div>
        <div class="row-status">${_statusPill(book)}${_absHtml(book)}</div>
    `;
    item.addEventListener('click', () => _toggleSelection(book.asin));
    item.addEventListener('keydown', e => { if (e.key === ' ' || e.key === 'Enter') { e.preventDefault(); _toggleSelection(book.asin); } });
    return item;
}

function _toggleSelection(asin) {
    AppState.toggleSelection(asin);
}

function _esc(str) {
    return String(str || '').replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;').replace(/'/g, '&#39;');
}

function _showLoading(show) {
    const spinner = document.getElementById('loadingSpinner');
    const grid = document.getElementById('libraryGrid');
    const list = document.getElementById('libraryList');
    const series = document.getElementById('librarySeries');
    if (spinner) spinner.hidden = !show;
    if (show) {
        [grid, list, series].forEach(el => { if (el) el.style.display = 'none'; });
    }
}

function _updateBookCount(shown, total) {
    const el = document.getElementById('bookCount');
    if (!el) return;
    el.textContent = shown === total
        ? `${total} book${total !== 1 ? 's' : ''}`
        : `${shown} of ${total} books`;
}

function _updateFilterActiveCount() {
    const count = AppState.countActiveFilters();
    const badge = document.getElementById('filterActiveCount');
    if (badge) {
        badge.textContent = count;
        badge.style.display = count > 0 ? 'inline-grid' : 'none';
    }
    ['accountFilter', 'authorFilter', 'seriesFilter', 'languageFilter', 'narratorFilter', 'publisherFilter', 'releaseYearFilter'].forEach(id => {
        const el = document.getElementById(id);
        if (el) el.classList.toggle('set', !!el.value);
    });
}

// ── Filter Dropdowns ──

function populateFilterDropdowns(books) {
    const unique = key => [...new Set(books.map(b => b[key]).filter(v => v && v !== 'Unknown'))].sort();

    _populateSelect('authorFilter',      unique('authors'),      'Author');
    _populateSelect('languageFilter',    unique('language'),     'Language');
    _populateSelect('narratorFilter',    unique('narrator'),     'Narrator');
    _populateSelect('seriesFilter',      unique('series'),       'Series');
    _populateSelect('publisherFilter',   unique('publisher'),    'Publisher');
    _populateSelect('releaseYearFilter', unique('release_year').reverse(), 'Year');

    const accounts = [...new Set(books.flatMap(_owners))].sort();
    const accountFilterEl = document.getElementById('accountFilter');
    if (accountFilterEl) {
        const multiAccount = accounts.length > 1;
        accountFilterEl.hidden = !multiAccount;
        if (multiAccount) _populateSelect('accountFilter', accounts, 'Account');
    }
}

function _populateSelect(id, values, placeholder) {
    const select = document.getElementById(id);
    if (!select) return;
    const current = select.value;
    select.replaceChildren();
    const empty = document.createElement('option');
    empty.value = '';
    empty.textContent = placeholder;
    select.appendChild(empty);
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
     'seriesFilter', 'publisherFilter', 'releaseYearFilter', 'sortSelect'].forEach(id => {
        const el = document.getElementById(id);
        if (el) el.value = '';
    });
    const hideEl = document.getElementById('hideDownloadedFilter');
    if (hideEl) hideEl.checked = false;
}

// ── Selection Helpers ──

function selectAllVisible() {
    AppState.selectAll(_visibleBooks().map(b => b.asin));
}

function selectAllNew() {
    AppState.selectAll(_byStatusTab(_filterBooks(), 'new').map(b => b.asin));
}

function _updateSelectionBar() {
    const selected = AppState.get('selectedAsins');
    const count = selected.size;
    const bar = document.getElementById('selectionBar');
    const btn = document.getElementById('downloadBtn');
    if (bar) bar.hidden = count === 0;
    if (!count) return;

    let bytes = 0;
    for (const book of AppState.get('library')) {
        if (selected.has(book.asin)) bytes += _estimateBytes(book);
    }
    const target = AppState.get('currentLibraryName');
    const parts = [];
    if (bytes) parts.push('≈ ' + _formatBytes(bytes));
    parts.push(target ? `to ${target}` : 'choose a library');

    const countEl = document.getElementById('selectionCount');
    if (countEl) countEl.textContent = `${count} selected`;
    const est = document.getElementById('selectionEstimate');
    if (est) est.textContent = parts.join(' · ');
    if (btn && !btn.disabled) btn.textContent = `Download ${count} book${count !== 1 ? 's' : ''}`;
}

// ── Duplicate handling (frame 1c) ──

function _householdDuplicates(asins) {
    const household = AppState.get('household') || {};
    return AppState.get('library').filter(b => asins.has(b.asin) && household[b.asin] && household[b.asin].status === 'downloaded');
}

function _formatAdded(h) {
    if (!h || !h.added_at) return '—';
    const d = new Date(h.added_at * 1000);
    const months = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];
    let text = `${d.getDate()} ${months[d.getMonth()]}`;
    if (h.added_by) {
        const region = ((AppState.get('accountData') || {})[h.added_by] || {}).region;
        text += ` by ${h.added_by}` + (region ? ` (${region.toUpperCase()})` : '');
    }
    return text;
}

/** Ask what to do with one duplicate. Resolves 'skip' | 'keep'. */
function _askDuplicate(book, index, total) {
    return new Promise(resolve => {
        const modalEl = document.getElementById('duplicateModal');
        if (!modalEl || typeof bootstrap === 'undefined') { resolve('keep'); return; }
        const h = (AppState.get('household') || {})[book.asin] || {};
        const owner = book.account_name || _owners(book)[0] || 'this account';

        const cover = document.getElementById('dupCover');
        cover.className = 'dup-cover ' + (book.cover_url ? '' : _coverClass(book));
        cover.replaceChildren();
        if (book.cover_url) {
            const img = document.createElement('img');
            img.src = book.cover_url; img.alt = '';
            cover.appendChild(img);
        } else {
            cover.textContent = book.title || '';
        }
        document.getElementById('dupText').textContent =
            `${book.title} by ${book.authors || 'unknown author'} is already in your household library` +
            (h.added_by ? `, added through the Audible account “${h.added_by}”.` : '.');
        document.getElementById('dupLocation').textContent = h.location || '—';
        document.getElementById('dupAdded').textContent = _formatAdded(h);
        const abs = _absState(book);
        document.getElementById('dupAbsRow').hidden = !abs;
        const absEl = document.getElementById('dupAbs');
        absEl.textContent = abs ? (abs.label === 'In Audiobookshelf' ? 'Matched by ASIN' : abs.label) : '';
        absEl.className = abs && abs.cls === 'abs-ok' ? 'ok' : '';
        document.getElementById('dupSkipBtn').textContent = `Skip and mark as owned by ${owner}`;
        const step = document.getElementById('dupStep');
        step.hidden = total < 2;
        step.textContent = `${index + 1} of ${total} duplicates`;
        const always = document.getElementById('dupAlways');
        always.checked = false;

        const modal = bootstrap.Modal.getOrCreateInstance(modalEl);
        let answer = null;
        const skipBtn = document.getElementById('dupSkipBtn');
        const keepBtn = document.getElementById('dupKeepBtn');
        const finish = choice => { answer = choice; modal.hide(); };
        const onSkip = () => finish('skip');
        const onKeep = () => finish('keep');
        skipBtn.addEventListener('click', onSkip);
        keepBtn.addEventListener('click', onKeep);
        modalEl.addEventListener('hidden.bs.modal', function done() {
            modalEl.removeEventListener('hidden.bs.modal', done);
            skipBtn.removeEventListener('click', onSkip);
            keepBtn.removeEventListener('click', onKeep);
            if (always.checked && answer !== 'keep') {
                try { localStorage.setItem(_SKIP_DUPES_KEY, '1'); } catch (e) { /* private mode */ }
            }
            // Dismissing with Esc / backdrop keeps the book selected but skips this prompt.
            resolve(answer || 'cancel');
        });
        modal.show();
        setTimeout(() => skipBtn.focus(), 300);
    });
}

/** Removes skipped duplicates from the selection; returns false if the user backed out. */
function _recordSkippedDuplicates(books) {
    if (!books.length) return;
    // Best effort: feeds the household 'duplicates avoided' counter, never blocks the download.
    books.forEach(b => apiCall('/api/library/duplicates-skipped', {
        method: 'POST',
        body: JSON.stringify({ account_name: b.account_name || _owners(b)[0], items: [{ asin: b.asin, title: b.title }] })
    }).catch(() => {}));
}

async function _resolveDuplicates() {
    const selected = AppState.get('selectedAsins');
    const dupes = _householdDuplicates(selected);
    if (!dupes.length) return true;

    let alwaysSkip = false;
    try { alwaysSkip = localStorage.getItem(_SKIP_DUPES_KEY) === '1'; } catch (e) { /* ignore */ }
    if (alwaysSkip) {
        dupes.forEach(b => selected.delete(b.asin));
        _recordSkippedDuplicates(dupes);
        showToast(`Skipped ${dupes.length} household duplicate${dupes.length !== 1 ? 's' : ''}`, 'info', 4000);
        AppState.selectAll([]);
        return selected.size > 0;
    }

    for (let i = 0; i < dupes.length; i++) {
        const choice = await _askDuplicate(dupes[i], i, dupes.length);
        if (choice === 'cancel') return false;
        if (choice === 'skip') { selected.delete(dupes[i].asin); _recordSkippedDuplicates([dupes[i]]); }
        if (choice === 'skip' && (localStorage.getItem(_SKIP_DUPES_KEY) === '1')) {
            const rest = dupes.slice(i + 1);
            rest.forEach(b => selected.delete(b.asin));
            _recordSkippedDuplicates(rest);
            break;
        }
    }
    AppState.selectAll([]);
    return selected.size > 0;
}

// ── Download ──

async function downloadSelectedBooks() {
    if (AppState.get('selectedAsins').size === 0) {
        showToast('No books selected', 'warning');
        return;
    }
    if (AppState.get('currentLibraryName')) {
        const proceed = await _resolveDuplicates();
        if (!proceed) return;
    }
    const selectedAsins = AppState.get('selectedAsins');

    const libraryName = AppState.get('currentLibraryName');
    if (!libraryName) {
        const sel = document.getElementById('downloadLibrarySelect');
        if (sel) {
            sel.classList.add('is-invalid');
            setTimeout(() => sel.classList.remove('is-invalid'), 3000);
        }
        showToast('Please select a download library first', 'warning');
        return;
    }

    // Group selected ASINs by account_name
    const byAccount = {};
    for (const book of AppState.get('library')) {
        if (!selectedAsins.has(book.asin)) continue;
        const account = book.account_name;
        if (!account) continue;
        if (!byAccount[account]) byAccount[account] = [];
        byAccount[account].push(book.asin);
    }

    if (Object.keys(byAccount).length === 0) {
        showToast('Could not determine account for selected books', 'warning');
        return;
    }

    const btn = document.getElementById('downloadBtn');
    const count = selectedAsins.size;
    const restore = btn ? setButtonLoading(btn, `Adding ${count} to queue…`) : null;

    const cleanup_aax = AppState.get('cleanupAax');
    const promises = Object.entries(byAccount).map(([accountName, asins]) =>
        apiCall('/api/download/books', {
            method: 'POST',
            body: JSON.stringify({
                selected_asins: asins,
                account_name: accountName,
                cleanup_aax,
                library_name: libraryName
            })
        })
    );

    Promise.all(promises).then(() => {
        showToast(`${count} book${count !== 1 ? 's' : ''} added to queue`, 'success');
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
    if (e.detail.key === 'household' || e.detail.key === 'absConfigured') renderLibrary();
    if (e.detail.key === 'currentLibraryName') _updateSelectionBar();
    if (e.detail.key === 'isUnifiedView') renderLibrary();
    if (e.detail.key === 'accountData') _updateAuthUI();
});

document.addEventListener('appstate:filterschange', renderLibrary);

document.addEventListener('appstate:selectionchange', function () {
    const selected = AppState.get('selectedAsins');
    document.querySelectorAll('.book, .book-row').forEach(el => {
        const on = selected.has(el.dataset.asin);
        el.classList.toggle('selected', on);
        el.setAttribute('aria-checked', on);
    });
    _updateSelectionBar();
});

// Live download states change the status pills.
document.addEventListener('appstate:downloadschange', function () {
    if (document.getElementById('libraryGrid') && !document.getElementById('libraryContent').hidden) {
        clearTimeout(window._libRerender);
        window._libRerender = setTimeout(renderLibrary, 400);
    }
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

    const names = Object.keys(libraries);
    const pick = current && libraries[current] ? current : (names.length === 1 ? names[0] : '');
    if (pick) {
        select.value = pick;
        AppState.set('currentLibraryName', pick);
    }
}

function _updateViewButtons(mode) {
    [['cardViewBtn', 'card'], ['listViewBtn', 'list'], ['seriesViewBtn', 'series']].forEach(([id, m]) => {
        const btn = document.getElementById(id);
        if (!btn) return;
        btn.classList.toggle('active', mode === m);
        btn.setAttribute('aria-pressed', mode === m ? 'true' : 'false');
    });
}

// ── Account events ──

document.addEventListener('accounts:loaded', function (e) {
    const accounts = e.detail || {};
    const hasAuthenticated = Object.values(accounts).some(a => a.authenticated);
    if (hasAuthenticated) {
        fetchAllLibraries();
    } else {
        // No authenticated accounts — show onboarding or empty state
        _showLibraryUI(false);
    }
});

function _updateLoadButtons() {
    const accountData = AppState.get('accountData') || {};
    const hasAuthenticated = Object.values(accountData).some(a => a.authenticated);
    const refreshBtn = document.getElementById('refreshLibraryBtn');
    if (refreshBtn) refreshBtn.hidden = !hasAuthenticated;
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

function _updateAuthUI() {
    const accountData = AppState.get('accountData') || {};
    const hasAuthenticated = Object.values(accountData).some(a => a.authenticated);
    const downloadToSection = document.getElementById('downloadToSection');
    if (downloadToSection) downloadToSection.hidden = !hasAuthenticated;
    _updateLoadButtons();
}

// ── DOMContentLoaded ──

document.addEventListener('DOMContentLoaded', function () {
    // Search input
    // Debounced: re-filtering + re-rendering a big library on every keystroke janks typing.
    let searchTimer = null;
    document.getElementById('searchInput')?.addEventListener('input', function () {
        const value = this.value;
        clearTimeout(searchTimer);
        searchTimer = setTimeout(() => AppState.setFilter('search', value), 120);
    });

    // Account filter
    document.getElementById('accountFilter')?.addEventListener('change', function () {
        AppState.setFilter('account', this.value);
    });

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
    document.getElementById('seriesViewBtn')?.addEventListener('click', () => AppState.set('viewMode', 'series'));
    document.getElementById('sortSelect')?.addEventListener('change', function () {
        AppState.setFilter('sort', this.value);
    });
    document.getElementById('selectAllNewBtn')?.addEventListener('click', selectAllNew);

    // Select/clear all
    document.getElementById('selectAllVisibleBtn')?.addEventListener('click', selectAllVisible);
    document.getElementById('clearSelectionBtn')?.addEventListener('click', () => AppState.clearSelection());

    // Refresh library
    document.getElementById('refreshLibraryBtn')?.addEventListener('click', () => fetchAllLibraries(true));

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
        this.setAttribute('aria-expanded', tray && !tray.hidden ? 'true' : 'false');
    });
});
