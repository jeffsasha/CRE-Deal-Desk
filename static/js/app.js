// SKW DealDesk — progressive enhancements. Every action also works without JS.
(function () {
  var root = document.documentElement;
  var reduceMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;

  function csrf() {
    var m = document.cookie.match(/(?:^|; )csrftoken=([^;]+)/);
    return m ? decodeURIComponent(m[1]) : "";
  }

  // ---- Theme: light → dark → system, persisted per browser -----------------
  function storedTheme() {
    try { return localStorage.getItem("dd-theme") || "system"; } catch (e) { return "system"; }
  }
  function showThemeIcon(mode) {
    document.querySelectorAll("[data-theme-icon]").forEach(function (el) {
      el.hidden = el.getAttribute("data-theme-icon") !== mode;
    });
    var btn = document.querySelector("[data-theme-toggle]");
    if (btn) btn.title = "Theme: " + mode + " (click to change)";
  }
  function applyTheme(mode) {
    var commit = function () {
      if (mode === "system") root.removeAttribute("data-theme");
      else root.setAttribute("data-theme", mode);
      try { localStorage.setItem("dd-theme", mode); } catch (e) {}
      showThemeIcon(mode);
    };
    if (document.startViewTransition && !reduceMotion) {
      root.classList.add("theme-switching");
      var t = document.startViewTransition(commit);
      t.finished.finally(function () { root.classList.remove("theme-switching"); });
    } else {
      commit();
    }
  }
  showThemeIcon(storedTheme());
  document.addEventListener("click", function (e) {
    if (!e.target.closest("[data-theme-toggle]")) return;
    var order = ["light", "dark", "system"];
    applyTheme(order[(order.indexOf(storedTheme()) + 1) % order.length]);
  });

  // ---- Mobile navigation ----------------------------------------------------
  document.addEventListener("click", function (e) {
    if (e.target.closest("[data-toggle-nav]")) { document.body.classList.toggle("nav-open"); return; }
    if (document.body.classList.contains("nav-open") && !e.target.closest(".sidebar")) {
      document.body.classList.remove("nav-open");
    }
  });

  // ---- Navigation progress bar ----------------------------------------------
  var bar = document.querySelector(".nprogress");
  function startProgress() { if (bar) { bar.classList.remove("on"); void bar.offsetWidth; bar.classList.add("on"); } }
  document.addEventListener("click", function (e) {
    var a = e.target.closest("a[href]");
    if (!a || e.defaultPrevented || e.metaKey || e.ctrlKey || e.shiftKey || a.target === "_blank" || a.hasAttribute("download")) return;
    var href = a.getAttribute("href");
    if (!href || href.charAt(0) === "#" || href.indexOf("mailto:") === 0 || /\/documents\/file\//.test(href) || /\.(ics|csv)(\?|$)/.test(href) || /export=csv/.test(href)) return;
    startProgress();
  });
  window.addEventListener("pageshow", function () { if (bar) bar.classList.remove("on"); });

  // ---- Forms: confirmation, progress ------------------------------------------
  document.addEventListener("submit", function (e) {
    var msg = (e.submitter && e.submitter.getAttribute("data-confirm")) || e.target.getAttribute("data-confirm");
    if (msg && !window.confirm(msg)) { e.preventDefault(); return; }
    if ((e.target.method || "").toLowerCase() === "post") startProgress();
  });

  // Column chooser: build ?cols= from checkboxes
  document.querySelectorAll("form[data-columns]").forEach(function (form) {
    form.addEventListener("submit", function () {
      var keys = Array.prototype.map.call(form.querySelectorAll("input[name=col]:checked"), function (i) { return i.value; });
      var hidden = form.querySelector("input[name=cols]");
      if (!hidden) { hidden = document.createElement("input"); hidden.type = "hidden"; hidden.name = "cols"; form.appendChild(hidden); }
      hidden.value = keys.join(",");
      form.querySelectorAll("input[name=col]").forEach(function (i) { i.disabled = true; });
    });
  });
  // Checkboxes for the column chooser live inside a dropdown but belong to another form.
  document.querySelectorAll("input[name=col][form]").forEach(function (cb) {
    var f = document.getElementById(cb.getAttribute("form"));
    if (f && !f.hasAttribute("data-columns")) f.setAttribute("data-columns", "");
  });

  document.querySelectorAll("[data-autosubmit]").forEach(function (el) {
    el.addEventListener("change", function () { startProgress(); el.form.submit(); });
  });

  // Close open dropdowns on outside click / Escape
  document.addEventListener("click", function (e) {
    document.querySelectorAll("details.dropdown[open]").forEach(function (d) { if (!d.contains(e.target)) d.removeAttribute("open"); });
  });

  // ---- Clickable table rows (the first cell's link) ----------------------------
  document.querySelectorAll("table.t tbody tr").forEach(function (tr) {
    var first = tr.querySelector("td:first-child a[href]");
    if (!first) return;
    tr.setAttribute("data-href", first.getAttribute("href"));
  });
  document.addEventListener("click", function (e) {
    var tr = e.target.closest("tr[data-href]");
    if (!tr || e.target.closest("a, button, input, select, textarea, label, form, summary")) return;
    if (window.getSelection && String(window.getSelection()).length) return;
    var href = tr.getAttribute("data-href");
    if (e.metaKey || e.ctrlKey) { window.open(href, "_blank"); return; }
    startProgress();
    window.location.href = href;
  });

  // ---- Rolling numbers (odometer) ---------------------------------------------
  // The server renders the final text; each digit becomes a strip that rolls into
  // place when the number scrolls into view. Without JS the plain text stays.
  function buildOdometer(el) {
    var text = el.textContent.trim();
    if (!/\d/.test(text)) return null;
    el.setAttribute("aria-label", text);
    el.textContent = "";
    var strips = [];
    var digitsLeft = text.replace(/\D/g, "").length;
    Array.prototype.forEach.call(text, function (ch) {
      if (/\d/.test(ch)) {
        var cell = document.createElement("span");
        cell.className = "odo-d";
        cell.setAttribute("aria-hidden", "true");
        var strip = document.createElement("span");
        strip.className = "odo-strip";
        for (var i = 0; i < 20; i++) {
          var n = document.createElement("span");
          n.textContent = String(i % 10);
          strip.appendChild(n);
        }
        cell.appendChild(strip);
        el.appendChild(cell);
        digitsLeft -= 1;
        strips.push({ strip: strip, target: 10 + Number(ch), rank: digitsLeft });
      } else {
        var sep = document.createElement("span");
        sep.className = "odo-s";
        sep.setAttribute("aria-hidden", "true");
        sep.textContent = ch;
        el.appendChild(sep);
      }
    });
    return strips;
  }
  function rollOdometer(strips) {
    strips.forEach(function (s) {
      s.strip.style.transitionDelay = (s.rank * 70) + "ms";
      s.strip.style.transform = "translateY(" + (-s.target * 5) + "%)";
    });
  }
  var odos = document.querySelectorAll(".odo[data-odo]");
  if (odos.length && !reduceMotion) {
    var pending = [];
    odos.forEach(function (el) {
      var strips = buildOdometer(el);
      if (strips) { el._strips = strips; pending.push(el); }
    });
    var start = function (el) { requestAnimationFrame(function () { requestAnimationFrame(function () { rollOdometer(el._strips); }); }); };
    if ("IntersectionObserver" in window) {
      var io = new IntersectionObserver(function (entries) {
        entries.forEach(function (en) { if (en.isIntersecting) { start(en.target); io.unobserve(en.target); } });
      }, { threshold: 0.4 });
      pending.forEach(function (el) { io.observe(el); });
    } else {
      pending.forEach(start);
    }
  }

  // ---- Neon Reveal: end the ignition, re-light on click, card spotlight ----------
  // The ignition ends when the darkness has lifted; the timer is only a fallback.
  var IGNITE_MS = 4000;
  function endIgnite() { root.classList.remove("neon-igniting"); }
  if (root.classList.contains("neon-igniting")) setTimeout(endIgnite, IGNITE_MS);
  document.addEventListener("animationend", function (e) {
    if (e.animationName === "neon-veil-lift") endIgnite();
  });
  // Keep the tube just under the top bar (a demo banner above it scrolls away).
  var stage = document.querySelector("[data-neon]");
  var rail = document.querySelector("[data-neon-rail]");
  var veil = document.querySelector("[data-neon-veil]");
  var topbar = document.querySelector(".topbar");
  if (stage && rail && topbar) {
    var place = function () {
      var top = Math.max(0, Math.round(topbar.getBoundingClientRect().bottom)) + "px";
      stage.style.top = top;
      rail.style.top = top;
      // The darkness starts below the tube so the tube is seen switching on.
      if (veil) veil.style.top = (parseInt(top, 10) + 18) + "px";
    };
    place();
    window.addEventListener("scroll", place, { passive: true });
    window.addEventListener("resize", place);
  }
  var SPOT = ".card, .metric, .facts, .hero-band, .tile";
  document.addEventListener("pointermove", function (e) {
    var el = e.target.closest && e.target.closest(SPOT);
    if (!el) return;
    var r = el.getBoundingClientRect();
    el.style.setProperty("--mx", (e.clientX - r.left) + "px");
    el.style.setProperty("--my", (e.clientY - r.top) + "px");
  }, { passive: true });

  // ---- Timeline labels: measure real widths and place each label below the track,
  // else above it. Current dates go first; a date replaced by an extension gives way
  // (date only, then no label; its dot keeps a tooltip).
  function layoutTimeline(tl) {
    var rows = tl.querySelectorAll(".tl-marks");
    if (rows.length < 2) return;
    var row = { above: rows[0], below: rows[1] };
    var taken = { above: [], below: [] };
    var marks = Array.prototype.slice.call(tl.querySelectorAll(".tl-mark"));
    marks.sort(function (a, b) {
      return (a.classList.contains("is-was") - b.classList.contains("is-was")) || (a.dataset.pos - b.dataset.pos);
    });
    tl.classList.add("has-above");  // measure with both rows in place
    function tryRow(m, name) {
      row[name].appendChild(m);
      var r = m.getBoundingClientRect();
      var clear = taken[name].every(function (o) { return r.right + 8 <= o.left || r.left >= o.right + 8; });
      if (clear) taken[name].push({ left: r.left, right: r.right });
      return clear;
    }
    var used = false;
    marks.forEach(function (m) {
      m.classList.remove("is-tight", "is-hidden");
      if (tryRow(m, "below")) return;
      if (tryRow(m, "above")) { used = true; return; }
      m.classList.add("is-tight");
      if (tryRow(m, "below")) return;
      if (tryRow(m, "above")) { used = true; return; }
      if (m.classList.contains("is-was")) { m.classList.add("is-hidden"); row.below.appendChild(m); return; }
      tryRow(m, "below");
    });
    tl.classList.toggle("has-above", used);
  }
  var tls = document.querySelectorAll("[data-tl]");
  if (tls.length) {
    var layoutAll = function () { tls.forEach(layoutTimeline); };
    layoutAll();
    if (document.fonts && document.fonts.ready) document.fonts.ready.then(layoutAll);
    var tlTimer = 0;
    window.addEventListener("resize", function () { clearTimeout(tlTimer); tlTimer = setTimeout(layoutAll, 120); });
  }

  // ---- Auto-hide confirmations ------------------------------------------------
  document.querySelectorAll(".notice[data-autohide]").forEach(function (n) {
    setTimeout(function () {
      n.classList.add("leaving");
      setTimeout(function () { n.remove(); }, 400);
    }, 5000);
  });

  // ---- Deal board drag and drop (stage form on each deal page is the fallback) -
  var board = document.querySelector("[data-board]");
  if (board) {
    var dragged = null;
    board.addEventListener("dragstart", function (e) {
      dragged = e.target.closest("[data-deal]");
      if (!dragged) return;
      e.dataTransfer.effectAllowed = "move";
      requestAnimationFrame(function () { dragged.classList.add("dragging"); });
    });
    board.addEventListener("dragend", function () { if (dragged) dragged.classList.remove("dragging"); });
    board.querySelectorAll("[data-stage]").forEach(function (col) {
      col.addEventListener("dragover", function (e) { e.preventDefault(); col.classList.add("drop"); });
      col.addEventListener("dragleave", function (e) { if (!col.contains(e.relatedTarget)) col.classList.remove("drop"); });
      col.addEventListener("drop", function (e) {
        e.preventDefault();
        col.classList.remove("drop");
        if (!dragged) return;
        var card = dragged;
        var stage = col.getAttribute("data-stage");
        var reason = "";
        if (col.getAttribute("data-needs-reason") === "1") {
          reason = window.prompt("Reason for moving this deal to " + col.getAttribute("data-stage-name") + ":") || "";
          if (!reason) return;
        }
        var from = card.parentNode, next = card.nextSibling;
        var move = function () { col.appendChild(card); };
        if (document.startViewTransition && !reduceMotion) {
          card.style.viewTransitionName = "dragged-card";
          document.startViewTransition(move).finished.finally(function () { card.style.viewTransitionName = ""; });
        } else { move(); }
        card.classList.remove("dragging");
        card.classList.add("settle");
        setTimeout(function () { card.classList.remove("settle"); }, 400);
        fetch(card.getAttribute("data-stage-url"), {
          method: "POST",
          headers: { "X-CSRFToken": csrf(), "Content-Type": "application/x-www-form-urlencoded", "X-Requested-With": "fetch" },
          body: new URLSearchParams({ stage: stage, reason: reason }).toString(),
        }).then(function (r) {
          if (r.ok) return;
          from.insertBefore(card, next);  // revert
          return r.text().then(function (t) { window.alert(t || "Stage change was not allowed."); });
        });
      });
    });
  }

  // ---- Document viewer: jump to page and highlight supporting text ------------
  document.querySelectorAll("[data-goto-page]").forEach(function (btn) {
    btn.addEventListener("click", function (e) {
      e.preventDefault();
      var page = btn.getAttribute("data-goto-page");
      var frame = document.querySelector("[data-viewer-frame]");
      if (frame && frame.dataset.base) {
        // PDF viewers ignore a hash-only change; reload the frame at the new page.
        frame.src = "about:blank";
        setTimeout(function () { frame.src = frame.dataset.base + "#page=" + page; }, 30);
      }
      var textUrl = btn.getAttribute("data-text-url");
      var pane = document.querySelector("[data-page-text]");
      if (pane && textUrl) {
        fetch(textUrl).then(function (r) { return r.text(); }).then(function (html) {
          pane.innerHTML = html;
          var m = pane.querySelector("mark");
          if (m) m.scrollIntoView({ block: "center", behavior: reduceMotion ? "auto" : "smooth" });
        });
      }
      document.querySelectorAll("[data-page-label]").forEach(function (el) { el.textContent = "Page " + page; });
    });
  });

  // ---- Command palette (⌘K / Ctrl+K / "/") -----------------------------------
  var palette = document.querySelector("[data-cmdk]");
  if (palette) {
    var input = palette.querySelector("[data-cmdk-input]");
    var list = palette.querySelector("[data-cmdk-list]");
    var box = palette.querySelector(".cmdk");
    var icons = {};
    var tpl = document.getElementById("cmdk-icons");
    if (tpl) tpl.content.querySelectorAll("[data-i]").forEach(function (s) { icons[s.getAttribute("data-i")] = s.innerHTML; });
    var searchUrl = JSON.parse(document.getElementById("cmdk-search-url").textContent);
    var staticItems = [];
    document.querySelectorAll(".sidebar .nav a").forEach(function (a) {
      staticItems.push({ label: a.textContent.trim(), url: a.getAttribute("href"), group: box.getAttribute("data-t-nav") || "Navigate", svg: (a.querySelector("svg") || {}).outerHTML });
    });
    try { staticItems = staticItems.concat(JSON.parse(document.getElementById("cmdk-actions").textContent)); } catch (e) {}
    var results = [], active = 0, remote = [], timer = null, seq = 0;

    function esc(s) { var d = document.createElement("div"); d.textContent = s == null ? "" : s; return d.innerHTML; }
    function score(item, q) {
      var l = item.label.toLowerCase();
      if (!q) return 1;
      if (l.indexOf(q) === 0) return 3;
      if (l.indexOf(q) > -1) return 2;
      var i = 0;  // subsequence match ("ndl" → "New deal")
      for (var c = 0; c < l.length && i < q.length; c++) if (l[c] === q[i]) i++;
      return i === q.length ? 1 : 0;
    }
    function render() {
      var q = input.value.trim().toLowerCase();
      var local = staticItems.map(function (it) { return [score(it, q), it]; })
        .filter(function (p) { return p[0] > 0; })
        .sort(function (a, b) { return b[0] - a[0]; })
        .map(function (p) { return p[1]; });
      results = remote.concat(local);
      if (q) results.push({ label: (box.getAttribute("data-t-search") || "Search everything for") + " “" + input.value.trim() + "”", url: searchUrl + "?q=" + encodeURIComponent(input.value.trim()), group: box.getAttribute("data-t-sgroup") || "Search", icon: "search" });
      if (active >= results.length) active = Math.max(0, results.length - 1);
      var html = "", group = null;
      results.forEach(function (it, i) {
        if (it.group !== group) { group = it.group; html += '<div class="cmdk-group">' + esc(group) + "</div>"; }
        var icon = it.svg || icons[it.icon] || icons.arrow || "";
        html += '<div class="cmdk-item' + (i === active ? " active" : "") + '" role="option" data-i="' + i + '">' + icon +
          "<span>" + esc(it.label) + "</span>" + (it.hint ? '<span class="hint">' + esc(it.hint) + "</span>" : "") + "</div>";
      });
      list.innerHTML = html || '<div class="empty">' + esc(box.getAttribute("data-t-empty") || "No matches") + "</div>";
      var el = list.querySelector(".cmdk-item.active");
      if (el) el.scrollIntoView({ block: "nearest" });
    }
    function fetchRemote() {
      var q = input.value.trim();
      if (q.length < 2) { remote = []; render(); return; }
      var mine = ++seq;
      fetch(searchUrl + "quick/?q=" + encodeURIComponent(q), { headers: { "X-Requested-With": "fetch" } })
        .then(function (r) { return r.ok ? r.json() : { results: [] }; })
        .then(function (data) { if (mine === seq) { remote = data.results || []; render(); } });
    }
    function open() {
      palette.hidden = false;
      input.value = "";
      remote = [];
      active = 0;
      render();
      input.focus();
    }
    function close() { palette.hidden = true; }
    function choose(i) {
      var it = results[i];
      if (!it) return;
      close();
      if (it.theme) { applyTheme(it.theme); return; }
      startProgress();
      window.location.href = it.url;
    }
    input.addEventListener("input", function () { active = 0; render(); clearTimeout(timer); timer = setTimeout(fetchRemote, 140); });
    input.addEventListener("keydown", function (e) {
      if (e.key === "ArrowDown") { e.preventDefault(); active = Math.min(active + 1, results.length - 1); render(); }
      else if (e.key === "ArrowUp") { e.preventDefault(); active = Math.max(active - 1, 0); render(); }
      else if (e.key === "Enter") { e.preventDefault(); choose(active); }
      else if (e.key === "Escape") { close(); }
    });
    list.addEventListener("mousemove", function (e) {
      var item = e.target.closest(".cmdk-item");
      if (!item) return;
      var i = +item.getAttribute("data-i");
      if (i !== active) { active = i; list.querySelectorAll(".cmdk-item").forEach(function (n) { n.classList.toggle("active", +n.getAttribute("data-i") === i); }); }
    });
    list.addEventListener("click", function (e) { var item = e.target.closest(".cmdk-item"); if (item) choose(+item.getAttribute("data-i")); });
    palette.addEventListener("click", function (e) { if (e.target === palette) close(); });
    document.addEventListener("click", function (e) { if (e.target.closest("[data-cmdk-open]")) open(); });
    document.addEventListener("keydown", function (e) {
      var typing = /input|textarea|select/i.test((document.activeElement || {}).tagName || "") || (document.activeElement || {}).isContentEditable;
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "k") { e.preventDefault(); palette.hidden ? open() : close(); }
      else if (e.key === "/" && !typing && palette.hidden) { e.preventDefault(); open(); }
      else if (e.key === "Escape") {
        if (!palette.hidden) close();
        document.querySelectorAll("details.dropdown[open]").forEach(function (d) { d.removeAttribute("open"); });
      }
    });
  }
})();

