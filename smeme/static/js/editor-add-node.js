/* Add-node panel (decision_tree/_editor_add_node.html): toggle between the
   Question / Conclusion field sections and their required/disabled state.
   HTMX re-swaps this panel's HTML (and re-executes this script tag) when the
   side panel resets to its default view, so the delegated listener below is
   bound once (idempotent) while syncAddNodeKind() re-queries the live DOM by
   id on every call — safe to re-run after a swap. */
(function () {
  function syncAddNodeKind() {
    var q = document.getElementById("add-node-kind-question");
    var kind = q && q.checked ? "question" : "conclusion";
    var qs = document.getElementById("add-node-question-section");
    var cs = document.getElementById("add-node-conclusion-section");
    if (qs) qs.classList.toggle("hidden", kind !== "question");
    if (cs) cs.classList.toggle("hidden", kind !== "conclusion");
    function setDisabled(root, on) {
      if (!root) return;
      root.querySelectorAll("input, select, textarea").forEach(function (el) {
        if (el.name === "kind" || el.name === "decision_tree_id" || el.name === "panel_context_node_id") return;
        el.disabled = !on;
      });
    }
    setDisabled(qs, kind === "question");
    setDisabled(cs, kind === "conclusion");
    var ta = document.querySelector('#add-node-wired-form textarea[name="text"]');
    var ti = document.querySelector('#add-node-wired-form input[name="title"]');
    if (ta) ta.required = kind === "question";
    if (ti) ti.required = kind === "conclusion";
    var su = document.querySelector('#add-node-wired-form textarea[name="summary"]');
    if (su) su.required = kind === "conclusion";
  }

  if (!window.__smemeEditorAddNodeBound) {
    window.__smemeEditorAddNodeBound = true;
    document.body.addEventListener("change", function (event) {
      if (event.target.closest && event.target.closest('#add-node-wired-form input[name="kind"]')) {
        syncAddNodeKind();
      }
    });
  }

  syncAddNodeKind();
})();
