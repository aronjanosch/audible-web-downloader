// Browser proxies for GOAL.md item 5. Run against scripts/e2e_server.py (fake data only).
//   node checks.mjs [baseUrl]      env: CHROME_PATH
// Prints a JSON report; exits non-zero on any failed check.
import puppeteer from 'puppeteer-core';
import { createRequire } from 'node:module';
import { readFileSync, mkdirSync } from 'node:fs';

const require = createRequire(import.meta.url);
const axeSource = readFileSync(require.resolve('axe-core/axe.min.js'), 'utf8');
const base = process.argv[2] || 'http://localhost:5599';
const chrome = process.env.CHROME_PATH || '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome';
mkdirSync('out', { recursive: true });

const report = { base, checks: [] };
const record = (name, ok, detail) => { report.checks.push({ name, ok, detail }); };

async function axe(page, label) {
  await page.evaluate(axeSource);
  const result = await page.evaluate(() => axe.run(document, { resultTypes: ['violations'] }));
  const serious = result.violations.filter(v => ['critical', 'serious'].includes(v.impact));
  record(`axe ${label}`, !result.violations.some(v => v.impact === 'critical'), {
    critical: result.violations.filter(v => v.impact === 'critical').map(v => v.id),
    serious: serious.map(v => `${v.id} (${v.nodes.length})`),
    nodes: Object.fromEntries(serious.map(v => [v.id, v.nodes.slice(0, 4).map(n => n.target.join(' '))])),
    otherCount: result.violations.length - serious.length,
  });
}

async function noHorizontalScroll(page, label) {
  const m = await page.evaluate(() => ({ sw: document.documentElement.scrollWidth, cw: document.documentElement.clientWidth }));
  record(`360px no horizontal scroll ${label}`, m.sw <= m.cw, m);
}

const browser = await puppeteer.launch({ executablePath: chrome, headless: true, args: ['--no-sandbox'] });
try {
  const page = await browser.newPage();
  await page.setViewport({ width: 360, height: 780, deviceScaleFactor: 2, isMobile: true, hasTouch: true });
  const consoleErrors = [];
  page.on('pageerror', e => consoleErrors.push(String(e)));
  page.on('console', m => { if (m.type() === 'error') consoleErrors.push(m.text()); });
  page.on('response', r => { if (r.status() >= 400 && !r.url().includes('/__e2e/')) consoleErrors.push(`HTTP ${r.status()} ${r.url()}`); });

  // 1. Invite landing: axe + 360px.
  const t0 = Date.now();
  await page.goto(`${base}/invite/invited`, { waitUntil: 'networkidle2' });
  record('invite landing load ms (networkidle2, local)', true, Date.now() - t0);
  await axe(page, 'invite landing');
  await noHorizontalScroll(page, 'invite landing');
  await page.screenshot({ path: 'out/invite-360.png' });

  // 2. Keyboard-only onboarding: Tab to each field, type, submit with Enter. No mouse.
  await page.keyboard.press('Tab');
  const skip = await page.evaluate(() => document.activeElement.textContent.trim());
  record('first Tab stop (skip link expected)', /skip/i.test(skip), skip);
  const order = [];
  for (let i = 0; i < 12; i++) {
    const id = await page.evaluate(() => document.activeElement.id || document.activeElement.tagName);
    order.push(id);
    if (id === 'accountName') break;
    await page.keyboard.press('Tab');
  }
  record('keyboard reaches account form', order.includes('accountName'), order);
  await page.keyboard.type('e2e-member');
  await page.keyboard.press('Tab'); // username
  await page.keyboard.type('e2e-member');
  await page.keyboard.press('Tab');
  await page.keyboard.type('member-password-123');
  const focusVisible = await page.evaluate(() => {
    const s = getComputedStyle(document.activeElement);
    return s.outlineStyle !== 'none' || s.boxShadow !== 'none';
  });
  record('focus indicator visible on focused field', focusVisible);
  await Promise.all([page.waitForNavigation({ timeout: 15000 }).catch(() => null), page.keyboard.press('Enter')]);
  await new Promise(r => setTimeout(r, 1000));
  const landed = page.url();
  record('keyboard-only submit advanced to OAuth step', /\/auth\/login/.test(landed), landed);

  // 3. Fake the external Audible OAuth result, then log in as the member.
  await fetch(`${base}/__e2e/authenticate/e2e-member`, { method: 'POST' });
  const ctx2 = await browser.createBrowserContext();
  const member = await ctx2.newPage();
  await member.setViewport({ width: 360, height: 780, deviceScaleFactor: 2, isMobile: true, hasTouch: true });
  member.on('pageerror', e => consoleErrors.push(String(e)));
  member.on('response', r => { if (r.status() >= 400) consoleErrors.push(`HTTP ${r.status()} ${r.url()} [member]`); });
  await member.goto(`${base}/login`, { waitUntil: 'networkidle2' });
  await axe(member, 'login');
  await noHorizontalScroll(member, 'login');
  await member.type('input[name=username], #username', 'e2e-member');
  await member.type('input[name=password], #password', 'member-password-123');
  await Promise.all([member.waitForNavigation({ waitUntil: 'networkidle2' }), member.keyboard.press('Enter')]);
  const t1 = Date.now();
  await member.goto(`${base}/`, { waitUntil: 'networkidle2' });
  record('member home load ms (networkidle2, local)', true, Date.now() - t1);
  await new Promise(r => setTimeout(r, 1500));
  const text = await member.evaluate(() => document.body.innerText);
  record('E2E invite -> member sees own library book', /The Long Way Home/.test(text), text.slice(0, 200));
  await axe(member, 'member library');
  await noHorizontalScroll(member, 'member library');
  await member.screenshot({ path: 'out/member-360.png', fullPage: true });

  // 4. Admin pages at 360px + axe.
  const ctx3 = await browser.createBrowserContext();
  const admin = await ctx3.newPage();
  await admin.setViewport({ width: 360, height: 780, deviceScaleFactor: 2, isMobile: true, hasTouch: true });
  admin.on('pageerror', e => consoleErrors.push(String(e)));
  admin.on('response', r => { if (r.status() >= 400) consoleErrors.push(`HTTP ${r.status()} ${r.url()} [admin]`); });
  await admin.goto(`${base}/login`, { waitUntil: 'networkidle2' });
  await admin.type('input[name=username], #username', 'admin');
  await admin.type('input[name=password], #password', 'e2e-admin-password-123');
  await Promise.all([admin.waitForNavigation({ waitUntil: 'networkidle2' }), admin.keyboard.press('Enter')]);
  for (const path of ['/', '/settings', '/downloads', '/import']) {
    await admin.goto(`${base}${path}`, { waitUntil: 'networkidle2' });
    await axe(admin, `admin ${path}`);
    await noHorizontalScroll(admin, `admin ${path}`);
    await admin.screenshot({ path: `out/admin${path.replace('/', '-') || '-home'}-360.png`, fullPage: true });
  }
  record('no uncaught page errors', consoleErrors.length === 0, consoleErrors.filter(e => e.startsWith('HTTP') || !e.startsWith('Failed to load')).slice(0, 12));
} finally {
  await browser.close();
}
console.log(JSON.stringify(report, null, 2));
process.exit(report.checks.every(c => c.ok) ? 0 : 1);
