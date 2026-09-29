/** household-badge.js — sets the attention count on the admin "Household" nav link. */
(function () {
    const badge = document.getElementById('householdNavBadge');
    if (!badge) return;
    fetch('/api/household/overview', { credentials: 'same-origin' })
        .then(r => (r.ok ? r.json() : null))
        .then(d => {
            const n = d && d.attention ? d.attention.length : 0;
            badge.textContent = String(n);
            badge.hidden = n === 0;
        })
        .catch(() => {});
})();
