# MCP cost telemetry — operator guide

**Status:** Shipped (logging + Postgres persistence)  
**Last updated:** 2026-06-18  
**Code:** `smeme/mcp/invocation_telemetry.py`, `smeme/mcp/models.py` (`mcp_tool_invocations`)  
**Related:** [reasoning-workflow-pricing-model.md](../planning/reasoning-workflow-pricing-model.md) (**§10** full-stack margin: MCP + wizard + fixed + Stripe), [DR-3 P3 metering sprint](../planning/sprint-dr3-p3-mcp-rs-binding-metering.md)

---

## 1. What this records

Every **authenticated** MCP reasoning tool call (after `get_mcp_user` succeeds) emits:

1. A structured **log line** (`mcp_tool_invocation`) for aggregation in Render, Datadog, CloudWatch, etc.
2. An append-only **`mcp_tool_invocations`** row when persistence is enabled.

We record **server-side** work only (handler wall time, Z3 kernel time, workflow size). We do **not** log Cowork/Claude token usage or raw answers.

| Field | Purpose |
| ----- | ------- |
| `tool_name` | Which MCP tool ran |
| `outcome` | `ok` or stable `error.code` from tool JSON |
| `user_id` | Billable account |
| `qnr_id` | Workflow when applicable |
| `oauth_client_id` | Clerk OAuth app (`client_id` / `azp`) when present |
| `duration_ms` | Full handler wall time |
| `reasoning_ms` | Time inside `evaluate_reasoning` / blob evaluate (when measured) |
| `question_count`, `edge_count`, `answered_count` | Size buckets for p50/p95 COGS |
| `sat_calls` | Populated for `how_to_reach` when telemetry records solver search depth |
| `quota_weight` | Units toward plan allowance (see §3) |
| `internal_cost_units` | Ops COGS multiplier in logs + `cost_metadata` (may differ from quota) |
| `estimated_cost_usd_micros` | Internal COGS fudge (not customer-facing) |

**Logical metric name for dashboards:** `smeme_mcp_tool_invocation_total` (field `reasoning_metric` on the log extra).

---

## 2. Environment flags

| Variable | Default | Effect |
| -------- | ------- | ------ |
| `MCP_INVOCATION_TELEMETRY_ENABLED` | `true` | Master switch for logs + persist path |
| `MCP_INVOCATION_TELEMETRY_PERSIST` | `true` | When `false`, logs only (no DB rows) — **quota caps unenforceable** (see warning below) |
| `MCP_COST_BASELINE_USD_MICROS` | `200` | Fixed micro-USD per call in estimate ($0.0002) |
| `MCP_COST_USD_MICROS_PER_SECOND` | `800` | Micro-USD per second of wall time ($0.0008/s) |

> **⚠ `MCP_INVOCATION_TELEMETRY_PERSIST=false` disables quota enforcement.** The monthly usage sum (`sum_mcp_weighted_month`) reads from `mcp_tool_invocations` rows. With persist off, no rows are written, the sum stays zero, and all quota cap checks pass — every user appears to have unlimited allowance. The app **hard-fails at startup** if `MCP_ENABLED=true` and persist is off in a non-development environment.
>
> Use `MCP_INVOCATION_TELEMETRY_PERSIST=false` only in local dev when you prefer logs without DB writes, or in CI where the test suite sets `ENVIRONMENT=testing`.

**Persist failure alerting:** when a DB write fails after a successful tool call, the handler logs `mcp_invocation_persist_failed_total` at WARNING. Wire a log-metric alert on this key to detect silent under-metering.

---

## 3. Quota weights vs internal cost units

Landing plans quote a monthly **tool call** budget. Advanced tools consume **weighted** units (`quota_weight`). **Internal COGS** uses a separate multiplier (`INTERNAL_COST_UNITS_BY_TOOL`) so ops can see true server work (e.g. `what_if` ≈ 2.2× evaluate) even when the customer-facing weight is rounded (2.0).

| Tool | Quota weight | Internal COGS units | Notes |
| ---- | -----------: | ------------------: | ----- |
| `smeme_reasoning_evaluate` | 1.0 | 1.0 | Baseline |
| `smeme_reasoning_validate_answers` | 1.0 | 0.3 | Phase 1 ingest gate (no Z3); same quota as evaluate |
| `smeme_reasoning_evaluate_blob` | 1.25 | 1.3 | When enabled |
| `smeme_reasoning_what_if` | **2.0** | **2.2** | Two evaluates + diff |
| `smeme_reasoning_how_to_reach` | 2.5 | 3.0 | Solver search (conservative) |
| `smeme_reasoning_list`, `capabilities`, template tools | 0.0 | 0.0 | Ops visibility; not billed |

`estimated_cost_usd_micros` scales by **internal** units, not quota weight.

