document.querySelectorAll("[data-docs-copy]").forEach(function (button) {
  button.addEventListener("click", async function () {
    var node = document.getElementById(button.getAttribute("data-docs-copy"));
    if (!node) return;
    var previous = button.textContent;
    try {
      await navigator.clipboard.writeText(node.innerText.trim());
      button.textContent = "Copied";
    } catch (err) {
      button.textContent = "Select the prompt";
    }
    window.setTimeout(function () {
      button.textContent = previous;
    }, 1600);
  });
});
