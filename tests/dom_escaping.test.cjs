const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const test = require('node:test');
const vm = require('node:vm');

const root = path.resolve(__dirname, '..');
const payload = '"><img src=x onerror=alert(1)>';

function harness() {
    const elements = new Map();
    const created = [];
    const makeElement = () => {
        const matches = new Map();
        const node = {
            innerHTML: '', textContent: '', className: '', dataset: {}, title: '',
            children: [],
            appendChild(child) { this.children.push(child); },
            addEventListener() {},
            querySelector(selector) {
                if (!matches.has(selector)) matches.set(selector, makeElement());
                return matches.get(selector);
            },
            querySelectorAll() { return []; },
            setAttribute() {},
        };
        created.push(node);
        return node;
    };
    const document = {
        createElement: makeElement,
        getElementById(id) {
            if (!elements.has(id)) elements.set(id, makeElement());
            return elements.get(id);
        },
        querySelectorAll() { return []; },
        addEventListener() {},
        dispatchEvent() {},
    };
    const context = vm.createContext({
        document, console, AppState: { get: () => ({}) },
        bootstrap: { Toast: class { show() {} } },
    });
    const load = (file) => vm.runInContext(fs.readFileSync(path.join(root, file), 'utf8'), context);
    return { context, elements, created, load };
}

test('toast messages are assigned as text', () => {
    const h = harness();
    h.load('static/js/ui.js');
    h.context.showToast(payload);
    const toast = h.elements.get('toastContainer').children[0];
    assert.doesNotMatch(toast.innerHTML, /onerror/);
    assert.equal(toast.querySelector('.toast-message').textContent, payload);
});

test('library names and paths never enter HTML parsing', () => {
    const h = harness();
    h.load('static/js/settings.js');
    h.context._renderLibraryList({ [payload]: { path: payload } });
    const item = h.elements.get('configuredLibraryList').children[0];
    assert.doesNotMatch(item.innerHTML, /onerror/);
    assert.equal(item.querySelector('.library-name').textContent, payload);
    assert.equal(item.querySelector('.library-path').textContent, payload);
});

test('download and import text is escaped before HTML parsing', () => {
    const h = harness();
    h.load('static/js/ui.js');
    h.load('static/js/downloads.js');
    h.load('static/js/importer.js');
    const item = h.context.document.createElement('div');
    h.context._updateDownloadItemEl(item, {
        title: payload, author: payload, error: payload,
        cover_url: payload, state: 'error', progress_percent: 0,
    });
    assert.doesNotMatch(item.innerHTML, /<img src=x onerror/);
    assert.match(item.innerHTML, /&lt;img/);

    h.context._renderScanResults([{
        file_path: payload, title: payload, author: payload, file_size: 1,
    }], 1, 1);
    const row = h.elements.get('scannedFilesTable').children[0];
    assert.doesNotMatch(row.innerHTML, /<img src=x onerror/);
    assert.match(row.innerHTML, /&lt;img/);
});

test('automation card and account list escape stored names and status', () => {
    const h = harness();
    h.load('static/js/ui.js');
    const template = fs.readFileSync(path.join(root, 'templates/settings.html'), 'utf8');
    const script = template.match(/<script>\s*([\s\S]*?)<\/script>/)[1];
    vm.runInContext(script, h.context);
    h.context._renderRulesRows = () => {};
    const card = h.context._buildAccountCard(payload, { region: payload }, {
        last_run_result: payload, rules: [],
    }, [payload]);
    assert.doesNotMatch(card.innerHTML, /<img src=x onerror/);
    assert.match(card.innerHTML, /&lt;img/);

    h.context.AppState.get = (key) => key === 'accountData'
        ? { [payload]: { region: 'us', authenticated: true } } : null;
    h.context._renderSettingsAccounts();
    const account = h.elements.get('settingsAccountList').children[0];
    assert.doesNotMatch(account.innerHTML, /<img src=x onerror/);
    assert.match(account.innerHTML, /&lt;img/);
});
