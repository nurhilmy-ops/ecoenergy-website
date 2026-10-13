// Upload page helpers: show which file was chosen, explain on the page (not in a browser bubble)
// when none was, and stop double submissions while the file uploads. The server repeats every check.
(function () {
  "use strict";
  var form = document.getElementById("upload-form");
  var input = document.getElementById("kml_file");
  var status = document.getElementById("file-status");
  var button = document.getElementById("run-button");
  if (!form || !input || !status || !button) return;

  function show(message, isError) {
    status.textContent = message;
    status.className = "file-status" + (isError ? " is-error" : " is-ok");
  }

  input.addEventListener("change", function () {
    var file = input.files && input.files[0];
    if (!file) { show("", false); return; }
    var ext = (file.name.split(".").pop() || "").toLowerCase();
    if (ext !== "kml" && ext !== "kmz") {
      show("“" + file.name + "” is not a .kml or .kmz file — please choose your site file.", true);
      return;
    }
    show("Selected: " + file.name + " (" + Math.max(1, Math.round(file.size / 1024)) + " KB)", false);
  });

  form.addEventListener("submit", function (event) {
    if (!input.files || !input.files.length) {
      event.preventDefault();
      show("Please press Choose File and pick your .kml or .kmz file first.", true);
      input.scrollIntoView({ behavior: "smooth", block: "center" });
      input.focus();
      return;
    }
    // Disable after the browser has captured the form data, so the click still submits.
    window.setTimeout(function () {
      button.disabled = true;
      button.textContent = "Uploading and starting your screening…";
    }, 0);
  });
})();
