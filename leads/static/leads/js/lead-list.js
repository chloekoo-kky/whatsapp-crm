(function () {
  if (window.__leadsDashboardSkip) return;
      async function handleLeadDequeueClick(btn) {
        if (!btn || btn.classList.contains('is-busy')) return;
        var url = btn.getAttribute('data-dequeue-url');
        var leadId = btn.getAttribute('data-lead-id');
        if (!url || !leadId) return;
        var isQueueView = btn.getAttribute('data-queue-view') === '1';
        btn.classList.add('is-busy');
        btn.disabled = true;
        try {
          var body = new FormData();
          var groupId = btn.getAttribute('data-group-id');
          if (groupId) body.append('group_id', groupId);
          if (isQueueView) body.append('queued', '1');
          var res = await fetch(url, {
            method: 'POST',
            headers: { 'X-CSRFToken': getCsrfToken() },
            credentials: 'same-origin',
            body: body,
          });
          var html = await res.text();
          if (!res.ok) {
            await window.appAlert('Could not unassign this lead from the WhatsApp batch.');
            return;
          }
          dispatchHtmxTriggerHeader(res.headers.get('HX-Trigger'));
          if (isQueueView) {
            var cell = document.getElementById('lead-grid-cell-' + leadId);
            if (cell) {
              cell.classList.add('lead-card--dequeuing');
              cell.setAttribute('data-whatsapp-status', 'idle');
            }
            var slot = document.getElementById('lead-queue-slot-' + leadId);
            if (slot) {
              slot.innerHTML = html;
              if (window.htmx) window.htmx.process(slot);
            }
          } else {
            var slot = document.getElementById('lead-queue-slot-' + leadId);
            if (slot) {
              slot.innerHTML = html;
              if (window.htmx) window.htmx.process(slot);
            }
          }
          if (typeof window.refreshSelectAllState === 'function') window.refreshSelectAllState();
          if (typeof window.refreshSelectionVisuals === 'function') window.refreshSelectionVisuals();
          if (typeof window.refreshSetCategoryButtonState === 'function') window.refreshSetCategoryButtonState();
          if (typeof window.refreshBulkAssignGroupButtonState === 'function') window.refreshBulkAssignGroupButtonState();
          if (typeof window.applyTableFilter === 'function') window.applyTableFilter({ resetPage: false });
        } catch (err) {
          console.error(err);
          await window.appAlert('Network error while unassigning this lead from the batch.');
        } finally {
          if (document.body.contains(btn)) {
            btn.classList.remove('is-busy');
            btn.disabled = false;
          }
        }
      }
      window.handleLeadDequeueClick = handleLeadDequeueClick;
      function isLeadsDashboardVisible() {
        var dashPanel = document.getElementById('workspace-panel-dashboard');
        return !!dashPanel && !dashPanel.hasAttribute('hidden') && !document.hidden;
      }
      window.isLeadsDashboardVisible = isLeadsDashboardVisible;
      function folderHasWhatsAppLeads() {
        var tbody = document.getElementById('clinics-table-body');
        if (!tbody) return false;
        return tbody.querySelector('tr.clinic-row[data-whatsapp-dispatched="1"]') !== null;
      }
      window.folderHasWhatsAppLeads = folderHasWhatsAppLeads;
      function setLeadVipStarVisual(btn, on) {
        if (!btn) return;
        btn.setAttribute('data-vip', on ? 'true' : 'false');
        btn.setAttribute('aria-pressed', on ? 'true' : 'false');
        btn.setAttribute('title', on ? 'Very important — click to clear' : 'Mark as very important');
        var o = btn.querySelector('.lead-vip-icon-outline');
        var s = btn.querySelector('.lead-vip-icon-solid');
        if (o) o.classList.toggle('hidden', on);
        if (s) s.classList.toggle('hidden', !on);
        btn.classList.toggle('text-amber-500', on);
        btn.classList.toggle('hover:bg-amber-50/90', on);
        btn.classList.toggle('hover:text-amber-600', on);
        btn.classList.toggle('text-slate-300', !on);
        btn.classList.toggle('hover:bg-amber-50/80', !on);
        btn.classList.toggle('hover:text-amber-500', !on);
      }
      window.setLeadVipStarVisual = setLeadVipStarVisual;
      function syncRowDataSearch(row, category, isChain, isVeryImportant, tags) {
        const base = (row.getAttribute('data-search-base') || '').trim();
        var t = (row.getAttribute('data-category') || '').trim();
        if (category !== undefined && category !== null) {
          t = String(category).trim();
          row.setAttribute('data-category', t);
        }
        var chain = row.getAttribute('data-is-chain') === '1';
        if (isChain !== undefined && isChain !== null) {
          chain = !!isChain;
          row.setAttribute('data-is-chain', chain ? '1' : '0');
        }
        var vip = row.getAttribute('data-very-important') === '1';
        if (isVeryImportant !== undefined && isVeryImportant !== null) {
          vip = !!isVeryImportant;
          row.setAttribute('data-very-important', vip ? '1' : '0');
        }
        var tagBits = [];
        if (tags !== undefined && tags !== null) {
          if (Array.isArray(tags)) {
            tagBits = tags.map(function (s) { return String(s).trim(); }).filter(Boolean);
            row.setAttribute('data-tags', tagBits.join(' '));
          }
        } else {
          tagBits = String(row.getAttribute('data-tags') || '').split(/\s+/).filter(Boolean);
        }
        const bits = [base, t].concat(tagBits);
        if (chain) bits.push('chain');
        if (vip) bits.push('important');
        row.setAttribute('data-search', bits.join(' ').replace(/\s+/g, ' ').trim());
      }
      window.syncRowDataSearch = syncRowDataSearch;
      function renderSourceLineText(searchState, searchCity, shopKeyword, searchQuery) {
        const parts = [
          (searchState || '').trim(),
          (searchCity || '').trim(),
          (shopKeyword || '').trim(),
          (searchQuery || '').trim(),
        ].filter(function (s) { return s.length > 0; });
        if (!parts.length) return '<span class="text-slate-400">—</span>';
        return parts.map(escapeHtml).join(' <span class="text-slate-400">/</span> ');
      }
      window.renderSourceLineText = renderSourceLineText;
      function renderWebsiteLineHtml(website) {
        const w = (website || '').trim();
        if (!w) return '';
        return (
          '<a href="' +
          escapeAttr(w) +
          '" class="break-all text-indigo-600 underline decoration-slate-300 decoration-1 underline-offset-2 transition hover:text-indigo-500" target="_blank" rel="noopener" title="' +
          escapeAttr(w) +
          '">' +
          escapeHtml(w) +
          '</a>'
        );
      }
      window.renderWebsiteLineHtml = renderWebsiteLineHtml;
      function setRowWhatsappDraft(row, draft) {
        if (!row) return;
        var store = row.querySelector('.whatsapp-draft-store');
        var btn = row.querySelector('.whatsapp-copy-btn');
        var t = draft != null ? String(draft) : '';
        if (store) store.textContent = t;
        if (btn) {
          var has = t.trim().length > 0;
          btn.disabled = !has;
          btn.title = has ? 'Copy WhatsApp draft to clipboard' : 'No draft yet — add one in Edit';
        }
      }
      window.setRowWhatsappDraft = setRowWhatsappDraft;
      function showLeadStatusToast(message, opts) {
        opts = opts || {};
        const el = document.getElementById('clinic-save-status');
        if (!el) return;
        const warnClasses = ['bg-amber-50', 'text-amber-900', 'ring-amber-200/90'];
        const okClasses = ['bg-emerald-50', 'text-emerald-900', 'ring-emerald-200/90'];
        el.classList.remove.apply(el.classList, warnClasses.concat(okClasses));
        el.classList.add.apply(el.classList, opts.tone === 'warn' ? warnClasses : okClasses);
        el.textContent = String(message || '');
        el.classList.remove('hidden');
        el.classList.remove('lead-status-toast--in');
        void el.offsetWidth;
        el.classList.add('lead-status-toast--in');
        if (clinicSaveStatusTimer) clearTimeout(clinicSaveStatusTimer);
        clinicSaveStatusTimer = setTimeout(function () {
          el.classList.remove('lead-status-toast--in');
          el.classList.add('hidden');
          clinicSaveStatusTimer = null;
        }, opts.duration || 4200);
      }
      window.showLeadStatusToast = showLeadStatusToast;
      function showClinicSaveSuccess(name) {
        const label = (name != null && String(name).trim()) ? String(name).trim() : 'Clinic';
        showLeadStatusToast('Saved — ' + label + ' updated.');
      }
      window.showClinicSaveSuccess = showClinicSaveSuccess;
      function flashClinicRowAfterSave(clinicId) {
        const sel = '.clinic-row[data-clinic-id="' + clinicId + '"]';
        document.querySelectorAll(sel).forEach(function (row) {
          row.classList.add('clinic-row--updated');
          window.setTimeout(function () {
            row.classList.remove('clinic-row--updated');
          }, 1200);
        });
      }
      window.flashClinicRowAfterSave = flashClinicRowAfterSave;
      function rebindLeadCardHtmx(leadId) {
        if (!window.htmx || leadId == null) return;
        var cell = document.getElementById('lead-grid-cell-' + leadId);
        if (cell) window.htmx.process(cell);
        document.querySelectorAll('tr.clinic-row[data-clinic-id="' + leadId + '"]').forEach(function (tr) {
          window.htmx.process(tr);
        });
      }
      window.rebindLeadCardHtmx = rebindLeadCardHtmx;
      function applyClinicEditToDom(d) {
        if (!d || !d.ok || d.id == null) return;
        const id = d.id;
        var phonesSearch = '';
        if (Array.isArray(d.phone_numbers) && d.phone_numbers.length) {
          phonesSearch = d.phone_numbers.join(' ');
        } else if (d.phone_number) {
          phonesSearch = String(d.phone_number);
        }
        const baseStr = [d.name, d.address, phonesSearch, d.website, d.shop_keyword, d.search_state, d.search_city, d.search_query]
          .join(' ')
          .replace(/\s+/g, ' ')
          .trim();

        document.querySelectorAll('.clinic-row[data-clinic-id="' + id + '"]').forEach(function (row) {
          row.setAttribute('data-search-base', baseStr);
          row.setAttribute('data-is-chain', d.is_chain ? '1' : '0');
          if (d.search_state != null) {
            row.setAttribute('data-sort-state', String(d.search_state || '').toLowerCase());
          }
          const typeCell = row.querySelector('.clinic-type-cell');
          if (typeCell && d.type_html) typeCell.innerHTML = d.type_html;
          if (d.is_very_important !== undefined) {
            row.querySelectorAll('.lead-vip-star-btn').forEach(function (b) {
              setLeadVipStarVisual(b, !!d.is_very_important);
            });
          }
          syncRowDataSearch(
            row,
            d.category || d.clinic_type,
            d.is_chain,
            d.is_very_important,
            d.tags
          );

          const nameInner = row.querySelector('.clinic-name-cell-inner');
          if (nameInner && d.name_cell_html) nameInner.innerHTML = d.name_cell_html;

          const sourceLine = row.querySelector('.clinic-source-line');
          if (sourceLine) sourceLine.innerHTML = renderSourceLineText(d.search_state, d.search_city, d.shop_keyword, d.search_query);

          const branchesLine = row.querySelector('.clinic-branches-line');
          if (branchesLine) {
            if (d.branches_line_html) {
              branchesLine.innerHTML = d.branches_line_html;
              branchesLine.classList.remove('hidden');
            } else {
              branchesLine.innerHTML = '';
              branchesLine.classList.add('hidden');
            }
          }

          const addrEl = row.querySelector('.clinic-address-inner');
          if (addrEl) {
            const a = d.address != null ? String(d.address).trim() : '';
            const nm = d.name != null ? String(d.name).trim() : '';
            addrEl.textContent = a || '—';
            addrEl.setAttribute('data-clinic-name', nm);
            addrEl.setAttribute('data-address-copy', a);
            const hasAddrCopy = !!(nm || a);
            addrEl.setAttribute('title', hasAddrCopy ? 'Click to copy name & address' : 'Nothing to copy');
            if (addrEl.tagName === 'BUTTON') addrEl.disabled = !hasAddrCopy;
          }

          const webLine = row.querySelector('.clinic-website-line');
          if (webLine) {
            const wh = renderWebsiteLineHtml(d.website);
            if (wh) {
              webLine.innerHTML = wh;
              webLine.classList.remove('hidden');
            } else {
              webLine.innerHTML = '';
              webLine.classList.add('hidden');
            }
          }

          row.querySelectorAll('td.clinic-phone-cell').forEach(function (td) {
            if (d.phone_td_inner_list) td.innerHTML = d.phone_td_inner_list;
          });
          row.querySelectorAll('.clinic-phone-slot').forEach(function (slot) {
            if (d.phone_slot_inner_grid) slot.outerHTML = d.phone_slot_inner_grid;
          });

          if (d.whatsapp_status != null) {
            row.setAttribute('data-whatsapp-status', String(d.whatsapp_status));
            var gridCell = document.getElementById('lead-grid-cell-' + id);
            if (gridCell) gridCell.setAttribute('data-whatsapp-status', String(d.whatsapp_status));
          }
          if (d.whatsapp_dispatched != null) {
            var dispatched = d.whatsapp_dispatched ? '1' : '0';
            row.setAttribute('data-whatsapp-dispatched', dispatched);
            var gridCellDisp = document.getElementById('lead-grid-cell-' + id);
            if (gridCellDisp) gridCellDisp.setAttribute('data-whatsapp-dispatched', dispatched);
            if (row.classList.contains('clinic-card')) {
              row.classList.toggle('clinic-card--dispatched', !!d.whatsapp_dispatched);
            }
          }
          if (d.grid_bottom_actions_html) {
            var bottomActions = document.getElementById('lead-bottom-actions-' + id);
            if (bottomActions) bottomActions.outerHTML = d.grid_bottom_actions_html;
          }

          var copyPhone = '';
          if (Array.isArray(d.phone_numbers) && d.phone_numbers.length) {
            copyPhone = d.phone_numbers.join(' ; ');
          } else if (d.phone_number != null) {
            copyPhone = String(d.phone_number);
          }
          row.querySelectorAll('.lead-card-copy-details-btn').forEach(function (btn) {
            btn.setAttribute('data-copy-name', d.name != null ? String(d.name) : '');
            btn.setAttribute('data-copy-address', d.address != null ? String(d.address) : '');
            btn.setAttribute('data-copy-phone', copyPhone);
            btn.setAttribute('data-copy-website', d.website != null ? String(d.website) : '');
          });

          const actCell = row.querySelector('.clinic-actions-cell');
          if (actCell && !row.classList.contains('clinic-card')) {
            if (d.actions_cell_html != null && d.actions_cell_html !== '') {
              actCell.innerHTML = d.actions_cell_html;
            }
          }

          if (d.whatsapp_draft !== undefined) setRowWhatsappDraft(row, d.whatsapp_draft);
        });

        rebindLeadCardHtmx(id);
        if (typeof window.invalidateLeadTabFragmentCache === 'function') {
          window.invalidateLeadTabFragmentCache();
        }
        if (!clinicLeadWouldHideFromCurrentFilters(id)) flashClinicRowAfterSave(id);
        fadeLeadsOutOfCurrentFilters([id]);
      }
      window.applyClinicEditToDom = applyClinicEditToDom;
      function readLeadsPerPage() {
        var allowed = { 24: true, 48: true, 96: true };
        try {
          var stored = parseInt(localStorage.getItem(LEADS_PER_PAGE_KEY) || '48', 10);
          if (allowed[stored]) return stored;
        } catch (e) { /* ignore */ }
        return 48;
      }
      window.readLeadsPerPage = readLeadsPerPage;
      function syncLeadsPerPageSelect() {
        var sel = document.getElementById('leads-per-page-select');
        if (!sel) return;
        var perPage = String(readLeadsPerPage());
        if (sel.value !== perPage) sel.value = perPage;
      }
      window.syncLeadsPerPageSelect = syncLeadsPerPageSelect;
      function getFilteredClinicRowsInOrder() {
        var tbody = document.getElementById('clinics-table-body');
        if (!tbody) return [];
        return Array.from(tbody.querySelectorAll('tr.clinic-row:not(.hidden)'));
      }
      window.getFilteredClinicRowsInOrder = getFilteredClinicRowsInOrder;
      function updateLeadPaginationControls(totalFiltered, totalPages) {
        var statusEl = document.getElementById('leads-page-status');
        var prevBtn = document.getElementById('leads-page-prev');
        var nextBtn = document.getElementById('leads-page-next');
        var controls = document.getElementById('leads-pagination-controls');
        if (statusEl) {
          statusEl.textContent = totalFiltered
            ? String(currentLeadPage) + ' / ' + String(totalPages)
            : '0 / 0';
        }
        if (prevBtn) prevBtn.disabled = currentLeadPage <= 1 || totalFiltered === 0;
        if (nextBtn) nextBtn.disabled = currentLeadPage >= totalPages || totalFiltered === 0;
        if (controls) {
          controls.classList.toggle('opacity-60', totalFiltered === 0);
        }
      }
      window.updateLeadPaginationControls = updateLeadPaginationControls;
      function applyLeadPagination(resetPage) {
        syncLeadsPerPageSelect();
        var perPage = readLeadsPerPage();
        if (resetPage) currentLeadPage = 1;
        var rows = getFilteredClinicRowsInOrder();
        var totalFiltered = rows.length;
        var totalPages = Math.max(1, Math.ceil(totalFiltered / perPage) || 1);
        if (currentLeadPage > totalPages) currentLeadPage = totalPages;
        if (currentLeadPage < 1) currentLeadPage = 1;
        var start = (currentLeadPage - 1) * perPage;
        var end = start + perPage;
        var visibleIds = Object.create(null);
        rows.forEach(function (row, idx) {
          if (idx >= start && idx < end) {
            var id = row.getAttribute('data-clinic-id');
            if (id) visibleIds[id] = true;
          }
        });
        document.querySelectorAll('.clinic-row').forEach(function (row) {
          var id = row.getAttribute('data-clinic-id');
          var filterHidden = row.classList.contains('hidden');
          if (filterHidden) {
            row.classList.remove('lead-page-hidden');
            return;
          }
          row.classList.toggle('lead-page-hidden', !visibleIds[id]);
        });
        document.querySelectorAll('.lead-card-container').forEach(function (cell) {
          var row = cell.querySelector('.clinic-row');
          if (!row) return;
          var id = row.getAttribute('data-clinic-id');
          var filterHidden = cell.classList.contains('hidden');
          if (filterHidden) {
            cell.classList.remove('lead-page-hidden');
            return;
          }
          cell.classList.toggle('lead-page-hidden', !visibleIds[id]);
        });
        updateLeadPaginationControls(totalFiltered, totalPages);
        clearSelectionsForHiddenRows();
        refreshSelectAllState();
        refreshSelectionVisuals();
        refreshGridCardsDraggable();
      }
      window.applyLeadPagination = applyLeadPagination;
      function goToLeadPage(page) {
        var next = parseInt(page, 10);
        if (!next || next < 1) return;
        currentLeadPage = next;
        applyLeadPagination(false);
      }
      window.goToLeadPage = goToLeadPage;
      function getActiveClinicsViewRoot() {
        const listEl = document.getElementById('clinics-view-list');
        const gridEl = document.getElementById('clinics-view-grid');
        if (document.documentElement.classList.contains('cv-grid')) return gridEl || listEl;
        return listEl || gridEl;
      }
      window.getActiveClinicsViewRoot = getActiveClinicsViewRoot;
      function getVisibleClinicRows(root) {
        const scope = root || getActiveClinicsViewRoot();
        if (!scope) return [];
        return Array.from(scope.querySelectorAll('.clinic-row:not(.hidden):not(.lead-page-hidden)'));
      }
      window.getVisibleClinicRows = getVisibleClinicRows;
      function setLeadCheckboxSelected(leadId, on) {
        const id = leadId != null ? String(leadId) : '';
        if (!id) return;
        document.querySelectorAll('.clinic-select-cb').forEach(function (cb) {
          if (cb.value === id) cb.checked = !!on;
        });
      }
      window.setLeadCheckboxSelected = setLeadCheckboxSelected;
      function clearSelectionsForHiddenRows() {
        document.querySelectorAll('.clinic-row.hidden, .clinic-row.lead-page-hidden').forEach(function (row) {
          const cb = row.querySelector('.clinic-select-cb');
          if (cb && cb.checked) setLeadCheckboxSelected(cb.value, false);
        });
      }
      window.clearSelectionsForHiddenRows = clearSelectionsForHiddenRows;
      function refreshSelectAllState() {
        if (!selectAll) return;
        const boxes = getVisibleClinicRows().map(function (row) {
          return row.querySelector('.clinic-select-cb');
        }).filter(Boolean);
        if (!boxes.length) {
          selectAll.checked = false;
          selectAll.indeterminate = false;
          return;
        }
        let nOn = 0;
        boxes.forEach(function (b) { if (b.checked) nOn += 1; });
        selectAll.checked = nOn === boxes.length;
        selectAll.indeterminate = nOn > 0 && nOn < boxes.length;
      }
      window.refreshSelectAllState = refreshSelectAllState;
      function refreshLeadSelectionCount() {
        var n = typeof getUniqueSelectedLeadIds === 'function' ? getUniqueSelectedLeadIds().length : 0;
        var text = n === 1 ? '1 selected' : n + ' selected';
        document.querySelectorAll('[data-lead-selection-count]').forEach(function (el) {
          el.textContent = n > 0 ? text : '';
          el.hidden = n < 1;
        });
      }
      window.refreshLeadSelectionCount = refreshLeadSelectionCount;
      function refreshSelectionVisuals() {
        const byId = {};
        document.querySelectorAll('.clinic-select-cb').forEach(function (cb) {
          byId[cb.value] = cb.checked;
        });
        document.querySelectorAll('.clinic-row[data-clinic-id]').forEach(function (row) {
          const id = row.getAttribute('data-clinic-id');
          const on = byId[id] === true;
          row.classList.toggle('clinic-row--selected', on);
          row.setAttribute('aria-selected', on ? 'true' : 'false');
        });
        refreshSetCategoryButtonState();
        refreshBulkAssignGroupButtonState();
        refreshBulkActionDock();
        refreshLeadSelectionCount();
      }
      window.refreshSelectionVisuals = refreshSelectionVisuals;
      window.__refreshFunnelMetricsStrip = async function () {
        try {
          var gid = typeof currentLeadGroupTabId !== 'undefined' && currentLeadGroupTabId != null
            ? String(currentLeadGroupTabId)
            : 'uncategorized';
          var data = await fetchLeadsTableFragment(gid);
          if (data && data.funnel_metrics) updateFunnelMetricsStrip(data.funnel_metrics);
          if (data && data.group_counts) updateLeadGroupTabCounts(data.group_counts);
          if (data && data.tag_counts) updateLeadTagFilterCounts(data.tag_counts);
        } catch (e) {
          console.error(e);
        }
      };
      function countUniqueLeadIdsFromRows(rows) {
        var seen = Object.create(null);
        (rows || []).forEach(function (row) {
          var id = row.getAttribute('data-clinic-id');
          if (id) seen[id] = true;
        });
        return Object.keys(seen).length;
      }
      window.countUniqueLeadIdsFromRows = countUniqueLeadIdsFromRows;
      function getAllClinicRowsInActiveView() {
        var scope = getActiveClinicsViewRoot();
        if (!scope) return [];
        return Array.from(scope.querySelectorAll('.clinic-row'));
      }
      window.getAllClinicRowsInActiveView = getAllClinicRowsInActiveView;
      function isLeadTableFilterActive() {
        var si = document.getElementById('table-search');
        if (si && si.value.trim()) return true;
        var vip = document.getElementById('filter-very-important-only');
        if (vip && vip.getAttribute('aria-pressed') === 'true') return true;
        var chain = document.getElementById('filter-chain-only');
        if (chain && chain.getAttribute('aria-pressed') === 'true') return true;
        var noChain = document.getElementById('filter-no-chain-only');
        if (noChain && noChain.getAttribute('aria-pressed') === 'true') return true;
        var sent = document.getElementById('filter-sent-message-only');
        if (sent && sent.getAttribute('aria-pressed') === 'true') return true;
        var unsent = document.getElementById('filter-unsent-message-only');
        if (unsent && unsent.getAttribute('aria-pressed') === 'true') return true;
        return getLeadTagFilterSlugs().length > 0;
      }
      window.isLeadTableFilterActive = isLeadTableFilterActive;
      function getFolderLeadCount() {
        var domCount = countUniqueLeadIdsFromRows(getAllClinicRowsInActiveView());
        return Math.max(domCount, folderTotalPipelineCount);
      }
      window.getFolderLeadCount = getFolderLeadCount;
      function refreshFilteredLeadCount() {
        var totalEl = document.getElementById('funnel-metric-total');
        var labelEl = document.getElementById('funnel-metric-total-label');
        var hintEl = document.getElementById('funnel-metric-total-filtered-hint');
        var folderEl = document.getElementById('funnel-metric-total-folder');
        if (!totalEl || !labelEl) return;

        var folderCount = getFolderLeadCount();

        if (!isLeadTableFilterActive()) {
          labelEl.textContent = 'Total Pipeline';
          totalEl.textContent = String(folderCount);
          if (hintEl) {
            hintEl.classList.add('hidden');
            hintEl.setAttribute('aria-hidden', 'true');
          }
          return;
        }

        var allRows = getAllClinicRowsInActiveView();
        var visibleRows = allRows.filter(function (r) { return !r.classList.contains('hidden'); });
        labelEl.textContent = 'Filtered count';
        totalEl.textContent = String(countUniqueLeadIdsFromRows(visibleRows));
        if (hintEl && folderEl) {
          folderEl.textContent = String(folderCount);
          hintEl.classList.remove('hidden');
          hintEl.setAttribute('aria-hidden', 'false');
        }
      }
      window.refreshFilteredLeadCount = refreshFilteredLeadCount;
      function updateFunnelMetricsStrip(metrics) {
        if (!metrics || typeof metrics !== 'object') return;
        if (metrics.total_pipeline != null) {
          folderTotalPipelineCount = Number(metrics.total_pipeline) || 0;
        }
        var map = {
          in_queue: 'funnel-metric-queue',
          outbound_sent: 'funnel-metric-sent',
          live_responses: 'funnel-metric-responses',
        };
        Object.keys(map).forEach(function (key) {
          var el = document.getElementById(map[key]);
          if (el && metrics[key] != null) el.textContent = String(metrics[key]);
        });
        refreshFilteredLeadCount();
      }
      window.updateFunnelMetricsStrip = updateFunnelMetricsStrip;
      function updateLeadGroupTabCounts(counts) {
        if (!counts || typeof counts !== 'object') return;
        document
          .querySelectorAll('#lead-group-tabs .lead-group-tab[data-group-id]')
          .forEach(function (tab) {
            var id = tab.getAttribute('data-group-id') || '';
            if (!Object.prototype.hasOwnProperty.call(counts, id)) return;
            var badge = tab.querySelector('.lead-group-count');
            if (!badge) return;
            var n = counts[id];
            badge.textContent = String(n);
            badge.title = n + ' lead(s) in this group';
          });
      }
      window.updateLeadGroupTabCounts = updateLeadGroupTabCounts;
      function syncLeadTagFilterChipVisibility(chip) {
        if (!chip) return;
        var badge = chip.querySelector('.lead-tag-filter-count');
        var n = badge ? Number(String(badge.textContent || '').trim()) || 0 : 0;
        var selected = chip.getAttribute('aria-pressed') === 'true';
        chip.hidden = n < 1 && !selected;
      }
      window.syncLeadTagFilterChipVisibility = syncLeadTagFilterChipVisibility;
      function updateLeadTagFilterCounts(counts) {
        if (!counts || typeof counts !== 'object') return;
        document.querySelectorAll('#lead-tag-filter .lead-tag-filter-chip').forEach(function (chip) {
          var slug = chip.getAttribute('data-tag-slug') || '';
          var n = Object.prototype.hasOwnProperty.call(counts, slug) ? Number(counts[slug]) || 0 : 0;
          var badge = chip.querySelector('.lead-tag-filter-count');
          if (!badge) {
            badge = document.createElement('span');
            badge.className = 'lead-tag-filter-count';
            badge.setAttribute('aria-hidden', 'true');
            chip.appendChild(badge);
          }
          badge.textContent = String(n);
          var labelEl = chip.querySelector('.lead-tag-filter-label');
          var name = labelEl ? String(labelEl.textContent || '').trim() : slug;
          chip.title = name + ' · ' + n + ' lead(s)';
          syncLeadTagFilterChipVisibility(chip);
        });
      }
      window.updateLeadTagFilterCounts = updateLeadTagFilterCounts;
      function setClinicViewMode(mode) {
        const isGrid = mode === 'grid';
        const listEl = document.getElementById('clinics-view-list');
        const gridEl = document.getElementById('clinics-view-grid');
        document.documentElement.classList.remove('cv-grid', 'cv-list');
        document.documentElement.classList.add(isGrid ? 'cv-grid' : 'cv-list');
        if (listEl) listEl.classList.toggle('hidden', isGrid);
        if (gridEl) gridEl.classList.toggle('hidden', !isGrid);
        document.querySelectorAll('.view-mode-btn').forEach(function (btn) {
          const active = btn.getAttribute('data-view-mode') === (isGrid ? 'grid' : 'list');
          btn.setAttribute('aria-pressed', active ? 'true' : 'false');
        });
        try {
          localStorage.setItem(VIEW_MODE_KEY, isGrid ? 'grid' : 'list');
        } catch (e) { /* ignore */ }
        refreshSelectAllState();
        refreshSelectionVisuals();
        applyTableFilter({ resetPage: false });
        if (typeof window.__ensureGridHtmxBound === "function") window.__ensureGridHtmxBound();
      }
      window.setClinicViewMode = setClinicViewMode;
      function readLeadSortMode() {
        try {
          var v = localStorage.getItem(LEAD_SORT_KEY);
          if (v && /^(default|name-asc|name-desc|state-asc|state-desc|created-asc|created-desc)$/.test(v)) return v;
        } catch (e) { /* ignore */ }
        return 'default';
      }
      window.readLeadSortMode = readLeadSortMode;
      function syncLeadSortSelect() {
        var sel = document.getElementById('lead-sort-select');
        if (sel && sel.value !== leadSortMode) sel.value = leadSortMode;
      }
      window.syncLeadSortSelect = syncLeadSortSelect;
      function compareLeadRowsForSort(a, b) {
        var desc = leadSortMode.endsWith('-desc');
        var field = leadSortMode.split('-')[0];
        var av;
        var bv;
        if (field === 'created') {
          av = parseFloat(a.getAttribute('data-sort-created') || '0') || 0;
          bv = parseFloat(b.getAttribute('data-sort-created') || '0') || 0;
        } else if (field === 'state') {
          av = (a.getAttribute('data-sort-state') || '').toLowerCase();
          bv = (b.getAttribute('data-sort-state') || '').toLowerCase();
        } else {
          av = (a.getAttribute('data-sort-name') || '').toLowerCase();
          bv = (b.getAttribute('data-sort-name') || '').toLowerCase();
        }
        var cmp = 0;
        if (field === 'created') cmp = av - bv;
        else if (av < bv) cmp = -1;
        else if (av > bv) cmp = 1;
        if (cmp === 0) {
          var aid = parseInt(a.getAttribute('data-clinic-id') || '0', 10) || 0;
          var bid = parseInt(b.getAttribute('data-clinic-id') || '0', 10) || 0;
          cmp = aid - bid;
        }
        return desc ? -cmp : cmp;
      }
      window.compareLeadRowsForSort = compareLeadRowsForSort;
      function applyLeadSort() {
        syncLeadSortSelect();
        if (leadSortMode === 'default') return;
        var tbody = document.getElementById('clinics-table-body');
        if (tbody) {
          var rows = Array.from(tbody.querySelectorAll('tr.clinic-row'));
          rows.sort(compareLeadRowsForSort);
          rows.forEach(function (row) { tbody.appendChild(row); });
        }
        var gridInner = document.getElementById('clinics-grid-inner');
        if (gridInner) {
          var cells = Array.from(gridInner.querySelectorAll('.lead-card-container'));
          cells.sort(function (a, b) {
            var ar = a.querySelector('.clinic-row');
            var br = b.querySelector('.clinic-row');
            if (!ar || !br) return 0;
            return compareLeadRowsForSort(ar, br);
          });
          cells.forEach(function (cell) { gridInner.appendChild(cell); });
        }
        refreshGridCardsDraggable();
      }
      window.applyLeadSort = applyLeadSort;
      function setLeadSortMode(mode) {
        leadSortMode = mode || 'default';
        try {
          localStorage.setItem(LEAD_SORT_KEY, leadSortMode);
        } catch (e) { /* ignore */ }
        syncLeadSortSelect();
        currentLeadPage = 1;
        applyLeadSort();
        applyLeadPagination(false);
        refreshSelectAllState();
        refreshSelectionVisuals();
      }
      window.setLeadSortMode = setLeadSortMode;
      function initClinicViewModeFromStorage() {
        try {
          if (localStorage.getItem(VIEW_MODE_KEY) === 'grid') setClinicViewMode('grid');
          else setClinicViewMode('list');
        } catch (e) {
          setClinicViewMode('list');
        }
      }
      window.initClinicViewModeFromStorage = initClinicViewModeFromStorage;
      var LEAD_FILTER_EXCLUSIVE_PAIRS = {
        'filter-sent-message-only': 'filter-unsent-message-only',
        'filter-unsent-message-only': 'filter-sent-message-only',
        'filter-chain-only': 'filter-no-chain-only',
        'filter-no-chain-only': 'filter-chain-only',
      };
      function toggleLeadFilterButton(btn) {
        if (!btn) return;
        const on = btn.getAttribute('aria-pressed') !== 'true';
        btn.setAttribute('aria-pressed', on ? 'true' : 'false');
        if (on) {
          var otherId = LEAD_FILTER_EXCLUSIVE_PAIRS[btn.id];
          if (otherId) {
            var other = document.getElementById(otherId);
            if (other) other.setAttribute('aria-pressed', 'false');
          }
        }
        applyTableFilter({ resetPage: true });
        refreshSelectAllState();
        refreshSelectionVisuals();
      }
      window.toggleLeadFilterButton = toggleLeadFilterButton;
      function getLeadTagFilterKey() {
        return window.LEAD_TAG_FILTER_KEY || 'clinic_crm_lead_tag_filter';
      }
      function getLeadTagFilterSlugs() {
        try {
          var raw = localStorage.getItem(getLeadTagFilterKey());
          if (!raw) return [];
          var parsed = JSON.parse(raw);
          if (!Array.isArray(parsed)) return [];
          var seen = {};
          var out = [];
          parsed.forEach(function (item) {
            var slug = String(item || '').trim();
            if (!slug || seen[slug]) return;
            seen[slug] = true;
            out.push(slug);
          });
          return out;
        } catch (err) {
          return [];
        }
      }
      window.getLeadTagFilterSlugs = getLeadTagFilterSlugs;
      function saveLeadTagFilterSlugs(slugs) {
        var cleaned = [];
        var seen = {};
        (slugs || []).forEach(function (item) {
          var slug = String(item || '').trim();
          if (!slug || seen[slug]) return;
          seen[slug] = true;
          cleaned.push(slug);
        });
        try {
          if (cleaned.length) localStorage.setItem(getLeadTagFilterKey(), JSON.stringify(cleaned));
          else localStorage.removeItem(getLeadTagFilterKey());
        } catch (err) { /* ignore */ }
        return cleaned;
      }
      window.saveLeadTagFilterSlugs = saveLeadTagFilterSlugs;
      function syncLeadTagFilterUi() {
        var slugs = getLeadTagFilterSlugs();
        var selected = {};
        slugs.forEach(function (slug) { selected[slug] = true; });
        document.querySelectorAll('.lead-tag-filter-chip').forEach(function (btn) {
          var on = !!selected[btn.getAttribute('data-tag-slug')];
          btn.setAttribute('aria-pressed', on ? 'true' : 'false');
          syncLeadTagFilterChipVisibility(btn);
        });
        var clearBtn = document.getElementById('lead-tag-filter-clear');
        if (clearBtn) {
          var showClear = slugs.length > 0;
          clearBtn.hidden = !showClear;
          clearBtn.classList.toggle('hidden', !showClear);
        }
      }
      window.syncLeadTagFilterUi = syncLeadTagFilterUi;
      function leadRowMatchesTagFilter(row, slugs) {
        if (!slugs || !slugs.length) return true;
        var rowTags = String(row.getAttribute('data-tags') || '').split(/\s+/).filter(Boolean);
        for (var i = 0; i < slugs.length; i += 1) {
          if (rowTags.indexOf(slugs[i]) === -1) return false;
        }
        return true;
      }
      window.leadRowMatchesTagFilter = leadRowMatchesTagFilter;
      function leadRowMatchesCurrentFilters(row, opts) {
        if (!row) return true;
        opts = opts || {};
        const searchInput = document.getElementById('table-search');
        const q = searchInput ? searchInput.value.trim().toLowerCase() : '';
        const vipBtn = document.getElementById('filter-very-important-only');
        const vipOnly = vipBtn && vipBtn.getAttribute('aria-pressed') === 'true';
        const chainBtn = document.getElementById('filter-chain-only');
        const chainOnly = chainBtn && chainBtn.getAttribute('aria-pressed') === 'true';
        const noChainBtn = document.getElementById('filter-no-chain-only');
        const noChainOnly = noChainBtn && noChainBtn.getAttribute('aria-pressed') === 'true';
        const sentBtn = document.getElementById('filter-sent-message-only');
        const sentOnly = sentBtn && sentBtn.getAttribute('aria-pressed') === 'true';
        const unsentBtn = document.getElementById('filter-unsent-message-only');
        const unsentOnly = unsentBtn && unsentBtn.getAttribute('aria-pressed') === 'true';
        const tagSlugs = getLeadTagFilterSlugs();
        const hay = (row.getAttribute('data-search') || '').toLowerCase();
        const isVip = row.getAttribute('data-very-important') === '1';
        const isChain = row.getAttribute('data-is-chain') === '1';
        const hasSent = row.getAttribute('data-whatsapp-dispatched') === '1';
        if (!opts.skipKeyword && !globalSearchActive && q && !hay.includes(q)) return false;
        if (vipOnly && !isVip) return false;
        if (chainOnly && !isChain) return false;
        if (noChainOnly && isChain) return false;
        if (sentOnly && !hasSent) return false;
        if (unsentOnly && hasSent) return false;
        if (tagSlugs.length && !leadRowMatchesTagFilter(row, tagSlugs)) return false;
        return true;
      }
      window.leadRowMatchesCurrentFilters = leadRowMatchesCurrentFilters;
      function clinicLeadWouldHideFromCurrentFilters(leadId) {
        var row = document.querySelector('.clinic-row[data-clinic-id="' + leadId + '"]');
        return !!(row && !leadRowMatchesCurrentFilters(row));
      }
      window.clinicLeadWouldHideFromCurrentFilters = clinicLeadWouldHideFromCurrentFilters;
      function leadFilterExitNodes(leadId) {
        var nodes = [];
        var cell = document.getElementById('lead-grid-cell-' + leadId);
        if (cell) nodes.push(cell);
        document.querySelectorAll('tr.clinic-row[data-clinic-id="' + leadId + '"]').forEach(function (tr) {
          nodes.push(tr);
        });
        return nodes;
      }
      function fadeLeadsOutOfCurrentFilters(leadIds) {
        var seen = {};
        var fadeIds = [];
        (leadIds || []).forEach(function (raw) {
          var id = String(raw == null ? '' : raw).trim();
          if (!id || seen[id]) return;
          seen[id] = true;
          if (clinicLeadWouldHideFromCurrentFilters(id)) fadeIds.push(id);
        });
        if (!fadeIds.length) {
          applyTableFilter({ resetPage: false });
          refreshSelectAllState();
          refreshSelectionVisuals();
          return;
        }
        fadeIds.forEach(function (id) {
          leadFilterExitNodes(id).forEach(function (el) {
            el.classList.add('lead-card--filter-exit');
          });
        });
        window.setTimeout(function () {
          fadeIds.forEach(function (id) {
            document.querySelectorAll('.clinic-row[data-clinic-id="' + id + '"]').forEach(function (row) {
              row.classList.add('hidden');
              var cb = row.querySelector('.clinic-select-cb');
              if (cb) cb.checked = false;
              var cell = row.closest('.lead-card-container');
              if (cell) cell.classList.add('hidden');
            });
            leadFilterExitNodes(id).forEach(function (el) {
              el.classList.add('hidden');
              el.classList.remove('lead-card--filter-exit');
            });
          });
          applyTableFilter({ resetPage: false });
          refreshSelectAllState();
          refreshSelectionVisuals();
        }, 300);
      }
      window.fadeLeadsOutOfCurrentFilters = fadeLeadsOutOfCurrentFilters;
      function applyLeadTagSlugsToDom(leadId, slugs) {
        var cleaned = [];
        var seen = {};
        (slugs || []).forEach(function (item) {
          var slug = String(item || '').trim();
          if (!slug || seen[slug]) return;
          seen[slug] = true;
          cleaned.push(slug);
        });
        document.querySelectorAll('.clinic-row[data-clinic-id="' + leadId + '"]').forEach(function (row) {
          syncRowDataSearch(row, undefined, undefined, undefined, cleaned);
          var typeCell = row.querySelector('.clinic-type-cell');
          if (!typeCell) return;
          var wrap = document.createElement('div');
          wrap.className = 'lead-tag-chips';
          cleaned.forEach(function (slug) {
            var span = document.createElement('span');
            span.className = 'lead-tag-chip lead-tag-chip--' + slug;
            span.setAttribute('data-tag-slug', slug);
            var filterLabel = document.querySelector(
              '#lead-tag-filter .lead-tag-filter-chip[data-tag-slug="' + slug + '"] .lead-tag-filter-label'
            );
            var label = filterLabel ? filterLabel.textContent.trim() : slug;
            span.setAttribute('title', label);
            span.textContent = label;
            wrap.appendChild(span);
          });
          typeCell.innerHTML = '';
          typeCell.appendChild(wrap);
        });
      }
      window.applyLeadTagSlugsToDom = applyLeadTagSlugsToDom;
      function isLeadIconFilterActive() {
        var queued = document.getElementById('filter-queued-only');
        if (queued && queued.getAttribute('aria-pressed') === 'true') return true;
        var vip = document.getElementById('filter-very-important-only');
        if (vip && vip.getAttribute('aria-pressed') === 'true') return true;
        var chain = document.getElementById('filter-chain-only');
        if (chain && chain.getAttribute('aria-pressed') === 'true') return true;
        var noChain = document.getElementById('filter-no-chain-only');
        if (noChain && noChain.getAttribute('aria-pressed') === 'true') return true;
        var sent = document.getElementById('filter-sent-message-only');
        if (sent && sent.getAttribute('aria-pressed') === 'true') return true;
        var unsent = document.getElementById('filter-unsent-message-only');
        if (unsent && unsent.getAttribute('aria-pressed') === 'true') return true;
        return false;
      }
      window.isLeadIconFilterActive = isLeadIconFilterActive;
      function isQueuedOutreachFilterActive() {
        var btn = document.getElementById('filter-queued-only');
        return !!(btn && btn.getAttribute('aria-pressed') === 'true');
      }
      window.isQueuedOutreachFilterActive = isQueuedOutreachFilterActive;
      function refreshTableSearchClearVisibility() {
        var si = document.getElementById('table-search');
        var btn = document.getElementById('table-search-clear');
        if (!btn) return;
        var hasTags = typeof getLeadTagFilterSlugs === 'function' && getLeadTagFilterSlugs().length > 0;
        var hasSearch = !!(si && si.value.trim().length > 0);
        var has = hasSearch || isLeadIconFilterActive() || hasTags || !!globalSearchActive;
        btn.hidden = !has;
        btn.setAttribute('aria-hidden', has ? 'false' : 'true');
        refreshLeadFilterTagSaveButton();
        refreshLeadFilterTagActiveState();
      }
      window.refreshTableSearchClearVisibility = refreshTableSearchClearVisibility;
      async function clearLeadToolbarQuickFilters() {
        var queued = document.getElementById('filter-queued-only');
        var wasQueued = queued && queued.getAttribute('aria-pressed') === 'true';
        if (queued) queued.setAttribute('aria-pressed', 'false');
        var vip = document.getElementById('filter-very-important-only');
        if (vip) vip.setAttribute('aria-pressed', 'false');
        var chain = document.getElementById('filter-chain-only');
        if (chain) chain.setAttribute('aria-pressed', 'false');
        var noChain = document.getElementById('filter-no-chain-only');
        if (noChain) noChain.setAttribute('aria-pressed', 'false');
        var sent = document.getElementById('filter-sent-message-only');
        if (sent) sent.setAttribute('aria-pressed', 'false');
        var unsent = document.getElementById('filter-unsent-message-only');
        if (unsent) unsent.setAttribute('aria-pressed', 'false');
        if (typeof saveLeadTagFilterSlugs === 'function') saveLeadTagFilterSlugs([]);
        var wasGlobal = !!globalSearchActive;
        await exitGlobalSearchMode({ clearInput: true });
        if (!wasGlobal && wasQueued && typeof window.__refreshCurrentLeadFolder === 'function') {
          await window.__refreshCurrentLeadFolder();
        }
        applyTableFilter({ resetPage: true });
        refreshSelectAllState();
        refreshSelectionVisuals();
      }
      window.clearLeadToolbarQuickFilters = clearLeadToolbarQuickFilters;
      function loadLeadFilterTags() {
        try {
          var raw = localStorage.getItem(LEAD_FILTER_TAGS_KEY);
          if (!raw) return [];
          var parsed = JSON.parse(raw);
          if (!Array.isArray(parsed)) return [];
          var out = [];
          var seen = Object.create(null);
          parsed.forEach(function (item) {
            var text = String(item || '').trim().slice(0, LEAD_FILTER_TAG_LEN_MAX);
            if (!text || seen[text]) return;
            seen[text] = true;
            out.push(text);
          });
          return out.slice(0, LEAD_FILTER_TAG_MAX);
        } catch (e) {
          return [];
        }
      }
      window.loadLeadFilterTags = loadLeadFilterTags;
      function saveLeadFilterTags(tags) {
        try {
          localStorage.setItem(LEAD_FILTER_TAGS_KEY, JSON.stringify(tags.slice(0, LEAD_FILTER_TAG_MAX)));
        } catch (e) { /* ignore */ }
      }
      window.saveLeadFilterTags = saveLeadFilterTags;
      function escapeLeadFilterTagHtml(text) {
        return String(text)
          .replace(/&/g, '&amp;')
          .replace(/</g, '&lt;')
          .replace(/>/g, '&gt;')
          .replace(/"/g, '&quot;');
      }
      window.escapeLeadFilterTagHtml = escapeLeadFilterTagHtml;
      function refreshLeadFilterTagSaveButton() {
        var saveBtn = document.getElementById('lead-filter-tag-save');
        var si = document.getElementById('table-search');
        if (!saveBtn || !si) return;
        var text = si.value.trim();
        var tags = loadLeadFilterTags();
        saveBtn.disabled = !text || tags.indexOf(text) !== -1;
      }
      window.refreshLeadFilterTagSaveButton = refreshLeadFilterTagSaveButton;
      function refreshLeadFilterTagActiveState() {
        var si = document.getElementById('table-search');
        var current = si ? si.value.trim() : '';
        document.querySelectorAll('.lead-filter-tag').forEach(function (chip) {
          var label = chip.getAttribute('data-tag') || '';
          var active = current && label === current;
          chip.classList.toggle('lead-filter-tag--active', active);
          var applyBtn = chip.querySelector('.lead-filter-tag-apply');
          if (applyBtn) applyBtn.setAttribute('aria-pressed', active ? 'true' : 'false');
        });
      }
      window.refreshLeadFilterTagActiveState = refreshLeadFilterTagActiveState;
      function renderLeadFilterTags() {
        var list = document.getElementById('lead-filter-tags-list');
        if (!list) return;
        var tags = loadLeadFilterTags();
        var si = document.getElementById('table-search');
        var current = si ? si.value.trim() : '';
        list.innerHTML = tags.map(function (tag) {
          var active = current && tag === current;
          return (
            '<span class="lead-filter-tag' + (active ? ' lead-filter-tag--active' : '') + '" data-tag="' + escapeLeadFilterTagHtml(tag) + '" role="listitem">' +
              '<button type="button" class="lead-filter-tag-apply" aria-pressed="' + (active ? 'true' : 'false') + '" title="Use keyword: ' + escapeLeadFilterTagHtml(tag) + '">' +
                escapeLeadFilterTagHtml(tag) +
              '</button>' +
              '<button type="button" class="lead-filter-tag-remove" aria-label="Remove keyword tag ' + escapeLeadFilterTagHtml(tag) + '" title="Remove tag">×</button>' +
            '</span>'
          );
        }).join('');
        refreshLeadFilterTagSaveButton();
      }
      window.renderLeadFilterTags = renderLeadFilterTags;
      function applyLeadFilterTag(text) {
        var si = document.getElementById('table-search');
        if (!si) return;
        si.value = text;
        applyTableFilter({ resetPage: true });
        si.focus();
      }
      window.applyLeadFilterTag = applyLeadFilterTag;
      function addLeadFilterTag(text) {
        var cleaned = String(text || '').trim().slice(0, LEAD_FILTER_TAG_LEN_MAX);
        if (!cleaned) return;
        var tags = loadLeadFilterTags();
        if (tags.indexOf(cleaned) !== -1) return;
        tags.unshift(cleaned);
        saveLeadFilterTags(tags);
        renderLeadFilterTags();
      }
      window.addLeadFilterTag = addLeadFilterTag;
      function removeLeadFilterTag(text) {
        var cleaned = String(text || '').trim();
        if (!cleaned) return;
        var tags = loadLeadFilterTags().filter(function (t) { return t !== cleaned; });
        saveLeadFilterTags(tags);
        renderLeadFilterTags();
        refreshLeadFilterTagActiveState();
      }
      window.removeLeadFilterTag = removeLeadFilterTag;
      function applyTableFilter(opts) {
        opts = opts || {};
        syncLeadTagFilterUi();
        document.querySelectorAll('.clinic-row').forEach(function (row) {
          if (row.classList.contains('lead-card--filter-exit')) return;
          var cell = row.closest('.lead-card-container');
          if (cell && cell.classList.contains('lead-card--filter-exit')) return;
          var hide = !leadRowMatchesCurrentFilters(row, opts);
          row.classList.toggle('hidden', hide);
          if (cell) cell.classList.toggle('hidden', hide);
        });
        if (opts.resetPage) currentLeadPage = 1;
        applyLeadPagination(false);
        refreshTableSearchClearVisibility();
        refreshFilteredLeadCount();
      }
      window.applyTableFilter = applyTableFilter;
      function canReorderGridCards() {
        if (!document.documentElement.classList.contains('cv-grid')) return false;
        if (leadSortMode !== 'default') return false;
        var si = document.getElementById('table-search');
        if (si && si.value.trim()) return false;
        var vip = document.getElementById('filter-very-important-only');
        if (vip && vip.getAttribute('aria-pressed') === 'true') return false;
        var chain = document.getElementById('filter-chain-only');
        if (chain && chain.getAttribute('aria-pressed') === 'true') return false;
        var noChain = document.getElementById('filter-no-chain-only');
        if (noChain && noChain.getAttribute('aria-pressed') === 'true') return false;
        var sent = document.getElementById('filter-sent-message-only');
        if (sent && sent.getAttribute('aria-pressed') === 'true') return false;
        var unsent = document.getElementById('filter-unsent-message-only');
        if (unsent && unsent.getAttribute('aria-pressed') === 'true') return false;
        if (typeof window.isQueuedOutreachFilterActive === 'function' && window.isQueuedOutreachFilterActive()) return false;
        if (getLeadTagFilterSlugs().length > 0) return false;
        var filtered = getFilteredClinicRowsInOrder();
        if (filtered.length > readLeadsPerPage()) return false;
        return true;
      }
      window.canReorderGridCards = canReorderGridCards;
      function refreshGridCardsDraggable() {
        var ok = canReorderGridCards();
        document.querySelectorAll('#clinics-grid-inner .clinic-card').forEach(function (card) {
          if (ok) {
            card.setAttribute('draggable', 'true');
            card.classList.add('clinic-card--sortable');
          } else {
            card.removeAttribute('draggable');
            card.classList.remove('clinic-card--sortable');
          }
        });
      }
      window.refreshGridCardsDraggable = refreshGridCardsDraggable;
      function getLeadGroupTabLabel(tabId) {
        var want = normalizeLeadGroupTabId(tabId);
        var btn = document.querySelector('#lead-group-tabs .lead-group-tab[data-group-id="' + want + '"]');
        if (!btn) return want === 'uncategorized' ? 'New' : 'folder';
        var nameEl = btn.querySelector('.lead-group-tab-label');
        if (nameEl) {
          var text = (nameEl.textContent || '').trim();
          if (text) return text;
        }
        return want === 'uncategorized' ? 'New' : 'folder';
      }
      window.getLeadGroupTabLabel = getLeadGroupTabLabel;
      function updateGlobalSearchBanner(meta) {
        meta = meta || {};
        var banner = document.getElementById('global-search-banner');
        var textEl = document.getElementById('global-search-banner-text');
        if (!banner || !textEl) return;
        if (!globalSearchActive) {
          banner.classList.add('hidden');
          textEl.textContent = '';
          return;
        }
        var parts = ['Searching all folders for "' + globalSearchQuery + '"'];
        if (meta.count != null) {
          parts.push(String(meta.count) + ' result' + (meta.count === 1 ? '' : 's'));
        }
        if (meta.truncated) parts.push('(first 200 shown)');
        parts.push('· Back to ' + getLeadGroupTabLabel(tabBeforeGlobalSearch));
        textEl.textContent = parts.join(' ');
        banner.classList.remove('hidden');
      }
      window.updateGlobalSearchBanner = updateGlobalSearchBanner;
      function applyLeadsTableFragment(data) {
        var tb = document.getElementById('clinics-table-body');
        var gridInner = document.getElementById('clinics-grid-inner');
        if (tb) tb.innerHTML = data.tbody_html;
        if (gridInner) gridInner.innerHTML = data.grid_html;
        if (data.funnel_metrics) updateFunnelMetricsStrip(data.funnel_metrics);
        if (data.group_counts) updateLeadGroupTabCounts(data.group_counts);
        if (data.tag_counts) updateLeadTagFilterCounts(data.tag_counts);
        if (window.htmx) {
          if (tb) window.htmx.process(tb);
        }
        if (typeof window.__ensureGridHtmxBound === 'function') window.__ensureGridHtmxBound();
      }
      window.applyLeadsTableFragment = applyLeadsTableFragment;
      function syncLeadsAfterGlobalSearchSwap() {
        currentLeadPage = 1;
        initClinicViewModeFromStorage();
        applyLeadSort();
        refreshSelectAllState();
        refreshSelectionVisuals();
        refreshSetCategoryButtonState();
        refreshBulkAssignGroupButtonState();
        applyTableFilter({ resetPage: false, skipKeyword: true });
        refreshTableSearchClearVisibility();
        refreshFilteredLeadCount();
        refreshGridCardsDraggable();
        if (typeof window.__syncLeadChatIndicatorPolling === 'function') {
          window.__syncLeadChatIndicatorPolling();
        }
      }
      window.syncLeadsAfterGlobalSearchSwap = syncLeadsAfterGlobalSearchSwap;
      async function runGlobalLeadSearch(q) {
        var reqId = ++globalSearchRequestId;
        if (!globalSearchActive) tabBeforeGlobalSearch = currentLeadGroupTabId;
        if (leadGroupTabBusy) return;
        leadGroupTabBusy = true;
        try {
          var data = await fetchLeadsTableFragment(null, { globalSearch: true, q: q });
          if (reqId !== globalSearchRequestId) return;
          if (!data.ok) throw new Error((data.detail && String(data.detail)) || 'Bad response');
          applyLeadsTableFragment(data);
          globalSearchActive = true;
          globalSearchQuery = q;
          updateGlobalSearchBanner({
            count: data.global_search_count,
            truncated: data.global_search_truncated,
          });
          syncLeadsAfterGlobalSearchSwap();
        } catch (err) {
          console.error(err);
        } finally {
          leadGroupTabBusy = false;
        }
      }
      window.runGlobalLeadSearch = runGlobalLeadSearch;
      async function exitGlobalSearchMode(opts) {
        opts = opts || {};
        globalSearchRequestId += 1;
        clearTimeout(globalSearchDebounceTimer);
        var wasActive = globalSearchActive;
        globalSearchActive = false;
        globalSearchQuery = '';
        updateGlobalSearchBanner();
        if (opts.clearInput) {
          var si = document.getElementById('table-search');
          if (si) si.value = '';
        }
        refreshTableSearchClearVisibility();
        refreshLeadFilterTagActiveState();
        if (wasActive && !opts.skipTabRestore) {
          await switchLeadGroupTab(tabBeforeGlobalSearch || currentLeadGroupTabId, {
            force: true,
            skipHistory: true,
            skipGlobalSearchExit: true,
          });
        } else if (!wasActive && !opts.clearInput) {
          applyTableFilter({ resetPage: true });
        }
      }
      window.exitGlobalSearchMode = exitGlobalSearchMode;
      function handleLeadSearchInput() {
        var searchInput = document.getElementById('table-search');
        var raw = searchInput ? searchInput.value.trim() : '';
        refreshTableSearchClearVisibility();
        if (raw.length >= GLOBAL_SEARCH_MIN_LEN) {
          clearTimeout(globalSearchDebounceTimer);
          globalSearchDebounceTimer = window.setTimeout(function () {
            runGlobalLeadSearch(raw);
          }, 300);
          return;
        }
        if (globalSearchActive) {
          exitGlobalSearchMode({ clearInput: false });
          return;
        }
        applyTableFilter({ resetPage: true });
        refreshLeadFilterTagActiveState();
      }
      window.handleLeadSearchInput = handleLeadSearchInput;
      function highlightLeadRow(leadId) {
        var sel = '.clinic-row[data-clinic-id="' + leadId + '"]';
        document.querySelectorAll(sel).forEach(function (row) {
          row.classList.remove('lead-page-hidden');
          var cell = row.closest('.lead-card-container');
          if (cell) cell.classList.remove('lead-page-hidden');
          row.classList.add('clinic-row--search-highlight');
          if (typeof row.scrollIntoView === 'function') {
            row.scrollIntoView({ block: 'center', behavior: 'smooth' });
          }
        });
        window.setTimeout(function () {
          document.querySelectorAll(sel).forEach(function (row) {
            row.classList.remove('clinic-row--search-highlight');
          });
        }, 3000);
      }
      window.highlightLeadRow = highlightLeadRow;
      function revealAndHighlightLead(leadId) {
        var id = String(leadId);
        var rows = Array.from(document.querySelectorAll('.clinic-row:not(.hidden)'));
        var targetIdx = -1;
        for (var i = 0; i < rows.length; i += 1) {
          if (rows[i].getAttribute('data-clinic-id') === id) {
            targetIdx = i;
            break;
          }
        }
        if (targetIdx === -1) {
          highlightLeadRow(id);
          return;
        }
        var perPage = readLeadsPerPage();
        var page = Math.floor(targetIdx / perPage) + 1;
        goToLeadPage(page);
        window.requestAnimationFrame(function () {
          highlightLeadRow(id);
        });
      }
      window.revealAndHighlightLead = revealAndHighlightLead;
      async function jumpToLeadInFolder(tabId, leadId) {
        pendingHighlightLeadId = String(leadId);
        globalSearchRequestId += 1;
        clearTimeout(globalSearchDebounceTimer);
        globalSearchActive = false;
        globalSearchQuery = '';
        updateGlobalSearchBanner();
        var si = document.getElementById('table-search');
        if (si) si.value = '';
        refreshTableSearchClearVisibility();
        await switchLeadGroupTab(tabId, {
          force: true,
          historyMode: 'push',
          skipGlobalSearchExit: true,
        });
      }
      window.jumpToLeadInFolder = jumpToLeadInFolder;
})();
