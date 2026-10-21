// SKW DealDesk — small progressive enhancements. Every action also works without JS.
(function () {
  function csrf() {
    const m = document.cookie.match(/(?:^|; )csrftoken=([^;]+)/);
    return m ? decodeURIComponent(m[1]) : "";
  }

  // Mobile navigation
  document.addEventListener("click", function (e) {
    const t = e.target.closest("[data-toggle-nav]");
    if (t) { document.body.classList.toggle("nav-open"); return; }
    if (document.body.classList.contains("nav-open") && !e.target.closest(".sidebar")) {
      document.body.classList.remove("nav-open");
    }
  });

  // Confirmation for irreversible or significant actions
  document.addEventListener("submit", function (e) {
    const msg = (e.submitter && e.submitter.getAttribute("data-confirm")) || e.target.getAttribute("data-confirm");
    if (msg && !window.confirm(msg)) e.preventDefault();
  });

  // Column chooser: build ?cols= from checkboxes
  document.querySelectorAll("form[data-columns]").forEach(function (form) {
    form.addEventListener("submit", function () {
      const keys = Array.from(form.querySelectorAll("input[name=col]:checked")).map(function (i) { return i.value; });
      let hidden = form.querySelector("input[name=cols]");
      if (!hidden) { hidden = document.createElement("input"); hidden.type = "hidden"; hidden.name = "cols"; form.appendChild(hidden); }
      hidden.value = keys.join(",");
      form.querySelectorAll("input[name=col]").forEach(function (i) { i.disabled = true; });
    });
  });

  // Auto-submit filter selects
  document.querySelectorAll("[data-autosubmit]").forEach(function (el) {
    el.addEventListener("change", function () { el.form.submit(); });
  });

  // Deal board drag and drop (falls back to the stage form on each deal page)
  const board = document.querySelector("[data-board]");
  if (board) {
    let dragged = null;
    board.addEventListener("dragstart", function (e) {
      dragged = e.target.closest("[data-deal]");
      e.dataTransfer.effectAllowed = "move";
    });
    board.querySelectorAll("[data-stage]").forEach(function (col) {
      col.addEventListener("dragover", function (e) { e.preventDefault(); col.classList.add("drop"); });
      col.addEventListener("dragleave", function () { col.classList.remove("drop"); });
      col.addEventListener("drop", function (e) {
        e.preventDefault();
        col.classList.remove("drop");
        if (!dragged) return;
        const stage = col.getAttribute("data-stage");
        const needsReason = col.getAttribute("data-needs-reason") === "1";
        let reason = "";
        if (needsReason) {
          reason = window.prompt("Reason for moving this deal to " + col.getAttribute("data-stage-name") + ":") || "";
          if (!reason) return;
        }
        const body = new URLSearchParams({ stage: stage, reason: reason });
        fetch(dragged.getAttribute("data-stage-url"), {
          method: "POST",
          headers: { "X-CSRFToken": csrf(), "Content-Type": "application/x-www-form-urlencoded", "X-Requested-With": "fetch" },
          body: body.toString(),
        }).then(function (r) {
          if (r.ok) { col.appendChild(dragged); return; }
          return r.text().then(function (t) { window.alert(t || "Stage change was not allowed."); });
        });
      });
    });
  }

  // Document viewer: jump to page and highlight supporting text
  document.querySelectorAll("[data-goto-page]").forEach(function (btn) {
    btn.addEventListener("click", function (e) {
      e.preventDefault();
      const page = btn.getAttribute("data-goto-page");
      const frame = document.querySelector("[data-viewer-frame]");
      if (frame && frame.dataset.base) {
        // PDF viewers ignore a hash-only change; reload the frame at the new page.
        frame.src = "about:blank";
        setTimeout(function () { frame.src = frame.dataset.base + "#page=" + page; }, 30);
      }
      const textUrl = btn.getAttribute("data-text-url");
      const pane = document.querySelector("[data-page-text]");
      if (pane && textUrl) {
        fetch(textUrl).then(function (r) { return r.text(); }).then(function (html) {
          pane.innerHTML = html;
          const m = pane.querySelector("mark");
          if (m) m.scrollIntoView({ block: "center" });
        });
      }
      document.querySelectorAll("[data-page-label]").forEach(function (el) { el.textContent = "Page " + page; });
    });
  });
})();