**Typical Cowork run:** the two-phase harness calls **`validate_answers`** then **`evaluate`** — **2.0** quota units on a clean first pass (1.0 each). Re-validates after the user fixes evidence each count as another 1.0.

**Outcome contract:** every persisted row should be `ok` or a stable `error.code`. `internal_error` is recorded when the tool wrapper catches an unhandled exception. `unknown` indicates a telemetry bug and should trigger an alert.

**Hybrid billing policy (A3-C, shipped):** customer allowance sums **`quota_weight`** on persisted rows. Server-side work bills even on some error outcomes (for example `stale_theory` after the graph-hash gate). Obvious client mistakes are **free** — `quota_weight` is zeroed on flush for outcomes in `MCP_CLIENT_ERROR_OUTCOMES` in `invocation_telemetry.py` (invalid `qnr_id`, malformed JSON, ingest hard-rejects, `not_found`, `not_discoverable`, etc.). Cheap owner/discoverability/dormant gates run **before** quota reservation so those failures never insert a row.

Weights live in `invocation_telemetry.py`. **Enforcement is shipped** — `smeme/billing/quota.py` hard-blocks MCP tool calls (weighted) when `current_sum + quota_weight` would exceed the tier cap (`quota_exceeded` tool error; denied calls are not persisted).

**Monthly weighted usage per user** (matches dashboard meter and enforcement — sum `quota_weight`, not `outcome = 'ok'` only):

```sql
SELECT
  date_trunc('month', created_at) AS month,
  user_id,
  sum(quota_weight) AS weighted_units
FROM mcp_tool_invocations
WHERE quota_weight > 0
GROUP BY 1, 2;
```

**Ops-only success-rate view** (not used for billing):

```sql
SELECT
  date_trunc('month', created_at) AS month,
  user_id,
  sum(quota_weight) AS billed_units,
  sum(CASE WHEN outcome = 'ok' THEN quota_weight ELSE 0 END) AS ok_weighted_units
FROM mcp_tool_invocations
GROUP BY 1, 2;
```

---

## 4. Using logs

### 4.1 Render / stdout

Filter JSON logs where message is `mcp_tool_invocation` or `reasoning_metric = smeme_mcp_tool_invocation_total`.

Useful dimensions:

- `tool_name`
- `outcome`
- `duration_ms`, `reasoning_ms`
- `quota_weight`
- `estimated_cost_usd_micros`

### 4.2 Example: p95 wall time by tool (Postgres)

```sql
SELECT
  tool_name,
  percentile_cont(0.50) WITHIN GROUP (ORDER BY duration_ms) AS p50_ms,
  percentile_cont(0.95) WITHIN GROUP (ORDER BY duration_ms) AS p95_ms,
  count(*) AS n
FROM mcp_tool_invocations
WHERE created_at >= now() - interval '14 days'
GROUP BY tool_name
ORDER BY p95_ms DESC;
```

Use **p95** (not average) when sizing bundled plan margins — see [pricing model §8](../planning/reasoning-workflow-pricing-model.md).

### 4.3 Example: internal COGS roll-up

```sql
SELECT
  date_trunc('day', created_at) AS day,
  sum(estimated_cost_usd_micros) / 1e6 AS est_usd
FROM mcp_tool_invocations
GROUP BY 1
ORDER BY 1;
```

Calibrate `MCP_COST_*` env vars once p50 handler times stabilize (~2 weeks of dogfood).

---

## 5. What we do not store

- Bearer tokens or JWT bodies
- `raw_answers_json`, evidence blobs, or report text
- PII beyond existing `users.id` linkage

Failed auth **before** `get_mcp_user` does not create a row (see auth telemetry in `smeme/mcp/auth_telemetry.py`).

---

## 6. Future refinements

| Item | When |
| ---- | ---- |
| ~~**Quota enforcement**~~ | **Shipped** — `smeme/billing/quota.py` hard caps; see [sprint-subscription-billing-quotas.md](../planning/sprint-subscription-billing-quotas.md) |
| **`sat_calls` / compile splits** | `how_to_reach` shipped; optional deeper compile telemetry still deferred |
| **Per-QNR size buckets** | Materialized view on `question_count × edge_count` |
| **Stripe Billing Meters** | Map `sum(quota_weight)` to subscription item |
| **Admin dashboard** | p50/p95 COGS cuts from §4.2 |
| **Retention job** | TTL or aggregate-and-drop raw rows (e.g. 90 days) |

Counterfactual quota weights shipped in `DEFAULT_QUOTA_WEIGHT_BY_TOOL`; re-check p95 after 1–2 weeks in production.

---

## 7. Migration

```bash
alembic upgrade head
```

Revision `c4d5e6f7a8b9` merges prior heads and creates `mcp_tool_invocations`.
