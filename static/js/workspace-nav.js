// Fetch fresh page content while keeping the sidebar, topbar and their listeners.
(function () {
  if (document.body.hasAttribute("data-editor-page") || !window.fetch || !window.AbortController) return;
  var main = document.querySelector("main.content");
  var links = Array.from(document.querySelectorAll(".sidebar a[data-workspace-nav]"));
  if (!main || !links.length) return;
  var paths = links.map(function (link) { return new URL(link.href).pathname; });
  var currentURL = location.href, controller = null, entrance;
  var scrollPositions = new Map();
  var reducedMotion = window.matchMedia("(prefers-reduced-motion: reduce)");
  history.scrollRestoration = "manual";

  function accepts(url) {
    return url.origin === location.origin && paths.includes(url.pathname) && !url.hash &&
      !url.searchParams.has("export") && !url.searchParams.has("editor");
  }

  function selectMenu(url) {
    var indicator = document.querySelector(".sidebar .nav-ind");
    var oldTop = indicator && indicator.getBoundingClientRect().top;
    var active;
    document.querySelectorAll(".sidebar .nav a").forEach(function (link) {
      var selected = new URL(link.href).pathname === url.pathname;
      link.classList.toggle("active", selected);
      if (selected) { link.setAttribute("aria-current", "page"); active = link; }
      else link.removeAttribute("aria-current");
    });
    if (!active) return;
    if (!indicator) { indicator = document.createElement("span"); indicator.className = "nav-ind"; }
    active.prepend(indicator);
    if (oldTop != null && !reducedMotion.matches) {
      indicator.animate([{transform: "translateY(" + (oldTop - indicator.getBoundingClientRect().top) + "px)"}, {transform: "none"}],
        {duration: 220, easing: "cubic-bezier(.2,.8,.2,1)"});
    }
  }

  async function navigate(url, fromHistory) {
    if (controller) controller.abort();
    if (entrance) entrance.cancel();
    var request = new AbortController();
    controller = request;
    scrollPositions.set(currentURL, [window.scrollX, window.scrollY]);
    main.classList.add("workspace-loading");
    main.setAttribute("aria-busy", "true");
    try {
      var response = await fetch(url, {headers: {"X-Workspace-Navigation": "1"}, cache: "no-store", signal: request.signal});
      if (request.signal.aborted) return;
      // Permissions, expired sign-in and non-workspace responses keep their normal behavior.
      if (!response.ok || response.redirected) { location.assign(response.url || url.href); return; }
      var doc = new DOMParser().parseFromString(await response.text(), "text/html");
      if (request.signal.aborted) return;
      var next = doc.querySelector("main[data-workspace-page]");
      if (!next || !next.dataset.workspacePage || next.querySelector("script") || doc.documentElement.lang !== document.documentElement.lang) {
        location.assign(url.href); return;
      }
      document.dispatchEvent(new Event("workspace:before"));
      main.replaceWith(next);
      main = next;
      document.title = doc.title;
      if (!fromHistory) history.pushState(null, "", url.href);
      currentURL = url.href;
      selectMenu(url);
      document.body.classList.remove("nav-open");
      document.dispatchEvent(new CustomEvent("workspace:content", {detail: main}));
      var scroll = fromHistory ? scrollPositions.get(currentURL) || [0, 0] : [0, 0];
      window.scrollTo({left: scroll[0], top: scroll[1], behavior: "instant"});
      var heading = main.querySelector("h1");
      if (heading) { heading.tabIndex = -1; heading.focus({preventScroll: true}); }
      if (!reducedMotion.matches) {
        entrance = main.animate([{opacity: 0, transform: "translateY(6px)"}, {opacity: 1, transform: "none"}],
          {duration: 180, easing: "cubic-bezier(.2,.8,.2,1)"});
      }
    } catch (error) {
      if (request.signal.aborted) return;
      if (fromHistory) { location.assign(url.href); return; }
      var previousError = main.querySelector("[data-workspace-error]");
      if (previousError) previousError.remove();
      var notice = document.createElement("div"), retry = document.createElement("a");
      notice.className = "notice notice-error";
      notice.setAttribute("role", "alert");
      notice.setAttribute("data-workspace-error", "");
      retry.href = url.href;
      retry.textContent = document.documentElement.lang.startsWith("zh") ? "暂时无法加载，点击重试。" : "Unable to load this page. Click to retry.";
      notice.appendChild(retry);
      main.prepend(notice);
    } finally {
      if (controller === request) {
        main.classList.remove("workspace-loading");
        main.removeAttribute("aria-busy");
        controller = null;
      }
    }
  }

  document.addEventListener("click", function (event) {
    var link = event.target.closest("a[href]");
    if (!link || event.defaultPrevented || event.button !== 0 || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey || link.target && link.target !== "_self" || link.hasAttribute("download") || link.hasAttribute("data-editor")) return;
    var url = new URL(link.href, location.href);
    if (!accepts(url)) return;
    event.preventDefault();
    if (url.href === currentURL && main.dataset.workspacePage) {
      if (controller) { controller.abort(); controller = null; }
      main.classList.remove("workspace-loading");
      main.removeAttribute("aria-busy");
      document.body.classList.remove("nav-open");
      return;
    }
    navigate(url, false);
  });

  document.addEventListener("submit", function (event) {
    var form = event.target;
    if (event.defaultPrevented || form.method.toLowerCase() !== "get" || form.target && form.target !== "_self") return;
    var url = new URL(form.action, location.href);
    url.search = new URLSearchParams(new FormData(form)).toString();
    if (event.submitter && event.submitter.name) url.searchParams.append(event.submitter.name, event.submitter.value);
    if (!accepts(url)) return;
    event.preventDefault();
    navigate(url, false);
  });

  window.addEventListener("popstate", function () {
    var url = new URL(location.href);
    if (accepts(url)) navigate(url, true);
    else if (url.pathname !== new URL(currentURL).pathname) {
      if (controller) controller.abort();
      location.assign(url.href);
    }
  });
})();
