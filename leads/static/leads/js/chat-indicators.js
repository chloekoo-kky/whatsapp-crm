(function () {
  if (window.__leadsDashboardSkip) return;
      function shouldPollLeadChatIndicators() {
        if (!isLeadsDashboardVisible()) return false;
        if (!document.getElementById('clinics-grid-inner')) return false;
        return folderHasWhatsAppLeads();
      }
      window.shouldPollLeadChatIndicators = shouldPollLeadChatIndicators;
      function createLeadChatAwaitingPulse() {
        var wrap = document.createElement('span');
        wrap.className = 'lead-chat-awaiting-pulse absolute right-1 top-1 flex h-2 w-2';
        wrap.setAttribute('aria-hidden', 'true');
        var dot = document.createElement('span');
        dot.className = 'relative inline-flex h-2 w-2 rounded-full bg-emerald-500 ring-2 ring-white';
        dot.setAttribute('aria-hidden', 'true');
        wrap.appendChild(dot);
        return wrap;
      }
      window.createLeadChatAwaitingPulse = createLeadChatAwaitingPulse;
      function updateActiveChatCountBadge(count) {
        var badge = document.getElementById('active-chat-count-badge');
        if (!badge) return;
        var n = Number(count) || 0;
        badge.textContent = String(n);
        badge.setAttribute('aria-label', n + ' active chats');
        badge.setAttribute('title', n + ' chats awaiting your reply');
        badge.classList.toggle('hidden', n === 0);
      }
      window.updateActiveChatCountBadge = updateActiveChatCountBadge;
      function setLeadCardAwaitingPulse(leadId, awaiting) {
        var cell = document.getElementById('lead-grid-cell-' + leadId);
        if (!cell) return false;
        var wants = awaiting ? '1' : '0';
        if (cell.getAttribute('data-awaiting-client-reply') === wants) return false;
        cell.setAttribute('data-awaiting-client-reply', wants);
        var btn = cell.querySelector('.lead-card-active-chat-btn');
        if (!btn) return true;
        var pulse = btn.querySelector('.lead-chat-awaiting-pulse');
        if (awaiting) {
          if (!pulse) btn.appendChild(createLeadChatAwaitingPulse());
        } else if (pulse) {
          pulse.remove();
        }
        return false;
      }
      window.setLeadCardAwaitingPulse = setLeadCardAwaitingPulse;
      function leadChatIndicatorSnapshotFromMap(leads) {
        var keys = Object.keys(leads || {}).sort();
        var parts = [];
        keys.forEach(function (id) {
          var row = leads[id] || {};
          parts.push(
            id + ':' + (row.awaiting ? '1' : '0') + ':' + (row.dispatched ? '1' : '0')
          );
        });
        return parts.join('|');
      }
      window.leadChatIndicatorSnapshotFromMap = leadChatIndicatorSnapshotFromMap;
      function leadChatIndicatorSnapshotFromDom() {
        var leads = {};
        document.querySelectorAll('#clinics-grid-inner .lead-card-container').forEach(function (cell) {
          var id = (cell.id || '').replace('lead-grid-cell-', '');
          if (!id) return;
          leads[id] = {
            awaiting: cell.getAttribute('data-awaiting-client-reply') === '1',
            dispatched: cell.getAttribute('data-whatsapp-dispatched') === '1',
          };
        });
        return leadChatIndicatorSnapshotFromMap(leads);
      }
      window.leadChatIndicatorSnapshotFromDom = leadChatIndicatorSnapshotFromDom;
      async function silentRefreshCurrentLeadGrid() {
        var data = await fetchLeadsTableFragment(currentLeadGroupTabId);
        if (!data || !data.ok) return;
        var tb = document.getElementById('clinics-table-body');
        var gridInner = document.getElementById('clinics-grid-inner');
        if (tb) tb.innerHTML = data.tbody_html;
        if (gridInner) gridInner.innerHTML = data.grid_html;
        if (data.funnel_metrics) updateFunnelMetricsStrip(data.funnel_metrics);
        if (data.group_counts) updateLeadGroupTabCounts(data.group_counts);
        if (data.tag_counts) updateLeadTagFilterCounts(data.tag_counts);
        syncLeadsAfterGroupFragmentSwap();
        leadChatIndicatorSnapshot = leadChatIndicatorSnapshotFromMap(
          (await fetchLeadChatIndicators())?.leads || {}
        );
      }
      window.silentRefreshCurrentLeadGrid = silentRefreshCurrentLeadGrid;
      async function fetchLeadChatIndicators() {
        var u = new URL(dashboardJsConfig.getLeadChatIndicatorsUrl, window.location.origin);
        var gid = normalizeLeadGroupTabId(currentLeadGroupTabId);
        u.searchParams.set('group_id', gid === 'uncategorized' ? 'uncategorized' : String(gid));
        if (activeSearchRecordId != null) u.searchParams.set('search_record', String(activeSearchRecordId));
        if (typeof window.isQueuedOutreachFilterActive === 'function' && window.isQueuedOutreachFilterActive()) {
          u.searchParams.set('queued', '1');
        }
        var res = await fetch(u.toString(), { headers: { Accept: 'application/json' }, credentials: 'same-origin' });
        if (!res.ok) throw new Error('HTTP ' + res.status);
        return res.json();
      }
      window.fetchLeadChatIndicators = fetchLeadChatIndicators;
      window.__refreshLeadChatIndicators = async function () {
        var gridInner = document.getElementById('clinics-grid-inner');
        if (!gridInner || !document.getElementById('clinics-panel')) return;
        try {
          var data = await fetchLeadChatIndicators();
          if (!data || !data.ok) return;
          if (data.funnel_metrics) updateFunnelMetricsStrip(data.funnel_metrics);
          if (data.group_counts) updateLeadGroupTabCounts(data.group_counts);
          if (data.active_chat_count != null) updateActiveChatCountBadge(data.active_chat_count);
          var snapshot = leadChatIndicatorSnapshotFromMap(data.leads || {});
          if (snapshot !== leadChatIndicatorSnapshot) {
            var apiLeadIds = Object.keys(data.leads || {});
            var domLeadIds = Array.prototype.slice.call(
              document.querySelectorAll('#clinics-grid-inner .lead-card-container')
            ).map(function (cell) {
              return (cell.id || '').replace('lead-grid-cell-', '');
            }).filter(Boolean);

            var rosterChanged = apiLeadIds.length !== domLeadIds.length;
            if (!rosterChanged) {
              for (var i = 0; i < apiLeadIds.length; i += 1) {
                if (domLeadIds.indexOf(apiLeadIds[i]) === -1) {
                  rosterChanged = true;
                  break;
                }
              }
            }
            if (!rosterChanged) {
              for (var j = 0; j < domLeadIds.length; j += 1) {
                if (!data.leads || !data.leads[domLeadIds[j]]) {
                  rosterChanged = true;
                  break;
                }
              }
            }

            if (rosterChanged) {
              await silentRefreshCurrentLeadGrid();
            } else {
              apiLeadIds.forEach(function (leadId) {
                var row = data.leads[leadId] || {};
                setLeadCardAwaitingPulse(leadId, !!row.awaiting);
                var cell = document.getElementById('lead-grid-cell-' + leadId);
                if (cell) {
                  cell.setAttribute('data-whatsapp-dispatched', row.dispatched ? '1' : '0');
                }
                document.querySelectorAll('.clinic-row[data-clinic-id="' + leadId + '"]').forEach(function (el) {
                  el.setAttribute('data-whatsapp-dispatched', row.dispatched ? '1' : '0');
                });
              });
              leadChatIndicatorSnapshot = snapshot;
            }
          }
        } catch (e) {
          console.error(e);
        }
      };
      window.__startLeadChatIndicatorPolling = function () {
        window.__stopLeadChatIndicatorPolling();
        if (!shouldPollLeadChatIndicators()) return;
        window.__refreshLeadChatIndicators();
        leadChatIndicatorPollTimer = window.setInterval(function () {
          if (!shouldPollLeadChatIndicators()) {
            window.__stopLeadChatIndicatorPolling();
            return;
          }
          window.__refreshLeadChatIndicators();
        }, CHAT_INDICATOR_POLL_MS);
      };
      window.__syncLeadChatIndicatorPolling = function () {
        if (shouldPollLeadChatIndicators()) {
          window.__startLeadChatIndicatorPolling();
        } else {
          window.__stopLeadChatIndicatorPolling();
        }
      };
      window.__stopLeadChatIndicatorPolling = function () {
        if (leadChatIndicatorPollTimer) {
          window.clearInterval(leadChatIndicatorPollTimer);
          leadChatIndicatorPollTimer = null;
        }
      };
})();
