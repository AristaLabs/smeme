/* Generation wizard main panel (decision_tree/generation/_generation_layout.html):
   initial form (file upload, tabs, char counters), SSE research preview, and
   HTMX button loading states. Loaded once per page (this file lives in
   {% block scripts %}, not swapped by HTMX) — all interactive sub-partials
   inside .main-panel-content are handled here via delegation + re-init on
   htmx:afterSwap. */

// Character counter helper (used by initial form and research edit augment section)
function updateCharCounter(inputId, counterId, wrapperId, maxLen) {
    var el = document.getElementById(inputId);
    var counter = document.getElementById(counterId);
    var wrapper = document.getElementById(wrapperId);
    if (!el || !counter || !wrapper) return;
    var len = el.value.length;
    counter.textContent = len;
    wrapper.classList.remove('text-ui-ink-muted', 'text-yellow-600', 'text-red-600', 'font-semibold');
    if (len > maxLen) wrapper.classList.add('text-red-600', 'font-semibold');
    else if (len > maxLen * 0.9) wrapper.classList.add('text-yellow-600', 'font-semibold');
    else wrapper.classList.add('text-ui-ink-muted');
}

// --- Initial form (file upload, tabs, char counters) - runs on load and after HTMX swap ---
var INITIAL_FORM_MAX_FILES = 10;

function userMaterialsEnabled() {
    var cb = document.getElementById('enable_user_materials');
    return cb && cb.checked;
}

function setUserMaterialsInputsDisabled(disabled) {
    var panel = document.getElementById('user-materials-options');
    if (!panel) return;
    panel.querySelectorAll('input, textarea, button').forEach(function(el) {
        el.disabled = disabled;
    });
}

function updateUserMaterialsOptionsVisibility() {
    var checkbox = document.getElementById('enable_user_materials');
    var panel = document.getElementById('user-materials-options');
    if (!checkbox || !panel) return;
    if (checkbox.checked) {
        panel.classList.remove('hidden');
        setUserMaterialsInputsDisabled(false);
    } else {
        panel.classList.add('hidden');
        setUserMaterialsInputsDisabled(true);
    }
}

function updateWebSearchOptionsVisibility() {
    var checkbox = document.getElementById('enable_web_search');
    var panel = document.getElementById('web-search-options');
    if (!checkbox || !panel) return;
    if (checkbox.checked) panel.classList.remove('hidden');
    else panel.classList.add('hidden');
}

function updateAddFileButtonState() {
    var addBtn = document.getElementById('add-file-btn');
    var container = document.getElementById('file-rows-container');
    if (!addBtn || !container) return;
    var rows = container.querySelectorAll('.file-row');
    var atMax = rows.length >= INITIAL_FORM_MAX_FILES;
    var lastRow = rows[rows.length - 1];
    var lastInput = lastRow ? lastRow.querySelector('input[type="file"]') : null;
    var lastRowEmpty = lastRow && (!lastInput || !lastInput.files || lastInput.files.length === 0);
    addBtn.disabled = atMax || (rows.length > 0 && lastRowEmpty);
}

function addFileRow() {
    var container = document.getElementById('file-rows-container');
    if (!container) return;
    var rows = container.querySelectorAll('.file-row');
    if (rows.length >= INITIAL_FORM_MAX_FILES) return;
    var lastRow = rows[rows.length - 1];
    if (lastRow) {
        var lastInput = lastRow.querySelector('input[type="file"]');
        if (!lastInput || !lastInput.files || lastInput.files.length === 0) return;
    }
    var row = document.createElement('div');
    row.className = 'file-row flex items-center gap-2';
    row.innerHTML = '<input type="file" name="source_files" accept=".txt,.pdf,.docx" class="flex-1 text-sm text-ui-ink-muted file:mr-2 file:py-1.5 file:px-3 file:rounded file:border-0 file:text-sm file:font-medium file:bg-brand-50 file:text-brand-700 hover:file:bg-brand-100" /><button type="button" class="remove-file-btn text-red-600 hover:text-red-700 text-sm font-medium px-2 py-1">Remove</button>';
    container.appendChild(row);
    updateAddFileButtonState();
}

function initInitialForm() {
    var form = document.getElementById('generate-form');
    if (!form) return;
    var container = document.getElementById('file-rows-container');
    if (userMaterialsEnabled() && container && container.querySelectorAll('.file-row').length === 0) {
        addFileRow();
    }
    updateCharCounter('goal', 'goal-char-count', 'goal-counter', 400);
    updateCharCounter('title', 'title-char-count', 'title-counter', 200);
    updateUserMaterialsOptionsVisibility();
    updateWebSearchOptionsVisibility();
    updateAddFileButtonState();
}

// Event delegation for initial form (persists across HTMX swaps)
document.body.addEventListener('click', function(e) {
    var tabBtn = e.target.closest('.expert-tab');
    if (tabBtn && !tabBtn.disabled) {
        var tab = tabBtn.dataset.tab;
        document.querySelectorAll('.expert-tab').forEach(function(b) {
            b.classList.remove('text-brand-600', 'border-b-2', 'border-brand-600', '-mb-px');
            b.classList.add('text-ui-ink-muted');
        });
        tabBtn.classList.add('text-brand-600', 'border-b-2', 'border-brand-600', '-mb-px');
        tabBtn.classList.remove('text-ui-ink-muted');
        document.querySelectorAll('.expert-panel').forEach(function(panel) { panel.classList.add('hidden'); });
        var content = document.getElementById('content-' + tab);
        if (content) content.classList.remove('hidden');
        return;
    }
    if (e.target.closest('#add-file-btn')) {
        addFileRow();
        return;
    }
    var removeBtn = e.target.closest('.remove-file-btn');
    if (removeBtn) {
        var row = removeBtn.closest('.file-row');
        if (row) { row.remove(); updateAddFileButtonState(); }
    }
});

