# QNR Routes

HTTP endpoints for the questionnaire system.

**Interactive docs (Swagger):** http://localhost:8000/api/docs

---

## Dashboard

### GET /qnr/dashboard

User's workflow dashboard (HTML).

**Auth:** Required

---

## Agentic generation

### GET /qnr/agentic/brief

Render the agentic generation wizard (research brief, uploads, options).

**Auth:** Required

**Response:** HTML page

### POST /qnr/agentic/generate

Start the agentic workflow (Phase 1 research). Accepts multipart form data with brief inputs and optional file uploads.

**Auth:** Required

**Response:** HTML partials (HTMX); the workflow uses LangGraph `interrupt()` for human-in-the-loop steps.

Further steps under `/qnr/agentic/*` include research submit, design review, and build. See route modules in `smeme/qnr/generation/agentic/routes/`.

---

## Session navigation

### GET /qnr/{qnr_id}/start

Start a new session for a QNR.

**Auth:** Required

**Response:** Redirects to first question

### POST /qnr/{qnr_id}/answer

Submit an answer and advance to the next node.

**Body:** Form data — `thread_id` (session), `answer`

**Auth:** Required

**Response:** HTML partial with next question or completion

### GET /qnr/session/{thread_id}/complete

View the session completion page.

**Auth:** Required

**Response:** HTML page

---

## Editor

### GET /qnr/{qnr_id}/editor

Open the workflow editor.

**Auth:** Required (must be author)

**Response:** HTML editor page

### POST /qnr/editor/{qnr_id}/node/create

Create a new node (question or conclusion).

**Auth:** Required (must be author)

### POST /qnr/editor/{qnr_id}/node/{node_id}/update

Update an existing node.

**Auth:** Required (must be author)

### POST /qnr/editor/{qnr_id}/node/{node_id}/delete

Delete a node (also removes its connected edges).

**Auth:** Required (must be author)

### POST /qnr/editor/{qnr_id}/edge/create

Create a conditional or default edge between two nodes.

**Auth:** Required (must be author)

### POST /qnr/editor/{qnr_id}/edge/delete

Delete an edge.

**Auth:** Required (must be author)

---

## Deploy (Tools)

### GET /qnr/{qnr_id}/editor?view=tools

Opens the Tools tab in the editor showing deploy status (Live / Stale / not built).

### POST /qnr/editor/{qnr_id}/publish

Run preflight checks and compile the workflow to a reasoning artifact. This is what **Deploy** triggers — it does **not** change gallery visibility. See [Deploy, validate & list](../../smeme/templates/docs/creator_dashboard.html) for the full flow.

**Auth:** Required (must be author and owner)

---

## Workflow management

### POST /qnr/{qnr_id}/archive

Archive a workflow (soft delete). Hides it from active list; restorable.

**Auth:** Required (must be author)

### POST /qnr/{qnr_id}/restore

Restore an archived workflow.

**Auth:** Required (must be author)

### POST /qnr/editor/{qnr_id}/create_version

Create a new editable version of a read-only (previously deployed) workflow.

**Auth:** Required (must be author)

---

## MCP discoverability

### POST /qnr/mcp/discoverable

Toggle Listed / Hidden for a deployed workflow.

**Body:** Form data — `qnr_id`, `discoverable` (bool)

**Auth:** Required (must be owner)

---

**See also:** [Auth Routes](auth-routes.md) | [Memo Routes](memo-routes.md)
