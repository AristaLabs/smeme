/* Generic modal dismissal: click any element with data-dismiss-modal="<id>"
   to clear that container's contents (mirrors the HTMX pattern used to open
   modals by swapping HTML into the same container). */
document.body.addEventListener("click", function (event) {
  var target = event.target.closest("[data-dismiss-modal]");
  if (!target) return;
  var containerId = target.getAttribute("data-dismiss-modal");
  var container = containerId && document.getElementById(containerId);
  if (container) container.innerHTML = "";
});
