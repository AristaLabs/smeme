/* Node editor auto-save status (decision_tree/_node_editor_form.html).
   Listeners are bound to this specific #node-editor-form element instance;
   HTMX replaces the whole form (and re-executes this script tag) on every
   node selection, so the old form/listeners are simply discarded with it. */
(function () {
  var form = document.getElementById("node-editor-form");
  var statusEl = document.getElementById("save-status");
  if (!form || !statusEl) return;

  form.addEventListener("htmx:beforeRequest", function () {
    statusEl.innerHTML = '<span class="text-brand-600 dark:text-brand-300">\u25cf Saving...</span>';
  });

  form.addEventListener("htmx:afterSwap", function () {
    statusEl.innerHTML = '<span class="text-green-600 dark:text-green-400">\u2713 Saved</span>';
    setTimeout(function () {
      statusEl.innerHTML = "";
    }, 2000);
  });

  form.addEventListener("htmx:afterRequest", function (evt) {
    var errorDisplay = document.getElementById("form-error-display");
    if (evt.detail.xhr.status === 422) {
      statusEl.innerHTML = '<span class="text-red-600 dark:text-red-400">\u26a0 Error</span>';
      if (errorDisplay) errorDisplay.innerHTML = evt.detail.xhr.responseText;
    } else if (evt.detail.xhr.status >= 400) {
      statusEl.innerHTML = '<span class="text-red-600 dark:text-red-400">\u26a0 Save failed</span>';
    } else if (errorDisplay) {
      errorDisplay.innerHTML = "";
    }
  });
})();
