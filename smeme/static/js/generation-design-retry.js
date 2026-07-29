/* Retry AI design generation button (decision_tree/generation/_main_design_edit.html).
   This partial is swapped into .main-panel-content via HTMX (see
   generation-wizard.js's EventSource -> loadEditForm), re-executing this
   script tag each time — the click listener is bound once via a guard flag
   since it's delegated on document.body, but retryDesignGeneration() always
   re-reads the current button/thread-id from the live DOM. */
function retryDesignGeneration() {
  var btn = document.getElementById("retry-design-btn");
  var indicator = document.getElementById("retry-design-indicator");
  if (!btn) return;
  var threadId = btn.getAttribute("data-thread-id") || "";

  btn.disabled = true;
  if (indicator) indicator.style.display = "block";

  fetch("/decision-trees/agentic/retry-design", {
    method: "POST",
    headers: {
      "Content-Type": "application/x-www-form-urlencoded",
    },
    body: new URLSearchParams({ thread_id: threadId }),
  })
    .then(function (response) {
      return response.text();
    })
    .then(function (html) {
      document.querySelector(".main-panel").innerHTML = html;
    })
    .catch(function (error) {
      console.error("Retry failed:", error);
      alert("Retry failed. Please try again or refresh the page.");
      btn.disabled = false;
      if (indicator) indicator.style.display = "none";
    });
}

if (!window.__smemeRetryDesignBound) {
  window.__smemeRetryDesignBound = true;
  document.body.addEventListener("click", function (event) {
    if (event.target.closest('[data-action="retry-design-generation"]')) {
      retryDesignGeneration();
    }
  });
}
