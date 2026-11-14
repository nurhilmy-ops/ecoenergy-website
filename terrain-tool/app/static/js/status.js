// Polls the job status every 2 s and reloads the page once the screening finishes.
(function () {
  "use strict";
  var root = document.getElementById("job-status");
  if (!root || !window.fetch) return;
  var url = root.getAttribute("data-status-url");
  var text = document.getElementById("status-text");
  var last = root.getAttribute("data-status");
  var failures = 0;
  var messages = {
    queued: "Queued — your screening will start shortly…",
    running: "Analysing terrain and drawing your maps…"
  };

  function poll() {
    fetch(url, { credentials: "same-origin", cache: "no-store", headers: { "Accept": "application/json" } })
      .then(function (resp) {
        if (resp.status === 404) throw new Error("gone");
        if (!resp.ok) throw new Error("http " + resp.status);
        return resp.json();
      })
      .then(function (data) {
        failures = 0;
        if (data.status === "done" || data.status === "failed") {
          text.textContent = data.status === "done" ? "Your report is ready — loading…" : "The screening stopped — loading details…";
          window.location.reload();
          return;
        }
        if (data.status !== last && messages[data.status]) {
          text.textContent = messages[data.status];
          last = data.status;
        }
        window.setTimeout(poll, 2000);
      })
      .catch(function (err) {
        if (err && err.message === "gone") {
          text.textContent = "This report is no longer available. Please check My reports.";
          return;
        }
        failures += 1;
        if (failures > 2) text.textContent = "Still working… (connection hiccup, retrying)";
        window.setTimeout(poll, Math.min(2000 * failures, 10000));
      });
  }
  window.setTimeout(poll, 2000);
})();
