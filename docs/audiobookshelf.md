# Audiobookshelf integration

Point Audiobookshelf at the same persistent library folder mounted by this app.
The default naming preset puts each M4B in its own book folder. Set these three
environment variables on the app (for Docker Compose, use a private `.env`):

| Variable | Value |
| --- | --- |
| `ABS_URL` | Audiobookshelf origin, such as `http://audiobookshelf:13378` |
| `ABS_API_TOKEN` | ABS API token for a user who can scan the target library |
| `ABS_LIBRARY_ID` | ABS library ID, such as `lib_...` |

All three are optional together. Without them, downloads and local library status
work normally. A partial configuration reports an integration error. Keep the
token private; it is sent only in the `Authorization: Bearer` header.

After each completed M4B, the app asks ABS to scan its library folders. A scan
request is asynchronous: success means ABS accepted the request, not that the
book is indexed. The app reconciles the ABS catalog every 15 minutes. Admins can
request a scan with `POST /api/audiobookshelf/scan`, then reconcile after indexing
with `POST /api/audiobookshelf/sync`. `GET /api/audiobookshelf/status` returns the
last match state beside each local book's own status. These endpoints require
the app's admin account.

Matching first uses an exact, case-insensitive ASIN. If ABS has no ASIN, a
unique normalized title can match when known authors agree. A different ABS
ASIN blocks title fallback. Multiple possible items are `ambiguous`, no item
is `pending`, an indexed item is `matched`, and an ABS `isMissing`/`isInvalid`
item is `missing`. The ABS state lives in `abs_items`; it never changes a local
book's `downloaded` status or deletes files. Correct metadata in ABS and sync
again to resolve an ambiguous item.

If ABS is offline, returns an error, or returns a catalog response with an
unsupported shape, reconciliation stops and preserves the last good state.
This permits a version difference without silently clearing links. Inspect the
app log and run a manual sync after upgrading ABS. The integration uses the
[documented scan endpoint](https://api.audiobookshelf.org/#scan-a-librarys-folders)
and [paginated library items endpoint](https://api.audiobookshelf.org/#get-a-librarys-items).
It does not alter ABS metadata or listening progress.
