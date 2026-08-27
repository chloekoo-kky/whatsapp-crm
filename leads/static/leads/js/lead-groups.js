(function () {
  if (window.__leadsDashboardSkip) return;
      function normalizeLeadGroupTabId(groupId) {
        if (groupId === 'uncategorized' || groupId === 'all' || groupId === '' || groupId == null) return 'uncategorized';
        return String(groupId);
      }
      window.normalizeLeadGroupTabId = normalizeLeadGroupTabId;
      function dashboardHistoryState() {
        return {
          leadGroupTabId: normalizeLeadGroupTabId(currentLeadGroupTabId),
          searchRecordId: activeSearchRecordId,
        };
      }
      window.dashboardHistoryState = dashboardHistoryState;
      function applyDashboardUrlFromState(state, url) {
        var u = url ? new URL(url, window.location.origin) : new URL(window.location.href);
        var gid = 'uncategorized';
        if (state && state.leadGroupTabId) {
          gid = normalizeLeadGroupTabId(state.leadGroupTabId);
        } else {
          var rawGid = u.searchParams.get('group_id');
          if (rawGid) gid = normalizeLeadGroupTabId(rawGid);
        }
        if (state && 'searchRecordId' in state) {
          activeSearchRecordId = state.searchRecordId;
        } else {
          var rawSr = u.searchParams.get('search_record');
          activeSearchRecordId = rawSr && String(rawSr).match(/^\d+$/) ? parseInt(rawSr, 10) : null;
        }
        return gid;
      }
      window.applyDashboardUrlFromState = applyDashboardUrlFromState;
      function replaceDashboardUrlForCurrentTab(historyMode) {
        var u = new URL(window.location.href);
        var gid = normalizeLeadGroupTabId(currentLeadGroupTabId);
        if (gid === 'uncategorized') {
          u.searchParams.delete('group_id');
        } else {
          u.searchParams.set('group_id', String(gid));
        }
        if (activeSearchRecordId != null) {
          u.searchParams.set('search_record', String(activeSearchRecordId));
        } else {
          u.searchParams.delete('search_record');
        }
        u.searchParams.delete('collapse_chains');
        var nextUrl = u.pathname + u.search + u.hash;
        var state = dashboardHistoryState();
        if (historyMode === 'push') {
          window.history.pushState(state, '', nextUrl);
        } else {
          window.history.replaceState(state, '', nextUrl);
        }
      }
      window.replaceDashboardUrlForCurrentTab = replaceDashboardUrlForCurrentTab;
      function setLeadGroupTabActive(groupId) {
        var want = normalizeLeadGroupTabId(groupId);
        currentLeadGroupTabId = want;
        document.querySelectorAll('#lead-group-tabs .lead-group-tab[data-group-id]').forEach(function (btn) {
          var id = btn.getAttribute('data-group-id') || 'uncategorized';
          var active = id === want;
          btn.classList.toggle('lead-group-tab--active', active);
          btn.setAttribute('aria-selected', active ? 'true' : 'false');
        });
        syncLeadGroupMobileLabel(want);
      }
      window.setLeadGroupTabActive = setLeadGroupTabActive;
      function syncLeadGroupMobileLabel(groupId) {
        var want = normalizeLeadGroupTabId(groupId);
        var btn = document.querySelector('#lead-group-tabs .lead-group-tab[data-group-id="' + want + '"]');
        var label = document.getElementById('lead-group-mobile-label');
        var countEl = document.getElementById('lead-group-mobile-count');
        if (!btn || !label) return;
        var clone = btn.cloneNode(true);
        clone.querySelectorAll('.lead-group-count, #active-chat-count-badge').forEach(function (el) {
          el.remove();
        });
        label.textContent = (clone.textContent || '').trim() || 'Uncategorized';
        if (!countEl) return;
        var countBadge = btn.querySelector('.lead-group-count, #active-chat-count-badge');
        if (countBadge) {
          var n = (countBadge.textContent || '').trim();
          countEl.textContent = n;
          countEl.classList.toggle('hidden', !n);
        } else {
          countEl.textContent = '';
          countEl.classList.add('hidden');
        }
      }
      window.syncLeadGroupMobileLabel = syncLeadGroupMobileLabel;
      function syncLeadsAfterGroupFragmentSwap() {
        currentLeadPage = 1;
        initClinicViewModeFromStorage();
        applyLeadSort();
        refreshSelectAllState();
        refreshSelectionVisuals();
        refreshSetCategoryButtonState();
        refreshBulkAssignGroupButtonState();
        applyTableFilter({ resetPage: false });
        if (window.htmx) {
          var tb = document.getElementById('clinics-table-body');
          if (tb) window.htmx.process(tb);
        }
        if (typeof window.__ensureGridHtmxBound === "function") window.__ensureGridHtmxBound();
        if (typeof window.__syncLeadChatIndicatorPolling === "function") {
          window.__syncLeadChatIndicatorPolling();
        }
        if (pendingHighlightLeadId) {
          var lid = pendingHighlightLeadId;
          pendingHighlightLeadId = null;
          window.requestAnimationFrame(function () {
            revealAndHighlightLead(lid);
          });
        }
      }
      window.syncLeadsAfterGroupFragmentSwap = syncLeadsAfterGroupFragmentSwap;
      async function fetchLeadsTableFragment(groupId, opts) {
        opts = opts || {};
        var u = new URL(dashboardJsConfig.getLeadsTableUrl, window.location.origin);
        if (opts.globalSearch && opts.q) {
          u.searchParams.set('q', String(opts.q));
        } else {
          var gid = normalizeLeadGroupTabId(groupId);
          u.searchParams.set('group_id', gid === 'uncategorized' ? 'uncategorized' : String(gid));
        }
        if (activeSearchRecordId != null) u.searchParams.set('search_record', String(activeSearchRecordId));
        var res = await fetch(u.toString(), { headers: { Accept: 'application/json' }, credentials: 'same-origin' });
        if (!res.ok) throw new Error('HTTP ' + res.status);
        return res.json();
      }
      window.fetchLeadsTableFragment = fetchLeadsTableFragment;
      async function switchLeadGroupTab(groupId, opts) {
        opts = opts || {};
        if (globalSearchActive && !opts.skipGlobalSearchExit) {
          globalSearchRequestId += 1;
          clearTimeout(globalSearchDebounceTimer);
          globalSearchActive = false;
          globalSearchQuery = '';
          updateGlobalSearchBanner();
          var searchClear = document.getElementById('table-search');
          if (searchClear) searchClear.value = '';
          refreshTableSearchClearVisibility();
        }
        var want = normalizeLeadGroupTabId(groupId);
        if (!opts.force && want === normalizeLeadGroupTabId(currentLeadGroupTabId) && !globalSearchActive) {
          return;
        }
        if (leadGroupTabBusy) return;
        leadGroupTabBusy = true;
        try {
          var data = await fetchLeadsTableFragment(want);
          if (!data.ok) throw new Error((data.detail && String(data.detail)) || 'Bad response');
          applyLeadsTableFragment(data);
          setLeadGroupTabActive(want);
          if (!opts.skipHistory) {
            replaceDashboardUrlForCurrentTab(opts.historyMode || (opts.fromPopstate ? 'replace' : 'push'));
          }
          syncLeadsAfterGroupFragmentSwap();
          leadChatIndicatorSnapshot = '';
          if (typeof window.__refreshLeadChatIndicators === 'function') {
            window.__refreshLeadChatIndicators();
          }
        } catch (err) {
          console.error(err);
          await window.appAlert('Could not load leads for this group.');
        } finally {
          leadGroupTabBusy = false;
        }
      }
      window.switchLeadGroupTab = switchLeadGroupTab;
      window.__refreshCurrentLeadFolder = function () {
        return switchLeadGroupTab(currentLeadGroupTabId, { force: true, skipHistory: true });
      };
      window.__dashboardHandlePopstate = function (e) {
        var gid = applyDashboardUrlFromState(e.state, window.location.href);
        switchLeadGroupTab(gid, { fromPopstate: true, skipHistory: true, force: true });
      };
      function clearLeadGroupMoveMenuErr() {
        var el = document.getElementById('lead-group-move-menu-error');
        if (!el) return;
        el.classList.add('hidden');
        el.textContent = '';
      }
      window.clearLeadGroupMoveMenuErr = clearLeadGroupMoveMenuErr;
      function closeLeadGroupMoveMenu() {
        var m = document.getElementById('lead-group-move-menu');
        if (m) {
          m.classList.add('hidden');
          m.setAttribute('aria-hidden', 'true');
        }
        var bulk = document.getElementById('bulk-assign-group-open');
        if (bulk) bulk.setAttribute('aria-expanded', 'false');
        leadGroupMoveMenuOpen = false;
        leadGroupMoveMenuAnchor = null;
        pendingMoveLeadIds = [];
        clearLeadGroupMoveMenuErr();
      }
      window.closeLeadGroupMoveMenu = closeLeadGroupMoveMenu;
      function positionLeadGroupMoveMenu(anchor) {
        var menu = document.getElementById('lead-group-move-menu');
        if (!menu || !anchor) return;
        menu.classList.remove('hidden');
        menu.setAttribute('aria-hidden', 'false');
        var mw = menu.offsetWidth;
        var mh = menu.offsetHeight;
        var r = anchor.getBoundingClientRect();
        var left = r.left + r.width / 2 - mw / 2;
        var top = r.bottom + 6;
        left = Math.max(8, Math.min(left, window.innerWidth - mw - 8));
        if (top + mh > window.innerHeight - 8) top = Math.max(8, r.top - mh - 6);
        menu.style.left = left + 'px';
        menu.style.top = top + 'px';
      }
      window.positionLeadGroupMoveMenu = positionLeadGroupMoveMenu;
      function openLeadGroupMoveMenu(anchor, ids) {
        var list = (ids || []).map(function (x) { return String(x); }).filter(function (x) { return x; });
        if (!list.length || !anchor) return;
        if (typeof closeLeadOwnerAssignMenu === 'function') closeLeadOwnerAssignMenu();
        pendingMoveLeadIds = list;
        clearLeadGroupMoveMenuErr();
        var cnt = document.getElementById('lead-group-move-menu-count');
        if (cnt) {
          var n = list.length;
          cnt.textContent = n === 1 ? '1 lead selected' : n + ' leads selected';
        }
        leadGroupMoveMenuOpen = true;
        leadGroupMoveMenuAnchor = anchor;
        if (anchor.id === 'bulk-assign-group-open') anchor.setAttribute('aria-expanded', 'true');
        positionLeadGroupMoveMenu(anchor);
      }
      window.openLeadGroupMoveMenu = openLeadGroupMoveMenu;
      function toggleLeadGroupMoveMenu(anchor, ids) {
        if (leadGroupMoveMenuOpen && leadGroupMoveMenuAnchor === anchor) {
          closeLeadGroupMoveMenu();
          return;
        }
        if (leadGroupMoveMenuOpen) closeLeadGroupMoveMenu();
        openLeadGroupMoveMenu(anchor, ids);
      }
      window.toggleLeadGroupMoveMenu = toggleLeadGroupMoveMenu;
      function clearLeadOwnerAssignMenuErr() {
        var el = document.getElementById('lead-owner-assign-menu-error');
        if (!el) return;
        el.classList.add('hidden');
        el.textContent = '';
      }
      window.clearLeadOwnerAssignMenuErr = clearLeadOwnerAssignMenuErr;
      function closeLeadOwnerAssignMenu() {
        var m = document.getElementById('lead-owner-assign-menu');
        if (m) {
          m.classList.add('hidden');
          m.setAttribute('aria-hidden', 'true');
        }
        var bulk = document.getElementById('bulk-assign-owner-open');
        if (bulk) bulk.setAttribute('aria-expanded', 'false');
        leadOwnerAssignMenuOpen = false;
        leadOwnerAssignMenuAnchor = null;
        pendingOwnerAssignLeadIds = [];
        clearLeadOwnerAssignMenuErr();
      }
      window.closeLeadOwnerAssignMenu = closeLeadOwnerAssignMenu;
      function positionLeadOwnerAssignMenu(anchor) {
        var menu = document.getElementById('lead-owner-assign-menu');
        if (!menu || !anchor) return;
        menu.classList.remove('hidden');
        menu.setAttribute('aria-hidden', 'false');
        var mw = menu.offsetWidth;
        var mh = menu.offsetHeight;
        var r = anchor.getBoundingClientRect();
        var left = r.left + r.width / 2 - mw / 2;
        var top = r.bottom + 6;
        left = Math.max(8, Math.min(left, window.innerWidth - mw - 8));
        if (top + mh > window.innerHeight - 8) top = Math.max(8, r.top - mh - 6);
        menu.style.left = left + 'px';
        menu.style.top = top + 'px';
      }
      window.positionLeadOwnerAssignMenu = positionLeadOwnerAssignMenu;
      function openLeadOwnerAssignMenu(anchor, ids) {
        var list = (ids || []).map(function (x) { return String(x); }).filter(function (x) { return x; });
        if (!list.length || !anchor) return;
        if (typeof closeLeadGroupMoveMenu === 'function') closeLeadGroupMoveMenu();
        pendingOwnerAssignLeadIds = list;
        clearLeadOwnerAssignMenuErr();
        var cnt = document.getElementById('lead-owner-assign-menu-count');
        if (cnt) {
          var n = list.length;
          cnt.textContent = n === 1 ? '1 lead selected' : n + ' leads selected';
        }
        leadOwnerAssignMenuOpen = true;
        leadOwnerAssignMenuAnchor = anchor;
        if (anchor.id === 'bulk-assign-owner-open') anchor.setAttribute('aria-expanded', 'true');
        positionLeadOwnerAssignMenu(anchor);
      }
      window.openLeadOwnerAssignMenu = openLeadOwnerAssignMenu;
      function toggleLeadOwnerAssignMenu(anchor, ids) {
        if (leadOwnerAssignMenuOpen && leadOwnerAssignMenuAnchor === anchor) {
          closeLeadOwnerAssignMenu();
          return;
        }
        if (leadOwnerAssignMenuOpen) closeLeadOwnerAssignMenu();
        openLeadOwnerAssignMenu(anchor, ids);
      }
      window.toggleLeadOwnerAssignMenu = toggleLeadOwnerAssignMenu;
})();
