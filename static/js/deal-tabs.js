// Panels are already rendered; switching never navigates or discards inputs.
(function () {
  var root = document.querySelector("[data-deal-tabs]");
  if (!root) return;
  var nav = root.querySelector('[role="tablist"]');
  var tabs = Array.from(nav.querySelectorAll("[data-deal-tab]"));
  var panels = Array.from(root.querySelectorAll("[data-deal-panel]"));
  var indicator = nav.querySelector(".deal-tabs-indicator");
  var body = root.querySelector(".deal-tab-panels");

  function moveIndicator() {
    var active = nav.querySelector('[aria-selected="true"]');
    indicator.style.width = Math.max(0, active.offsetWidth - 24) + "px";
    indicator.style.transform = "translateX(" + (active.offsetLeft + 12) + "px)";
  }

  function show(url, focus) {
    var key = url.searchParams.get("tab") || "overview";
    var active = tabs.find(function (tab) { return tab.dataset.dealTab === key; }) || tabs[0];
    // Keep enough space below the tab bar to avoid a scroll jump on shorter panels.
    body.style.minHeight = Math.max(0, window.innerHeight - body.getBoundingClientRect().top) + "px";
    tabs.forEach(function (tab) {
      var selected = tab === active;
      tab.classList.toggle("on", selected);
      tab.setAttribute("aria-selected", String(selected));
      tab.tabIndex = selected ? 0 : -1;
    });
    panels.forEach(function (panel) { panel.hidden = panel.dataset.dealPanel !== active.dataset.dealTab; });
    moveIndicator();
    if (focus || panels.some(function (panel) { return panel.hidden && panel.contains(document.activeElement); })) {
      active.focus({preventScroll: true});
    }
  }

  root.addEventListener("click", function (event) {
    var link = event.target.closest("a[href]");
    if (!link || event.defaultPrevented || event.button !== 0 || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey || link.target === "_blank" || link.hasAttribute("data-editor")) return;
    var url = new URL(link.href, location.href);
    if (url.origin !== location.origin || url.pathname !== location.pathname || !tabs.some(function (tab) { return tab.dataset.dealTab === url.searchParams.get("tab"); })) return;
    event.preventDefault();
    if (url.href !== location.href) history.pushState(null, "", url);
    show(url, !nav.contains(link));
  });

  nav.addEventListener("keydown", function (event) {
    var index = tabs.indexOf(event.target);
    if (index < 0 || !["ArrowLeft", "ArrowRight", "Home", "End"].includes(event.key)) return;
    event.preventDefault();
    var next = event.key === "Home" ? 0 : event.key === "End" ? tabs.length - 1 :
      (index + (event.key === "ArrowRight" ? 1 : -1) + tabs.length) % tabs.length;
    tabs[next].click();
    tabs[next].focus({preventScroll: true});
    var left = tabs[next].offsetLeft, right = left + tabs[next].offsetWidth;
    if (left < nav.scrollLeft) nav.scrollLeft = left;
    else if (right > nav.scrollLeft + nav.clientWidth) nav.scrollLeft = right - nav.clientWidth;
  });

  function restoreTab() { if (root.isConnected) show(new URL(location.href)); }
  window.addEventListener("popstate", restoreTab);
  var observer = new ResizeObserver(moveIndicator);
  observer.observe(nav);
  document.addEventListener("workspace:before", function () {
    observer.disconnect();
    window.removeEventListener("popstate", restoreTab);
  }, {once: true});
  moveIndicator();
  indicator.hidden = false;
})();
