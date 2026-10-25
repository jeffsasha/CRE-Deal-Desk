// Keep the existing server-rendered forms and validation inside one native dialog.
(function () {
  if (document.body.hasAttribute("data-editor-page")) return;
  var dialog = document.getElementById("edit-dialog");
  if (!dialog || !dialog.showModal) return;
  var frame = dialog.querySelector("iframe"), title = dialog.querySelector("h2");
  var panelBody = dialog.querySelector(".edit-dialog-body"), heights = Object.create(null), currentForm;
  var closeButton = dialog.querySelector("button"), status = dialog.querySelector("[role=status]");
  var loadingText = status.textContent, feedbackKey = "dealdesk-editor-feedback";
  var opener, submitting = false, observer;

  // Redirected form pages consume Django flash messages; carry them to the refreshed parent.
  try {
    var feedback = JSON.parse(sessionStorage.getItem(feedbackKey) || "[]");
    sessionStorage.removeItem(feedbackKey);
    if (feedback.length) {
      var notices = document.createElement("div");
      notices.className = "messages";
      feedback.forEach(function (item) {
        var notice = document.createElement("div");
        notice.className = "notice " + item.tone;
        notice.textContent = item.text;
        notice.setAttribute("role", "status");
        notices.appendChild(notice);
      });
      document.querySelector("main.content").prepend(notices);
    }
  } catch (error) { /* Storage may be unavailable; form data is already saved server-side. */ }

  function busy(on) {
    submitting = on;
    closeButton.disabled = on;
    dialog.setAttribute("aria-busy", String(on));
  }
  function close() { if (!submitting) dialog.close(); }
  function failed() {
    busy(false);
    status.textContent = dialog.dataset.error;
    status.hidden = false;
    frame.hidden = true;
  }
  closeButton.addEventListener("click", close);
  dialog.addEventListener("cancel", function (event) { if (submitting) event.preventDefault(); });
  dialog.addEventListener("click", function (event) {
    var box = dialog.getBoundingClientRect();
    if (event.target === dialog && (event.clientX < box.left || event.clientX > box.right || event.clientY < box.top || event.clientY > box.bottom)) close();
  });
  dialog.addEventListener("close", function () {
    if (observer) observer.disconnect();
    document.body.classList.remove("editor-open");
    // Keep the form visible for the native exit transition; opening always loads a fresh form.
    if (opener && document.contains(opener)) opener.focus({preventScroll: true});
  });

  document.addEventListener("click", function (event) {
    var link = event.target.closest("a[data-editor]");
    if (!link || event.defaultPrevented || event.button !== 0 || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey || link.target === "_blank") return;
    if (!link.getAttribute("href") || link.getAttribute("href").charAt(0) === "#") return;
    var url = new URL(link.href, location.href);
    if (url.origin !== location.origin) return;
    event.preventDefault();
    opener = link;
    title.textContent = link.title || link.textContent.trim();
    status.textContent = loadingText;
    status.hidden = false;
    frame.hidden = true;
    busy(false);
    currentForm = url.pathname + url.search;
    panelBody.style.height = Math.min(heights[currentForm] || 560, Math.max(160, window.innerHeight - 124)) + "px";
    url.searchParams.set("editor", "1");
    frame.src = url.href;
    dialog.showModal();
    document.body.classList.add("editor-open");
    var progress = document.querySelector(".nprogress");
    if (progress) progress.classList.remove("on");
  });

  frame.addEventListener("error", failed);
  frame.addEventListener("load", function () {
    if (!dialog.open) return;
    var doc, url;
    try {
      url = new URL(frame.contentWindow.location.href);
      if (url.protocol === "about:") return;
      if (url.origin !== location.origin) { failed(); return; }
      doc = frame.contentDocument;
    } catch (error) { failed(); return; }
    if (!doc || !doc.body) { failed(); return; }
    if (!doc.body.hasAttribute("data-editor-page")) {
      if (submitting && url.searchParams.get("editor") !== "1" && doc.querySelector("main.content")) {
        try {
          sessionStorage.setItem(feedbackKey, JSON.stringify(Array.from(doc.querySelectorAll(".messages .notice")).map(function (notice) {
            return {text: notice.textContent.trim(), tone: notice.classList.contains("notice-error") ? "notice-error" : notice.classList.contains("notice-warn") ? "notice-warn" : "notice-success"};
          })));
        } catch (error) { /* The normal reload still updates all saved values. */ }
        dialog.close();
        location.reload();
      } else failed();
      return;
    }
    busy(false);
    status.hidden = true;
    frame.hidden = false;
    var heading = doc.querySelector(".page-head h1");
    if (heading) title.textContent = heading.textContent.trim();
    frame.title = title.textContent;
    var content = doc.querySelector("main.content");
    function resize() {
      var height = Math.max(160, Math.min(content.scrollHeight + 2, window.innerHeight - 124));
      heights[currentForm] = height;
      panelBody.style.height = height + "px";
    }
    if (observer) observer.disconnect();
    if (content) {
      observer = new ResizeObserver(resize);
      observer.observe(content);
      resize();
    }
    doc.addEventListener("click", function (event) {
      if (event.target.closest(".crumbs a, .form-actions a")) { event.preventDefault(); close(); }
    }, true);
    doc.addEventListener("submit", function (event) {
      if (event.defaultPrevented || event.target.method.toLowerCase() !== "post") return;
      if (submitting) { event.preventDefault(); return; }
      busy(true);
    });
    // Escape pressed inside an iframe does not always reach the parent dialog.
    doc.addEventListener("keydown", function (event) { if (event.key === "Escape") { event.preventDefault(); close(); } });
    var input = doc.querySelector("input:not([type=hidden]):not([disabled]), select:not([disabled]), textarea:not([disabled])");
    if (input) input.focus({preventScroll: true});
  });
})();
