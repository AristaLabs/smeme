/* Small, generic same-origin behaviors driven by data-* attributes, wired up
   via event delegation so they work after HTMX swaps without re-binding.
   Replaces scattered onclick/onchange handlers (M-04 CSP hardening). */
(function () {
  document.body.addEventListener("click", function (event) {
    var backTarget = event.target.closest('[data-action="history-back"]');
    if (backTarget) {
      event.preventDefault();
      window.history.back();
      return;
    }

    var reloadTarget = event.target.closest('[data-action="reload"]');
    if (reloadTarget) {
      event.preventDefault();
      window.location.reload();
      return;
    }

    // Dashboard link inside a blocked-start modal: if it points at the page
    // already open (same path/search/hash), clear the modal and reload in
    // place instead of doing a no-op navigation.
    var reloadIfCurrent = event.target.closest("[data-reload-if-current-href]");
    if (reloadIfCurrent) {
      var href = reloadIfCurrent.getAttribute("href") || "";
      var here = window.location.pathname + window.location.search + window.location.hash;
      var hereNoHash = window.location.pathname + window.location.search;
      var herePathOnly = window.location.pathname;
      if (href === here || href === hereNoHash || href === herePathOnly) {
        event.preventDefault();
        var modal = document.getElementById("modal-container");
        if (modal) modal.innerHTML = "";
        window.location.reload();
      }
      return;
    }

    // data-confirm: block the default action (submit/navigate) unless the
    // user accepts the confirm() dialog. Works for both plain and
    // HTMX-enhanced forms because HTMX also waits on the native submit event,
    // which never fires once the triggering click's default action is
    // prevented.
    var confirmTarget = event.target.closest("[data-confirm]");
    if (confirmTarget) {
      var message = confirmTarget.getAttribute("data-confirm");
      if (message && !window.confirm(message)) {
        event.preventDefault();
        event.stopPropagation();
      }
    }
  });

  // data-submit-on-change: submit the owning form as soon as the field
  // changes (e.g. Listed/Hidden select).
  document.body.addEventListener("change", function (event) {
    var target = event.target.closest("[data-submit-on-change]");
    if (target && target.form) target.form.requestSubmit();
  });
})();
