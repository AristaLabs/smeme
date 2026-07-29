/* Refresh the generation wizard brief panel when the server signals a change
   via HX-Trigger: refreshWizardBrief (see phase1_research.py). */
document.body.addEventListener("refreshWizardBrief", function () {
  var panel = document.querySelector(".main-panel-content");
  if (!panel || typeof htmx === "undefined") return;
  htmx.ajax("GET", "/decision-trees/agentic/brief-partial", {
    target: ".main-panel-content",
    swap: "innerHTML",
  });
});
