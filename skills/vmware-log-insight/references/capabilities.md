# vmware-log-insight Capabilities

VMware Aria Operations for Logs (vRealize Log Insight) public REST API v2,
base `https://<host>:9543/api/v2`, session auth (Bearer). All tools read-only.

| Tool | Endpoint | What it returns | Typical response tokens |
|---|---|---|---|
| `search_logs` | GET /events/{constraints} | `{count, complete, constraints, events:[{timestamp_ms, text, fields}]}` | 400–4000 (scales with limit) |
| `aggregate_logs` | GET /aggregated-events/{constraints} | `{aggregation, bin_width_ms, bins:[...], spikes:[...]}` | 200–1500 |
| `list_log_fields` | GET /fields | envelope of `[{name}]` | 100–800 |
| `get_log_insight_version` | GET /version | `{version, release_name, build}` | ~40 |
| `list_log_alerts` | GET /alerts | envelope of `[{id, name, enabled, info}]` | 100–1500 |
| `get_log_alert` | GET /alerts/{id} | `{id, name, enabled, info, raw_keys}` | 100–400 |
| `get_log_alert_history` | GET /alerts/{id}/history | envelope of `[{timestamp_ms, info}]` | 100–1500 |

## List envelope

`list_log_fields`, `list_log_alerts` and `get_log_alert_history` return the family list envelope
rather than a bare list — read the rows from `items`:

```json
{
  "items": [{"id": "a1", "name": "Disk full", "enabled": true, "info": ""}],
  "returned": 50,
  "limit": 50,
  "total": 213,
  "truncated": true,
  "hint": "Showing 50 of 213. Raise limit or narrow the query with a filter to see the rest."
}
```

`total` is a **real** count, never an estimate: the appliance returns each
collection in one GET and this package applies `limit` client-side, so the full
match count is already in hand. Two consequences worth relying on —

- `truncated: true` means rows were genuinely left behind; raise `limit` or
  narrow `name_filter`.
- A page that exactly fills `limit` is still reported `truncated: false` when it
  is genuinely the whole set, so no redundant follow-up query is needed.
- `list_log_fields` takes no `limit` at all, so it is always `truncated: false` —
  that is the complete field list, not a page of it.

## High-signal design

- **Search over list**: `search_logs` defaults to `limit=50` and a 1-hour window;
  narrow with `text`/filters rather than raising the limit. `complete=False`
  signals server-side truncation.
- **Spike detection in-tool**: `aggregate_logs` returns z-score-flagged `spikes[]`
  so the agent gets "where did logs burst?" without scanning raw events.
- **Field flattening**: Log Insight's `fields: [{name, content}]` is flattened to
  a `{name: content}` dict; all text is `sanitize()`d (truncated + control-char stripped).

## Auth & connection

- Session: `POST /api/v2/sessions {username, password, provider}` → `{sessionId, ttl}`;
  carried as `Authorization: Bearer <sessionId>`, re-acquired near TTL expiry.
- Errors are translated centrally to teaching `LogInsightApiError` (status + path +
  fix hint); transient 502/503/504 and transport errors get one retry, 401 triggers
  one re-auth, 4xx are not retried.

## Known limitations

- Exact v2 response schemas are parsed defensively across documented wire variants;
  they need confirmation against a live appliance's `/rest-api` reference (tracked in
  BACKLOG, same status as VKS `/wcp/login`).
- No ingest/write tools by design. Alert management (create/edit/delete) is out of scope.
