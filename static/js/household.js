/** household.js — admin household overview (needs attention, members, activity). */
(function () {
    const AV = ['hh-av-0', 'hh-av-1', 'hh-av-2', 'hh-av-3', 'hh-av-4', 'hh-av-5'];

    function el(tag, cls, text) {
        const node = document.createElement(tag);
        if (cls) node.className = cls;
        if (text != null) node.textContent = text;
        return node;
    }

    function renderAttention(list) {
        const root = document.getElementById('hhAttention');
        root.replaceChildren();
        if (!list.length) {
            root.append(el('div', 'hh-ok', 'Everyone is connected. Nothing needs your attention.'));
            return;
        }
        list.forEach(item => {
            const expired = item.state === 'err';
            const card = el('div', 'hh-alert ' + (expired ? 'err' : 'warn'));
            const body = el('div', 'body');
            const title = expired
                ? (item.label === 'Not connected' ? `${item.name} has not connected Audible` : `${item.name}'s Audible connection expired`)
                : `${item.name}'s connection needs a refresh`;
            body.append(el('b', null, title), el('div', 'sub', item.detail));
            const btn = el('button', 'btn', expired ? 'Send link' : 'Remind now');
            btn.type = 'button';
            btn.addEventListener('click', () => openAccountInviteModal(item.name));
            card.append(body, btn);
            root.append(card);
        });
    }

    function renderMembers(list) {
        const root = document.getElementById('hhMembers');
        root.replaceChildren();
        if (!list.length) {
            root.append(el('div', 'hh-empty', 'No members yet. Add an Audible account or invite someone.'));
            return;
        }
        list.forEach((m, i) => {
            const card = el('div', 'hh-member');
            const av = el('div', 'avatar avatar-lg ' + AV[i % AV.length], m.initials);
            av.setAttribute('aria-hidden', 'true');
            const count = el('div', 'count', String(m.books));
            count.append(el('small', null, ' books'));
            const cls = { ok: 'pill-ok', warn: 'pill-warn', err: 'pill-err' }[m.state] || '';
            card.append(av, el('div', 'name', m.name), el('div', 'role', `${m.role} · ${m.region}`),
                        count, el('span', 'pill ' + cls, m.label));
            root.append(card);
        });
    }

    function renderActivity(list) {
        const root = document.getElementById('hhActivity');
        root.replaceChildren();
        if (!list.length) { root.append(el('div', 'hh-empty', 'Nothing has happened yet.')); return; }
        list.forEach(e => {
            const row = el('div', 'hh-event');
            row.append(el('span', 'dot ' + e.kind), el('div', 'txt', e.text), el('span', 'when', e.when));
            root.append(row);
        });
    }

    async function load() {
        try {
            const d = await apiCall('/api/household/overview');
            const s = d.summary;
            document.getElementById('hhSummary').textContent =
                `${s.members} member${s.members === 1 ? '' : 's'} · ${s.on_disk} books on disk · ${s.duplicates_avoided} duplicate${s.duplicates_avoided === 1 ? '' : 's'} avoided this week`;
            renderAttention(d.attention);
            renderMembers(d.members);
            renderActivity(d.activity);
        } catch (err) {
            document.getElementById('hhSummary').textContent = 'Could not load the household: ' + err.message;
        }
    }

    document.getElementById('hhInviteBtn')?.addEventListener('click', async () => {
        try { await loadInvitationLink(); } catch (e) { /* modal shows its own state */ }
        bootstrap.Modal.getOrCreateInstance(document.getElementById('familySharingModal')).show();
    });
    document.addEventListener('DOMContentLoaded', load);
})();
