// Loading-time measurement against scripts/e2e_server.py (fake data only).
//   E2E_BOOKS=1500 uv run python scripts/e2e_server.py 5630 &
//   node perf.mjs http://127.0.0.1:5630 [label]      env: CHROME_PATH, RUNS (default 5)
// Prints one JSON report: per page, cold (empty cache) and warm (repeat visit) medians of
// request count, transferred KB, third-party request count, DCL, load and LCP (ms).
import puppeteer from 'puppeteer-core';

const base = process.argv[2] || 'http://127.0.0.1:5630';
const label = process.argv[3] || 'run';
const chrome = process.env.CHROME_PATH || '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome';
const RUNS = Number(process.env.RUNS || 5);
const PAGES = ['/', '/downloads', '/settings', '/household'];
const median = a => [...a].sort((x, y) => x - y)[Math.floor(a.length / 2)];

const browser = await puppeteer.launch({ executablePath: chrome, headless: true, args: ['--no-sandbox'] });
const origin = new URL(base).origin;

async function login(page) {
  await page.goto(`${base}/login`, { waitUntil: 'networkidle2' });
  await page.type('input[name=username], #username', 'admin');
  await page.type('input[name=password], #password', 'e2e-admin-password-123');
  await Promise.all([page.waitForNavigation({ waitUntil: 'networkidle2' }), page.keyboard.press('Enter')]);
  // Seed one account + library so the library page renders the fake purchase list.
  await page.evaluate(async (base) => {
    const csrf = document.querySelector('meta[name=csrf-token]')?.content;
    const h = { 'Content-Type': 'application/json', 'X-CSRFToken': csrf };
    await fetch('/api/accounts', { method: 'POST', headers: h, body: JSON.stringify({ account_name: 'perf-account', region: 'us' }) });
    await fetch('/__e2e/authenticate/perf-account', { method: 'POST', headers: h });
    await fetch('/api/libraries', { method: 'POST', headers: h, body: JSON.stringify({ library_name: 'Audiobooks', library_path: '/tmp/perf-lib' }) });
  }, base);
}

async function measure(page, path, cold) {
  const client = await page.createCDPSession();
  await client.send('Network.enable');
  await client.send('Network.setCacheDisabled', { cacheDisabled: cold });
  let requests = 0, bytes = 0, third = 0;
  const seen = new Map();
  client.on('Network.requestWillBeSent', e => { requests++; seen.set(e.requestId, e.request.url); if (!e.request.url.startsWith(origin) && !e.request.url.startsWith('data:')) third++; });
  client.on('Network.loadingFinished', e => { bytes += e.encodedDataLength; });
  await page.evaluateOnNewDocument(() => {
    window.__lcp = 0;
    new PerformanceObserver(l => { for (const e of l.getEntries()) window.__lcp = e.startTime; }).observe({ type: 'largest-contentful-paint', buffered: true });
  });
  await page.goto(base + path, { waitUntil: 'networkidle2' });
  const t = await page.evaluate(() => {
    const n = performance.getEntriesByType('navigation')[0];
    return { ttfb: n.responseStart, dcl: n.domContentLoadedEventEnd, load: n.loadEventEnd, lcp: window.__lcp };
  });
  await client.detach();
  return { requests, kb: Math.round(bytes / 1024), third, ...t };
}

const report = { label, base, runs: RUNS, pages: {} };
try {
  const page = await browser.newPage();
  await page.setViewport({ width: 1280, height: 800 });
  await login(page);
  for (const path of PAGES) {
    const cold = [], warm = [];
    for (let i = 0; i < RUNS; i++) cold.push(await measure(page, path, true));
    await measure(page, path, false); // prime cache
    for (let i = 0; i < RUNS; i++) warm.push(await measure(page, path, false));
    const agg = rows => Object.fromEntries(Object.keys(rows[0]).map(k => [k, Math.round(median(rows.map(r => r[k])))]));
    report.pages[path] = { cold: agg(cold), warm: agg(warm) };
  }
} finally { await browser.close(); }
console.log(JSON.stringify(report, null, 1));
