# Memo Routes

Memo generation endpoint.

## Base URL

Memo routes are prefixed with `/memo/`

---

## Generate Memo

### POST /memo/generate_memo

Generate an AI memo from a completed QNR session.

**Auth:** Required (must be session owner)

**Body:** Form data

| Field | Type | Description |
|-------|------|-------------|
| `session_id` | UUID string | ID of the completed QNR session |

**Response:** HTML partial with the generated memo (HTMX swap target)

**Notes:**
- Memos are cached by `session_id`. Re-submitting the same session returns the cached version.
- The session must be in a completed state (reached a conclusion node).

---

## View Memo

### GET /memo/{memo_id}

View an existing memo.

**Parameters:**
- `memo_id` (path) — UUID of the memo

**Auth:** Required (must be memo owner)

**Response:** HTML page with memo content

---

## Memo Data Structure

```python
class Memo(BaseSQLModel, table=True):
    id: uuid.UUID
    session_id: uuid.UUID       # FK to qnr_sessions
    user_id: uuid.UUID          # FK to users
    title: str
    content: str                # Structured text with sections
    metadata: dict              # qnr_id, qnr_title, completed_at
    created_at: datetime
```

---

**See also:** [QNR Routes](qnr-routes.md) | [Auth Routes](auth-routes.md)
