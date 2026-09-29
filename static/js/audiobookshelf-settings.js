/** Admin controls for the optional Audiobookshelf catalog sync. */
(function () {
    const summary = document.getElementById('absSummary');
    const list = document.getElementById('absBookStatus');
    const scan = document.getElementById('absScanButton');
    const sync = document.getElementById('absSyncButton');
    if (!summary || !list) return;

    async function refresh() {
        try {
            const data = await apiCall('/api/audiobookshelf/status');
            scan.disabled = sync.disabled = !data.configured;
            if (!data.configured) {
                summary.textContent = 'Audiobookshelf is not configured. Add its URL, API token and library ID to your deployment environment.';
                list.replaceChildren();
                return;
            }
            const books = data.books || [];
            const matched = books.filter(book => book.abs_status === 'matched').length;
            const pending = books.filter(book => !book.abs_status || book.abs_status === 'pending').length;
            summary.textContent = `${matched} matched, ${pending} pending, ${books.length} local books.`;
            list.replaceChildren();
            for (const book of books.slice(0, 50)) {
                const item = document.createElement('li');
                item.className = 'list-group-item d-flex justify-content-between gap-2';
                const title = document.createElement('span');
                title.textContent = book.title;
                const status = document.createElement('span');
                status.className = 'badge text-bg-secondary align-self-center';
                status.textContent = book.abs_status || 'pending';
                item.append(title, status);
                list.append(item);
            }
            if (books.length > 50) {
                const item = document.createElement('li');
                item.className = 'list-group-item text-muted';
                item.textContent = `${books.length - 50} more books are available through the status API.`;
                list.append(item);
            }
        } catch (error) {
            summary.textContent = `Could not read Audiobookshelf status: ${error.message}`;
        }
    }

    async function perform(path, label) {
        summary.textContent = `${label}…`;
        try {
            await apiCall(path, { method: 'POST' });
            await refresh();
        } catch (error) {
            summary.textContent = `${label} failed: ${error.message}`;
        }
    }
    scan.addEventListener('click', () => perform('/api/audiobookshelf/scan', 'Requesting scan'));
    sync.addEventListener('click', () => perform('/api/audiobookshelf/sync', 'Refreshing matches'));
    document.getElementById('tab-audiobookshelf')?.addEventListener('shown.bs.tab', refresh);
    refresh();
})();
