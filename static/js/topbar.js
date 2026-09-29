/** topbar.js — user menu toggle, ⌘K jump palette hook. */
(function () {
    const btn = document.getElementById('userMenuBtn');
    const menu = document.getElementById('userMenu');
    if (btn && menu) {
        const close = () => { menu.hidden = true; btn.setAttribute('aria-expanded', 'false'); };
        btn.addEventListener('click', e => {
            e.stopPropagation();
            menu.hidden = !menu.hidden;
            btn.setAttribute('aria-expanded', String(!menu.hidden));
        });
        document.addEventListener('click', e => { if (!menu.contains(e.target)) close(); });
        document.addEventListener('keydown', e => { if (e.key === 'Escape') close(); });
    }
})();

/* Keep the active section visible when the nav scrolls horizontally on phones. */
(function () {
    const nav = document.querySelector('.topbar-nav');
    const cur = nav && nav.querySelector('[aria-current="page"], .active');
    if (cur && nav.scrollWidth > nav.clientWidth) nav.scrollLeft = cur.offsetLeft - 16;
})();
