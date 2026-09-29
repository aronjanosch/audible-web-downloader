/** pw-meter.js — client-side password strength hint. Attach: <input data-pw-meter="#meterId"> */
(function () {
    function score(pw) {
        let s = 0;
        if (pw.length >= 12) s += 1;
        if (pw.length >= 16) s += 1;
        if (/[a-z]/.test(pw) && /[A-Z]/.test(pw)) s += 1;
        if (/\d/.test(pw)) s += 1;
        if (/[^A-Za-z0-9]/.test(pw)) s += 1;
        return pw ? Math.max(1, s) : 0;
    }
    const LEVELS = [
        ['', 0, 'var(--err)'], ['Too weak', 20, 'var(--err)'], ['Weak', 40, 'var(--orange)'],
        ['Okay', 60, 'var(--orange)'], ['Strong', 80, 'var(--green)'], ['Very strong', 100, 'var(--green)']
    ];
    document.querySelectorAll('[data-pw-meter]').forEach(function (input) {
        const meter = document.querySelector(input.dataset.pwMeter);
        if (!meter) return;
        const bar = meter.querySelector('span');
        const label = meter.parentElement.querySelector('.pw-meter-label');
        input.addEventListener('input', function () {
            const l = LEVELS[Math.min(5, score(input.value))];
            bar.style.width = l[1] + '%';
            bar.style.background = l[2];
            if (label) label.textContent = l[0];
        });
    });
})();
