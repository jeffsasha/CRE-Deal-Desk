(function () {
  var panel = document.querySelector("[data-workflow-panel]");
  if (!panel) return;
  var summary = document.querySelector("[data-workflow-toggle]"), status = panel.querySelector("[data-workflow-status]");
  var storageKey = "dealdesk-checklist-" + panel.dataset.deal;
  function focusToggle() { summary.focus({preventScroll: true}); }
  function setOpen(value) {
    panel.dataset.open = String(value);
    panel.inert = !value;
    summary.setAttribute("aria-expanded", String(value));
    try { sessionStorage.setItem(storageKey, value ? "open" : "closed"); } catch (error) {}
  }
  function open() {
    var overview = document.querySelector('[data-deal-panel="overview"]');
    if (overview && overview.hidden) document.querySelector('[data-deal-tab="overview"]').click();
    setOpen(true); focusToggle();
  }
  function close() { setOpen(false); focusToggle(); }
  var startOpen = panel.hasAttribute("data-start-open");
  try { startOpen = startOpen || sessionStorage.getItem(storageKey) === "open"; } catch (error) {}
  setOpen(startOpen);
  summary.addEventListener("click", function () { if (panel.dataset.open === "true") close(); else open(); });
  panel.querySelector("[data-workflow-close]").addEventListener("click", close);
  function externalOpen(event) {
    if (!panel.isConnected || !event.target.closest("[data-workflow-open]")) return;
    event.preventDefault(); open();
  }
  function escape(event) {
    if (event.key === "Escape" && panel.dataset.open === "true" && panel.getClientRects().length && !document.querySelector("dialog[open]")) {
      event.preventDefault(); close();
    }
  }
  document.addEventListener("click", externalOpen);
  document.addEventListener("keydown", escape);
  document.addEventListener("workspace:before", function () {
    document.removeEventListener("click", externalOpen);
    document.removeEventListener("keydown", escape);
  }, {once: true});

  var queue = Promise.resolve(), pending = 0, failed = new Set();
  function renderRow(row) {
    var done = row.dataset.done === "true";
    row.classList.toggle("is-done", done);
    var input = row.querySelector("input");
    input.checked = done;
    input.disabled = panel.dataset.editable !== "true";
    row.classList.toggle("is-error", failed.has(row.dataset.key));
    var retry = row.querySelector("[data-workflow-retry]");
    retry.hidden = !failed.has(row.dataset.key);
    retry.disabled = panel.dataset.editable !== "true";
  }
  panel.querySelectorAll("[data-workflow-item]").forEach(renderRow);
  function save(row, state) {
    if (row.classList.contains("is-saving")) return;
    row.classList.add("is-saving");
    row.querySelectorAll("input, button").forEach(function (control) { control.disabled = true; });
    status.textContent = failed.size ? panel.dataset.error : panel.dataset.saving;
    status.classList.toggle("is-error", failed.size > 0);
    pending += 1;
    // Serialize saves so an older response cannot overwrite a newer progress count.
    queue = queue.then(async function () {
    try {
      var cookie = document.cookie.match(/(?:^|; )csrftoken=([^;]+)/);
      var response = await fetch(row.dataset.url, {method: "POST", headers: {"X-CSRFToken": cookie ? decodeURIComponent(cookie[1]) : "", "Content-Type": "application/x-www-form-urlencoded"}, body: new URLSearchParams({state: state})});
      if (!response.ok) throw new Error("Save failed");
      var data = await response.json();
      if (data.key !== row.dataset.key || typeof data.done !== "boolean" || typeof data.na !== "boolean") throw new Error("Invalid response");
      row.dataset.done = String(data.done);
      document.querySelectorAll("[data-workflow-count]").forEach(function (count) { count.textContent = data.completed + "/" + data.total; });
      data.stages.forEach(function (stage) {
        var count = panel.querySelector('[data-stage="' + stage.key + '"] [data-stage-count]');
        if (count) count.textContent = stage.done + "/" + stage.total;
      });
      failed.delete(row.dataset.key);
      delete row.dataset.retryState;
    } catch (error) {
      failed.add(row.dataset.key);
      row.dataset.retryState = state;
    } finally {
      row.classList.remove("is-saving");
      pending -= 1;
      renderRow(row);
      status.textContent = failed.size ? panel.dataset.error : pending ? panel.dataset.saving : panel.dataset.saved;
      status.classList.toggle("is-error", failed.size > 0);
    }
    });
  }
  panel.addEventListener("change", function (event) {
    var row = event.target.closest("[data-workflow-item]");
    if (row && event.target.matches('input[type="checkbox"]')) save(row, event.target.checked ? "done" : "todo");
  });
  panel.addEventListener("click", function (event) {
    var retry = event.target.closest("[data-workflow-retry]");
    if (retry) {
      var retryRow = retry.closest("[data-workflow-item]");
      save(retryRow, retryRow.dataset.retryState);
      return;
    }
  });
})();
