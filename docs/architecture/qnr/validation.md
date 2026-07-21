# QNR Editor Validation Design

## Design Philosophy

### The Catch-22 Problem
Previously, validation errors blocked saves. This created an impossible situation:
- A graph with multiple errors couldn't be saved
- Authors couldn't fix errors incrementally
- They were locked out of their own QNRs

### Solution: Save-First Validation
The editor now follows a "save first, validate second" pattern:
- **All edits are saved** regardless of validation status
- **Validation errors are displayed** but don't block saves
- Authors can fix one error at a time without being locked out
- **Publishing is the gate** - errors must be fixed before going public

---

## Validation Behavior by Action

| Action | Validation | Save? | Behavior |
|--------|------------|-------|----------|
| Any edit (node/edge CRUD) | Run after save | ✅ Yes | Show errors/warnings in UI |
| Start/Answer QNR | Check on load | ❌ Block if errors | Error page with guidance |
| Set Public/Publish | Strict check | ❌ Block if any issues | Full error list |

### Why Block Answering?
If a user navigates to a broken node (e.g., edge pointing to non-existent "End"), the questionnaire breaks. Blocking at start time protects users from broken experiences.

### Why Allow Editing Broken Graphs?
Authors need to fix errors. If we block saves, they can never fix the graph. The validation UI shows what's wrong so they can address issues incrementally.

---

## Implementation Details

### Key Files

| File | Responsibility |
|------|----------------|
| `smeme/qnr/editor/workflow.py` | `validate_graph_node` always returns `success=True` |
| `smeme/qnr/editor/routes.py` | Routes check operation success only, not validation |
| `smeme/qnr/routes.py` | `start_qnr` blocks answering if validation errors exist |
| `smeme/qnr/helpers/validation.py` | Tier-2/Tier-3 validation; fix hints via `_ValidationContext` |
| `smeme/templates/qnr/_validation_issue_row.html` | Sidebar issue row (message + optional fix hint) |

### Workflow Node Change
```python
# Before: Blocked on validation errors
if not is_valid:
    return {"success": False, "error_message": "..."}

# After: Always proceed, pass validation results for display
return {
    "is_valid": is_valid,
    "errors": errors,
    "warnings": warnings,
    "success": True,  # Always proceed to save
}
```

### Route Change
```python
# Before: Checked both success AND is_valid
if not result.get("success", False) or not result.get("is_valid", True):
    return error_response

# After: Only check operation success
if not result.get("success", False):
    return error_response
# Validation errors are shown in UI via OOB swaps
```

---

## Real-time Validation UI Updates

### OOB Swap Elements
After any edit, HTMX Out-of-Band swaps update these elements:

| Element ID | Purpose |
|------------|---------|
| `#validation-badge` | Compact error/warning count in header |
| `#side-panel-validation` | Detailed validation panel at top of side panel |
| `#view-graph` | Graph SVG visualization (node colors for errors) |
| `#view-checklist` | Checklist view with per-node validation |
| `#warning-banner` | Collapsible warning messages |

### Helper Function
`render_editor_oob_swaps()` in `smeme/qnr/editor/routes.py` generates all OOB swap HTML.

All 6 edit routes use this helper:
- `create_node`, `update_node`, `delete_node`
- `create_edge`, `update_edge`, `delete_edge`

### Template Structure
```html
<!-- _side_panel.html -->
<div id="side-panel-validation">
  {% if validation_data.error_count > 0 or validation_data.warning_count > 0 %}
    {% include 'qnr/_validation_panel.html' %}
  {% endif %}
</div>
<div id="side-panel-content">
  <!-- Node editor, edge lists, etc. -->
</div>
```

The validation panel is **outside** `#side-panel-content` so it persists across node selections.

### Fix hints

Each issue in the sidebar validation list may show a **How to fix** line under the error or warning text.

| Property | Detail |
|----------|--------|
| Source | Programmatic strings at the validation call site in `validation.py` (`_ValidationContext.error` / `.warning`). |
| Transport | `ValidationResult.suggestions` — map of message text → hint. Passed to `build_validation_issue_rows()` as `ValidationIssueRow.suggestion`. |
| Scope | Tier-2 editor checks (`validate_graph_for_editing`). Agentic generation merges `BranchingDiagnostic.suggestion` in `validate_graph_for_generation`. |
| Not included | Publish preflight (`PreflightIssue` / SAT gate). No LLM; graph data is not sent externally for hints. |

When adding a new Tier-2 check, supply the hint in the same `ctx.error(...)` or `ctx.warning(...)` call as the message.

User-facing copy lives at `/docs/introduction` (Validation section). Bump `DOCS_VERSION` in `smeme/docs/constants.py` when that content changes.

---

## Templates Architecture

### Centralized Module
`smeme/core/templates.py` provides a shared Jinja2 instance with custom filters.

```python
from smeme.core.templates import templates  # Use this everywhere
```

### Custom Filters

**`natsort`** - Natural/human sorting
```jinja2
{# Wrong: q1, q10, q11, q2, q21, q3... #}
{{ items|sort(attribute='id') }}

{# Correct: q1, q2, q3, ..., q10, q11, ..., q21... #}
{{ items|natsort(attribute='id') }}
```

### Routes Migration
Routes should import from the shared module instead of creating local instances:
```python
# Before (each file)
from starlette.templating import Jinja2Templates
templates = Jinja2Templates(directory="smeme/templates")

# After
from smeme.core.templates import templates
```

Files migrated:
- `smeme/qnr/editor/routes.py` ✅
- `smeme/qnr/viewer/routes.py` ✅

---

## Edge Operation Patterns

### Condition Normalization
Edge conditions must be normalized before comparison:
- Empty string `""` → `None`
- Whitespace-only `"  "` → `None`

Both `update_edge` and `delete_edge` in `operations.py` do this:
```python
normalized_condition = condition.strip() if condition and condition.strip() else None
```

### Why This Matters
- HTML forms send `""` for empty inputs
- Database stores `None` for no condition
- Without normalization, edge lookup fails

### Lesson Learned
When matching edges, always normalize BOTH the stored value AND the incoming value before comparison:
```python
def edge_matches(e: GraphEdge) -> bool:
    e_condition = e.condition.strip() if e.condition and e.condition.strip() else None
    return (
        e.source == source
        and e.target == old_target
        and e_condition == normalized_old_condition
    )
```

---

## Error Messaging

### For Authors (their own broken QNR)
Detailed message with error count and link to editor:
```
Cannot Start: QNR Has Validation Errors
This questionnaire has 3 validation error(s) that must be fixed...
[Open in Editor] [Back to Dashboard]
```

### For Non-Authors (someone else's broken QNR)
Generic message (don't expose internal state):
```
Questionnaire Temporarily Unavailable
This questionnaire is currently being updated by its author.
[Back to Dashboard]
```
