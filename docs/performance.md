# v1 performance budget (server response proxy)

Measured on 2026-09-28 in this workspace with Python 3.13 and Flask's test
client, 51 requests after the app was initialized. An isolated empty SQLite
installation and an authenticated admin session were used for the working tree.
The baseline was `git archive HEAD` before v1 edits. Run `scripts/benchmark.py`
with `PYTHONPATH` set to the revision being measured.

| Route | Budget (p95) | Baseline median / p95 | Working tree median / p95 | Response bytes, before / after |
| --- | ---: | ---: | ---: | ---: |
| `GET /` | 25 ms | 0.301 / 0.352 ms | 0.369 / 0.416 ms | 26,672 / 27,164 |
| `GET /api/accounts` | 20 ms | 0.160 / 0.182 ms | 0.223 / 0.290 ms | 3 / 3 |

Both routes meet the local server response budget. The extra account guard adds
about 0.06 ms to the median API response in this empty test. These numbers are
**proxies**: they exclude a reverse proxy, network, external fonts and styles,
JavaScript execution, cover images, populated libraries, and actual browser paint.
A production deployment should remeasure against realistic household data.

---

# Loading-time optimisation (redesign release)

Measured 2026-09-29 on one laptop: headless Chrome, Python 3.13, Flask dev server on 127.0.0.1, **1,500-book
library** (fake data). All numbers are **proxies**: loopback has no network latency, so absolute times
understate the real-world gain from removing third-party round trips. Compare the columns, not the values.

## What changed

| Area | Change |
| --- | --- |
| Third-party requests | Bootstrap, Font Awesome and DM Sans are self-hosted (`static/vendor/`, pinned, licenses in `static/vendor/licenses/`). Zero CDN requests at runtime, so the app also works offline and behind a strict CSP. |
| Icons | The ~150 KB Font Awesome webfont is replaced by `static/css/icons.css` (23 KB raw, ~4 KB compressed): only the 45 glyphs in use, as CSS masks. Existing `<i class="fas fa-…">` markup is unchanged. Regenerate with `scripts/build_icons.py`. |
| Fonts | DM Sans latin subset, 4 woff2 files (14 KB each), `font-display: swap`, the two most used weights preloaded. |
| Compression | brotli / gzip via Flask-Compress (`utils/web_perf.py`). Server-sent events are never compressed. |
| Caching | First-party static URLs carry a content hash (`?v=`) and are `immutable` for a year. Vendor files are immutable by path. Everything else revalidates with ETag (a repeat visit costs 304s). |
| `/api/library/all` | The merged household catalog is cached per (account, cache write time) and rebuilt only when an account's library cache changes. It no longer re-upserts every purchase on every page load. |
| `/api/household/overview` | The activity query computed a correlated `MIN()` per row (O(n²)); it is now a single grouped CTE. |
| SQLite | `synchronous=NORMAL` (safe with WAL), 16 MiB page cache, in-memory temp store, mmap reads. |
| Library UI | Grid, list and series views render 120 books at once and append more as you scroll (identical behaviour: selection, counts and "Select all" are data-driven). Search is debounced (120 ms). Covers are `decoding="async"` and lazy. |
| Gunicorn | Still `workers = 1` (the download queue is an in-memory singleton, see `gunicorn.conf.py`). Threads raised to 32 (`GUNICORN_THREADS`) because every open admin tab holds one thread for its SSE stream. Keep-alive 30 s, heartbeat file on tmpfs. |
| Token health | `auth.json` is re-read only when its mtime changes. |

## Browser: before → after (median of 5 runs)

`Cold` = empty cache, `warm` = repeat visit. `KB` = bytes on the wire. LCP is Chrome's
largest-contentful-paint, `load` is `loadEventEnd`. "Before" is this same tree with the CDN head, no
compression/caching hooks, unchunked rendering and uncached library merge (see *Reproduce*).

| Page | Cold KB | Cold load ms | Cold LCP ms | Warm KB | Warm load ms | 3rd-party requests |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| `/` (library, 1,500 books) | 761 → **207** | 283 → **57** | 188 → **84** | 366 → **25** | 55 → **24** | 6 → **0** |
| `/downloads` | 223 → **174** | 230 → **55** | 200 → **64** | 33 → **10** | 36 → **24** | 5 → **0** |
| `/settings` | 476 → **194** | 184 → **53** | 100 → **56** | 262 → **21** | 36 → **23** | 5 → **0** |
| `/household` | 230 → **177** | 133 → **57** | 112 → **60** | 35 → **11** | 35 → **25** | 5 → **0** |

Request count went **up** by two per page (32 → 36 on the library page): the icon stylesheet and font
preloads are separate files. They are cached immutably, so this only affects the first visit; bundling
the JavaScript is the next step if it matters.

## Server: before → after (Flask test client, median / p95 ms, 1,500 books, 3 accounts)

| Route | Before | After | Response bytes |
| --- | ---: | ---: | ---: |
| `/api/library/all` | 25.8 / 29.3 | **0.20 / 0.37** | 432,121 (identical body) |
| `/api/household/overview` | 202.1 / 219.1 | **0.82 / 0.89** | 1,522 |
| `/api/library/household` | 1.62 / 1.80 | 1.44 / 1.49 | 80,810 |
| `/api/session` | 0.16 / 0.22 | 0.15 / 0.15 | 63 |
| `/` (HTML) | 0.44 / 0.50 | 0.44 / 0.46 | 26,963 |
| `/household`, `/settings`, `/downloads` (HTML) | ≈0.4 / 0.5 | ≈0.4 / 0.5 | 16–25 KB |

The 432 KB library JSON is 14 KB with brotli for this synthetic catalog (repetitive fake titles; a real
catalog with covers and descriptions compresses less). The test client sends no network traffic, so wire sizes
come from the browser table above.

## Reproduce

```bash
# Server latency (isolated temp install, fake data)
SECRET_KEY=bench PYTHONPATH=. uv run python scripts/benchmark.py            # BENCH_BOOKS=0 for the empty install

# Browser timings (fake data, throwaway config dir; needs Chrome and `npm ci` in scripts/browser)
E2E_BOOKS=1500 uv run python scripts/e2e_server.py 5630 &
(cd scripts/browser && RUNS=5 node perf.mjs http://127.0.0.1:5630 after)
```

The "before" columns were produced by copying the tree, restoring the CDN `<link>`/`<script>` tags and the
`@import` in `app.css`, deleting the `install_web_perf(app)` call, setting `LAZY_CHUNK = 1e9` in
`static/js/library.js`, making the merged-library lookup in `routes/auth.py` always miss, and restoring the
correlated subquery in `routes/household.py`, then running the same two commands against the copy.

## Not done (and why)

- **Connection reuse to Audible:** library fetches run in `asyncio.run()` per request, so a pooled client
  cannot outlive the call. The merged-library cache already avoids most fetches (6 h TTL); a persistent
  background event loop would be the next step.
- **JS/CSS bundling and minification:** files are small, compressed, immutable and cached; bundling would add
  a build step to a project that deliberately has none.
- **Bootstrap CSS purge:** 33 KB compressed, cached for a year; purging risks dropping classes that
  JavaScript adds at runtime.
- **Behind a reverse proxy:** let the proxy serve `/static/` directly and terminate HTTP/2; the response
  headers above are already proxy-cache friendly.