// ---- Guided New Deal: reveal the questions that apply ------------------------
(function () {
  var form = document.querySelector("[data-new-deal]");
  if (!form) return;
  var labels = {};
  try { labels = JSON.parse(document.getElementById("client-labels").textContent); } catch (e) {}
  var summary = form.querySelector("[data-summary]");
  function val(name) { var el = form.querySelector('input[name="' + name + '"]:checked'); return el ? el.value : ""; }
  function sync() {
    var kind = val("kind"), mode = val("property_mode");
    form.querySelectorAll("[data-kind-only]").forEach(function (el) {
      var on = el.getAttribute("data-kind-only") === kind;
      el.hidden = !on;
      el.querySelectorAll('input[name="side"]').forEach(function (i) { i.disabled = !on; if (!on) i.checked = false; });
    });
    var side = val("side");
    form.querySelector("[data-needs-kind]").hidden = !kind;
    form.querySelector("[data-needs-side]").hidden = !(kind && side);
    form.querySelectorAll("[data-mode-only]").forEach(function (el) { el.hidden = el.getAttribute("data-mode-only") !== mode; });
    var pair = labels[kind + ":" + side] || ["", ""];
    var a = form.querySelector('[data-client-label="a"]'), b = form.querySelector('[data-client-label="b"]');
    if (a && pair[0]) a.textContent = pair[0];
    if (b) b.textContent = pair[1];
    form.querySelector("[data-client-b]").hidden = !pair[1];
    if (summary) {
      var k = form.querySelector('input[name="kind"]:checked'), s = form.querySelector('input[name="side"]:checked');
      summary.textContent = k && s ? "✓ " + k.closest(".tile").querySelector(".tile-title").textContent + " · " +
        s.closest(".tile").querySelector(".tile-title").textContent : "";
    }
  }
  form.addEventListener("change", sync);
  sync();
})();
