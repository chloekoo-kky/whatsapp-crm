(function () {
    if (window.__appPullToRefreshBound) return;
    window.__appPullToRefreshBound = true;

    var THRESHOLD = 64;
    var MAX_PULL = 112;
    var startY = 0;
    var pulling = false;
    var dist = 0;
    var refreshing = false;
    var indicator = null;
    var label = null;

    function isMobileLayout() {
      return window.matchMedia("(max-width: 1023px)").matches;
    }

    function ensureIndicator() {
      indicator = document.getElementById("app-ptr-indicator");
      if (!indicator) {
        indicator = document.createElement("div");
        indicator.id = "app-ptr-indicator";
        indicator.className = "app-ptr-indicator";
        indicator.setAttribute("aria-hidden", "true");
        indicator.innerHTML =
          '<svg class="app-ptr-icon h-5 w-5 shrink-0" fill="none" stroke="currentColor" stroke-width="2" viewBox="0 0 24 24" aria-hidden="true"><path stroke-linecap="round" stroke-linejoin="round" d="M16.023 9.348h4.992v-.001M2.985 19.644v-4.992m0 0h4.992m-4.993 0l3.181 3.183a8.25 8.25 0 0013.803-3.7M4.031 9.865a8.25 8.25 0 0113.803-3.7l3.181 3.182m0-4.991v4.99"/></svg>' +
          '<span class="app-ptr-text text-xs font-medium">Pull to refresh</span>';
        document.body.appendChild(indicator);
      }
      label = indicator.querySelector(".app-ptr-text");
    }

    function setLabel(text) {
      if (label) label.textContent = text;
    }

    function eventElement(e) {
      var t = e.target;
      if (t && t.nodeType !== 1) t = t.parentElement;
      return t && t.closest ? t : null;
    }

    function shouldIgnore(el) {
      if (!el) return true;
      if (document.body.classList.contains("mobile-nav-open")) return true;
      if (document.body.classList.contains("lead-group-drawer-open")) return true;
      if (document.querySelector("dialog[open]")) return true;
      if (el.closest("#app-sidebar, #chat-modal-container, .lead-group-drawer-panel")) return true;
      if (el.closest("input, textarea, select, [contenteditable='true']")) return true;
      return false;
    }

    function scrollableAncestorsAtTop(el) {
      var node = el;
      while (node && node !== document.body && node !== document.documentElement) {
        var style = window.getComputedStyle(node);
        var overflowY = style.overflowY;
        var canScroll =
          (overflowY === "auto" || overflowY === "scroll") &&
          node.scrollHeight > node.clientHeight + 2;
        if (canScroll && node.scrollTop > 1) return false;
        node = node.parentElement;
      }
      return (window.scrollY || document.documentElement.scrollTop || 0) <= 1;
    }

    function leadsContent() {
      return document.getElementById("leads-ptr-content");
    }

    function setDist(nextDist) {
      dist = Math.max(0, Math.min(nextDist, MAX_PULL));
      ensureIndicator();
      indicator.style.height = dist > 0 ? dist + "px" : "0px";
      indicator.style.opacity = dist > 0 ? "1" : "0";
      indicator.classList.toggle("app-ptr--ready", dist >= THRESHOLD && !refreshing);
      indicator.classList.toggle("app-ptr--refreshing", refreshing);
      if (!refreshing) {
        setLabel(dist >= THRESHOLD ? "Release to refresh" : "Pull to refresh");
      }
      var content = leadsContent();
      if (content) {
        content.style.transform = dist > 0 ? "translateY(" + dist + "px)" : "";
      }
      var scroll = document.getElementById("leads-scroll-container");
      if (scroll) {
        scroll.classList.toggle("leads-ptr--pulling", pulling && dist > 0);
        scroll.classList.toggle("leads-ptr--ready", dist >= THRESHOLD && !refreshing);
        scroll.classList.toggle("leads-ptr--refreshing", refreshing);
      }
    }

    function resetPull() {
      pulling = false;
      if (!refreshing) {
        setDist(0);
        var content = leadsContent();
        if (content) content.style.transform = "";
      }
    }

    async function refresh() {
      if (refreshing) return;
      refreshing = true;
      ensureIndicator();
      indicator.classList.add("app-ptr--refreshing");
      indicator.classList.remove("app-ptr--ready");
      setLabel("Refreshing…");
      setDist(Math.max(dist, THRESHOLD * 0.7));
      try {
        var view = (document.getElementById("workspace-root") || {}).getAttribute("data-view") || "";
        if (view === "dashboard" && typeof window.__refreshCurrentLeadFolder === "function") {
          await window.__refreshCurrentLeadFolder();
          if (typeof window.__refreshFunnelMetricsStrip === "function") {
            await window.__refreshFunnelMetricsStrip();
          }
        } else {
          window.location.reload();
        }
      } catch (err) {
        console.error(err);
      } finally {
        refreshing = false;
        if (indicator) indicator.classList.remove("app-ptr--refreshing");
        resetPull();
      }
    }

    document.addEventListener(
      "touchstart",
      function (e) {
        if (!isMobileLayout() || refreshing) return;
        var el = eventElement(e);
        if (shouldIgnore(el) || !scrollableAncestorsAtTop(el)) return;
        if (!e.touches || !e.touches.length) return;
        startY = e.touches[0].clientY;
        pulling = true;
        dist = 0;
      },
      { passive: true }
    );

    document.addEventListener(
      "touchmove",
      function (e) {
        if (!pulling || refreshing) return;
        var el = eventElement(e);
        if (!scrollableAncestorsAtTop(el)) {
          resetPull();
          return;
        }
        var dy = e.touches[0].clientY - startY;
        if (dy > 8) {
          e.preventDefault();
          setDist((dy - 8) * 0.45);
        } else if (dy < 0) {
          resetPull();
        }
      },
      { passive: false }
    );

    document.addEventListener("touchend", function () {
      if (!pulling || refreshing) return;
      if (dist >= THRESHOLD) {
        pulling = false;
        refresh();
        return;
      }
      resetPull();
    });

    document.addEventListener("touchcancel", function () {
      if (!refreshing) resetPull();
    });

    window.__bindLeadsPullToRefresh = function () {
      if (isMobileLayout()) ensureIndicator();
    };
  })();
