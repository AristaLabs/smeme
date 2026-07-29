/* Delete-account confirmation phrase form (auth/_delete_account_step2.html):
   enable the submit button only once the typed phrase matches (case- and
   whitespace-insensitive), and disable it immediately on submit to prevent
   double-submits. Event-delegated on document.body (bound once via a guard
   flag) so it keeps working across repeated HTMX swaps of this modal. */
if (!window.__smemeDeleteAccountConfirmBound) {
  window.__smemeDeleteAccountConfirmBound = true;

  document.body.addEventListener("input", function (event) {
    var input = event.target.closest("[data-delete-account-phrase-input]");
    if (!input) return;
    var expected = (input.getAttribute("data-confirm-phrase") || "").trim().toLowerCase();
    var actual = input.value.trim().toLowerCase();
    var submitBtn = document.getElementById("delete-account-submit-btn");
    if (submitBtn) submitBtn.disabled = actual !== expected;
  });

  document.body.addEventListener("submit", function (event) {
    if (!event.target.closest("[data-delete-account-form]")) return;
    var submitBtn = document.getElementById("delete-account-submit-btn");
    if (submitBtn) submitBtn.disabled = true;
  });
}
