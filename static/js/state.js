/**
 * state.js — AppState singleton: single source of truth for all UI state.
 * Uses DOM custom events so modules can react to changes without direct coupling.
 */

window.AppState = (function () {
    const _state = {
        currentAccount: null,
        accountData: {},           // { [name]: { region, authenticated } }
        isAuthenticated: false,
        isUnifiedView: false,

        library: [],               // full book list for current account
        selectedAsins: new Set(),
        libraryStateAsins: new Set(), // ASINs already in library (downloaded)

        libraries: {},             // configured download libraries
        currentLibraryName: null,

        namingSettings: null,
        cleanupAax: true,

        viewMode: 'card',          // 'card' | 'list'

        filters: {
            search: '',
            account: '',
            author: '',
            language: '',
            narrator: '',
            series: '',
            publisher: '',
            year: '',
            hideDownloaded: false
        },

        downloads: {},             // live data from SSE: { [asin]: downloadState }
        downloadStats: {}          // { active, queued, completed, failed }
    };

    function _emit(eventName, detail) {
        document.dispatchEvent(new CustomEvent(eventName, { detail }));
    }

    function get(key) {
        return _state[key];
    }

    function set(key, value) {
        _state[key] = value;
        _emit('appstate:change', { key, value });
    }

    function setFilter(filterKey, value) {
        _state.filters[filterKey] = value;
        _emit('appstate:filterschange', { filterKey, value });
    }

    function getFilters() {
        return { ..._state.filters };
    }

    function resetFilters() {
        Object.keys(_state.filters).forEach(k => {
            _state.filters[k] = typeof _state.filters[k] === 'boolean' ? false : '';
        });
        _emit('appstate:filterschange', {});
    }

    function countActiveFilters() {
        const f = _state.filters;
        let count = 0;
        if (f.search) count++;
        if (f.account) count++;
        if (f.author) count++;
        if (f.language) count++;
        if (f.narrator) count++;
        if (f.series) count++;
        if (f.publisher) count++;
        if (f.year) count++;
        if (f.hideDownloaded) count++;
        return count;
    }

    function updateDownloads(data) {
        _state.downloads = data.downloads || {};
        _state.downloadStats = data.stats || {};
        _emit('appstate:downloadschange', {
            downloads: _state.downloads,
            stats: _state.downloadStats
        });
    }

    function toggleSelection(asin) {
        if (_state.selectedAsins.has(asin)) {
            _state.selectedAsins.delete(asin);
        } else {
            _state.selectedAsins.add(asin);
        }
        _emit('appstate:selectionchange', { selectedAsins: _state.selectedAsins });
    }

    function clearSelection() {
        _state.selectedAsins.clear();
        _emit('appstate:selectionchange', { selectedAsins: _state.selectedAsins });
    }

    function selectAll(asins) {
        asins.forEach(a => _state.selectedAsins.add(a));
        _emit('appstate:selectionchange', { selectedAsins: _state.selectedAsins });
    }

    return {
        get,
        set,
        setFilter,
        getFilters,
        resetFilters,
        countActiveFilters,
        updateDownloads,
        toggleSelection,
        clearSelection,
        selectAll
    };
})();
