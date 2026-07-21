# Wizard generation funnel telemetry (Spike 1)

Operator guide for drop-off analysis after Spike 1 ships.

## Events

Persisted in `wizard_generation_events`:

| `event_type` | When |
|--------------|------|
| `wizard.phase.enter` | User lands on a wizard phase (brief, research, conclusions, design) |
| `wizard.phase.submit` | User submits/advances a phase (includes latency in `duration_ms`) |
| `wizard.phase.error` | Handler failure for a phase |
| `wizard.abandon` | TTL/stale cleanup removes an in-progress generation |
| `wizard.complete` | Workflow saved and finished (`phase=complete`) |

`event_metadata` JSON may include `source`, `action`, `qnr_id`, `reason`, etc.

Disable recording: `WIZARD_TELEMETRY_ENABLED=false`.

## HTTP report (superuser)

```http
GET /qnr/agentic/telemetry/report
```

Returns JSON with:

- `funnel_by_phase` — enters, submits, errors, drop-off count and %
- `submit_latency_by_phase` — avg/max ms for submit events
- `spike2_gate` — `ready_to_re_rank` when **50 completions** or **7 days** of data

## Manual SQL

Drop-off by phase:

```sql
SELECT phase,
       SUM(CASE WHEN event_type = 'wizard.phase.enter' THEN 1 ELSE 0 END) AS enters,
       SUM(CASE WHEN event_type = 'wizard.phase.submit' THEN 1 ELSE 0 END) AS submits,
       SUM(CASE WHEN event_type = 'wizard.phase.error' THEN 1 ELSE 0 END) AS errors
FROM wizard_generation_events
GROUP BY phase
ORDER BY phase;
```

Completion count (Spike 2 gate):

```sql
SELECT COUNT(*) AS completions
FROM wizard_generation_events
WHERE event_type = 'wizard.complete';
```

Days collecting:

```sql
SELECT EXTRACT(DAY FROM (NOW() - MIN(created_at))) AS days_collecting
FROM wizard_generation_events;
```

Submit latency p95 by phase:

```sql
SELECT phase,
       PERCENTILE_CONT(0.95) WITHIN GROUP (ORDER BY duration_ms) AS p95_ms,
       COUNT(*) AS samples
FROM wizard_generation_events
WHERE event_type = 'wizard.phase.submit' AND duration_ms IS NOT NULL
GROUP BY phase;
```

Thread-level funnel (single generation):

```sql
SELECT created_at, event_type, phase, duration_ms, event_metadata
FROM wizard_generation_events
WHERE thread_id = :thread_id
ORDER BY created_at;
```

## Spike 2 re-rank gate

Do not re-prioritize structured-editor work until:

- **50** `wizard.complete` events, **or**
- **7** calendar days since first event,

whichever comes first. Check `spike2_gate` in the report endpoint or run the SQL above.

## Observability

Workflow execution is **not** sent to LangSmith or other third-party tracing backends. Wizard events provide **product funnel** metrics (enter/submit/abandon) queryable in Postgres; use structured application logs for engineering debug.
