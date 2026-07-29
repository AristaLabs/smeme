/* Delete-decision-tree confirmation phrase form
   (decision_tree/_delete_confirm_step2.html): enable the submit button only
   once the typed phrase exactly matches. Event-delegated on document.body
   (bound once via a guard flag) so it keeps working across repeated HTMX
   swaps of this modal. */
if (!window.__smemeDeleteTreeConfirmBound) {
  window.__smemeDeleteTreeConfirmBound = true;

  document.body.addEventListener("input", function (event) {
    var input = event.target.closest("[data-delete-tree-phrase-input]");
    if (!input) return;
    var expected = input.getAttribute("data-confirm-phrase") || "";
    var submitBtn = document.getElementById("delete-submit-btn");
    if (submitBtn) submitBtn.disabled = input.value !== expected;
  });
}
