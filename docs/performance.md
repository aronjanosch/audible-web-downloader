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