document.body.addEventListener('change', function(e) {
    if (e.target.id === 'enable_web_search') {
        updateWebSearchOptionsVisibility();
        return;
    }
    if (e.target.id === 'enable_user_materials') {
        updateUserMaterialsOptionsVisibility();
        if (userMaterialsEnabled()) {
            var container = document.getElementById('file-rows-container');
            if (container && container.querySelectorAll('.file-row').length === 0) {
                addFileRow();
            }
        }
    }
});

document.body.addEventListener('input', function(e) {
    if (e.target.id === 'goal') { updateCharCounter('goal', 'goal-char-count', 'goal-counter', 400); return; }
    if (e.target.id === 'title') { updateCharCounter('title', 'title-char-count', 'title-counter', 200); return; }
    if (e.target.name === 'source_files') { updateAddFileButtonState(); }
});

// Research SSE preview (Release 1) — minimal EventSource listener
var researchStreamSource = null;

function closeResearchStream() {
    if (researchStreamSource) {
        researchStreamSource.close();
        researchStreamSource = null;
    }
}

function initResearchStream() {
    var cfg = document.getElementById('research-stream-config');
    if (!cfg) return;
    closeResearchStream();
    var streamUrl = cfg.dataset.streamUrl;
    var editUrl = cfg.dataset.editUrl;
    var preview = document.getElementById('research-stream-preview');
    var statusEl = document.getElementById('research-stream-status');
    var errorEl = document.getElementById('research-stream-error');
    var cancelBtn = document.getElementById('research-stream-cancel-btn');
    if (!streamUrl || !preview) return;

    var sawComplete = false;
    var pendingError = null;

    function loadEditForm() {
        if (typeof htmx !== 'undefined') {
            htmx.ajax('GET', editUrl, { target: '.main-panel-content', swap: 'innerHTML' });
        } else {
            window.location.href = editUrl;
        }
    }

    if (cancelBtn) {
        cancelBtn.addEventListener('click', function() {
            var threadId = cfg.dataset.threadId;
            if (!threadId) return;
            cancelBtn.disabled = true;
            fetch('/decision-trees/agentic/generate/' + threadId + '/cancel', { method: 'POST', credentials: 'same-origin' });
        });
    }

    researchStreamSource = new EventSource(streamUrl);
    researchStreamSource.onmessage = function(ev) {
        var data;
        try { data = JSON.parse(ev.data); } catch (e) { return; }
        if (data.type === 'generation_started') return;
        if (data.type === 'heartbeat') return;
        if (data.type === 'status' && data.payload && data.payload.phase) {
            var phase = data.payload.phase;
            if (phase === 'tavily' && statusEl) statusEl.textContent = 'Searching the web…';
            else if (phase === 'llm' && statusEl) statusEl.textContent = 'Analyzing factors…';
            else if (phase === 'truncated_replay' && statusEl) statusEl.textContent = 'Reconnecting — older preview text omitted';
            return;
        }
        if (data.type === 'research_delta' && data.payload && data.payload.text) {
            preview.textContent += data.payload.text;
            return;
        }
        if (data.type === 'error' && data.payload) {
            pendingError = data.payload.message || 'Research failed';
            if (errorEl) {
                errorEl.textContent = pendingError;
                errorEl.classList.remove('hidden');
            }
            return;
        }
        if (data.type === 'research_complete') {
            sawComplete = true;
            closeResearchStream();
            loadEditForm();
        }
    };
    researchStreamSource.onerror = function() {
        if (!sawComplete && statusEl) statusEl.textContent = 'Connection lost — check in-progress wizard drafts on your dashboard to resume.';
    };
}

// Initialize augment counter on swap (scripts in HTMX response don't run)
document.body.addEventListener('htmx:afterSwap', function(event) {
    var augmentPrompt = document.getElementById('augment_prompt');
    if (augmentPrompt && !augmentPrompt.dataset.counterAttached) {
        augmentPrompt.dataset.counterAttached = 'true';
        augmentPrompt.addEventListener('input', function() {
            updateCharCounter('augment_prompt', 'augment-char-count', 'augment-counter', 400);
        });
        updateCharCounter('augment_prompt', 'augment-char-count', 'augment-counter', 400);
    }
    initInitialForm();
    initResearchStream();
});

document.addEventListener('DOMContentLoaded', function() {
    initInitialForm();
    initResearchStream();
    // Init augment counter on full-page load (e.g. direct navigation to research edit)
    var augmentPrompt = document.getElementById('augment_prompt');
    if (augmentPrompt && !augmentPrompt.dataset.counterAttached) {
        augmentPrompt.dataset.counterAttached = 'true';
        augmentPrompt.addEventListener('input', function() {
            updateCharCounter('augment_prompt', 'augment-char-count', 'augment-counter', 400);
        });
        updateCharCounter('augment_prompt', 'augment-char-count', 'augment-counter', 400);
    }

    // Add loading states to buttons during HTMX requests
    document.body.addEventListener('htmx:beforeRequest', function(event) {
        const button = event.detail.elt;
        if (button.tagName === 'BUTTON') {
            button.disabled = true;
            const originalText = button.innerHTML;
            button.setAttribute('data-original-text', originalText);
            button.innerHTML = '<span class="animate-spin">⏳</span> Processing...';
        }
    });

    document.body.addEventListener('htmx:afterRequest', function(event) {
        const button = event.detail.elt;
        if (button.tagName === 'BUTTON' && button.hasAttribute('data-original-text')) {
            button.disabled = false;
            button.innerHTML = button.getAttribute('data-original-text');
            button.removeAttribute('data-original-text');
        }
    });
});
