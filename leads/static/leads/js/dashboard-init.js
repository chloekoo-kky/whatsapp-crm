(function () {
  if (window.__leadsDashboardSkip) return;
      /** Prefer csrftoken cookie so the header always matches what Django validates (see Django AJAX CSRF docs). */
      window.MANUAL_PHONE_MAX = 8;
      window.manualPhoneRowTpl = document.getElementById('manual-phone-row-template');
      document.getElementById('clinic-edit-add-phone')?.addEventListener('click', function () {
        var c = document.getElementById('clinic-edit-phones-list');
        if (c && c.querySelectorAll('.manual-phone-row').length < MANUAL_PHONE_MAX) appendManualPhoneRow(c, '');
      });
      document.getElementById('lead-create-add-phone')?.addEventListener('click', function () {
        var c = document.getElementById('lead-create-phones-list');
        if (c && c.querySelectorAll('.manual-phone-row').length < MANUAL_PHONE_MAX) appendManualPhoneRow(c, '');
      });
      document.getElementById('clinic-edit-phones-list')?.addEventListener('click', function (e) {
        var b = e.target.closest('.manual-phone-remove');
        if (!b || !this.contains(b)) return;
        e.preventDefault();
        var row = b.closest('.manual-phone-row');
        if (row && this.querySelectorAll('.manual-phone-row').length > 1) row.remove();
        syncManualPhoneRemoveVisibility(this);
      });
      document.getElementById('lead-create-phones-list')?.addEventListener('click', function (e) {
        var b = e.target.closest('.manual-phone-remove');
        if (!b || !this.contains(b)) return;
        e.preventDefault();
        var row = b.closest('.manual-phone-row');
        if (row && this.querySelectorAll('.manual-phone-row').length > 1) row.remove();
        syncManualPhoneRemoveVisibility(this);
      });
      window.huntLimitInput = document.getElementById('hunt-limit-value');
      window.limitButtons = document.querySelectorAll('.limit-btn');
      limitButtons.forEach(function (btn) {
        btn.addEventListener('click', function () {
          setLimit(btn.getAttribute('data-limit'), true);
        });
      });
      setLimit(huntLimitInput ? huntLimitInput.value : dashboardJsConfig.defaultLimit, true);
      window.requireWebsiteToggle = document.getElementById('hunt-require-website');
      bindHuntOptionToggle(requireWebsiteToggle, REQUIRE_WEBSITE_KEY);
      window.chatIndicatorPollToggle = document.getElementById('chat-indicator-poll-toggle');
      bindHuntOptionToggle(chatIndicatorPollToggle, CHAT_INDICATOR_POLL_KEY);
      window.clinicSaveStatusTimer = null;
      window.selectAll = document.getElementById('select-all-clinics');
      window.currentLeadPage = 1;
      window.folderTotalPipelineCount = 0;
      window.leadChatIndicatorPollTimer = null;
      window.leadChatIndicatorSnapshot = '';
      if (chatIndicatorPollToggle) {
        chatIndicatorPollToggle.addEventListener('change', function () {
          window.__syncLeadChatIndicatorPolling();
        });
      }
      document.getElementById('bulk-wa-queue-btn')?.addEventListener('click', function () {
        bulkPushSelectedToWhatsappQueue();
      });
      document.getElementById('bulk-dequeue-btn')?.addEventListener('click', function () {
        bulkDequeueSelectedFromQueue();
      });
      // --- Choose batch (assign selected Queue leads to a WhatsApp batch) ---
      window.chooseBatchDialog = document.getElementById('choose-batch-dialog');
      document.getElementById('bulk-choose-batch-btn')?.addEventListener('click', openChooseBatchDialog);
      document.getElementById('choose-batch-select')?.addEventListener('change', toggleChooseBatchNewFields);
      document.getElementById('choose-batch-close-x')?.addEventListener('click', closeChooseBatchDialog);
      document.getElementById('choose-batch-cancel')?.addEventListener('click', closeChooseBatchDialog);
      document.getElementById('choose-batch-form')?.addEventListener('submit', function (e) {
        e.preventDefault();
        submitChooseBatch();
      });
      chooseBatchDialog?.addEventListener('click', function (e) {
        if (e.target === chooseBatchDialog) closeChooseBatchDialog();
      });
      /** Unique lead ids among checked boxes in the current visible filter/view. */
      // Lead id of the last plainly-selected card; anchor for shift+click ranges.
      window.selectionAnchorId = null;
      if (selectAll) {
        selectAll.addEventListener('change', function () {
          const seen = Object.create(null);
          getVisibleClinicRows().forEach(function (row) {
            const cb = row.querySelector('.clinic-select-cb');
            if (!cb || seen[cb.value]) return;
            seen[cb.value] = true;
            setLeadCheckboxSelected(cb.value, selectAll.checked);
          });
          refreshSelectAllState();
          refreshSelectionVisuals();
        });
      }
      refreshBulkActionDock();
      window.exportXlsxBtn = document.getElementById('export-xlsx-btn');
      window.exportXlsxStatus = document.getElementById('export-xlsx-status');
      window.exportXlsxIcon = document.getElementById('export-xlsx-icon');
      window.exportXlsxSpinner = document.getElementById('export-xlsx-spinner');
      if (exportXlsxBtn) {
        exportXlsxBtn.addEventListener('click', function () {
          exportXlsxShowErr('');
          const ids = getUniqueSelectedLeadIds();
          var url = dashboardJsConfig.exportXlsxUrl || '/leads/export/xlsx/';
          var gid = typeof currentLeadGroupTabId !== 'undefined' && currentLeadGroupTabId != null
            ? String(currentLeadGroupTabId)
            : 'uncategorized';
          var q = new URLSearchParams();
          q.set('group_id', gid);
          if (ids.length) q.set('ids', ids.join(','));
          url += (url.indexOf('?') >= 0 ? '&' : '?') + q.toString();
          exportXlsxSetBusy(true);
          fetch(url, { method: 'GET', credentials: 'same-origin' })
            .then(function (res) {
              if (!res.ok) {
                return res.text().then(function (txt) {
                  throw new Error((txt && txt.slice(0, 200)) || ('HTTP ' + res.status));
                });
              }
              var cd = res.headers.get('Content-Disposition') || '';
              var m = /filename="([^"]+)"/i.exec(cd) || /filename=([^;]+)/i.exec(cd);
              var fname = (m && m[1] ? m[1].trim() : '') || 'clinic_leads.xlsx';
              return res.blob().then(function (blob) {
                return { blob: blob, fname: fname };
              });
            })
            .then(function (o) {
              var a = document.createElement('a');
              a.href = URL.createObjectURL(o.blob);
              a.download = o.fname;
              document.body.appendChild(a);
              a.click();
              a.remove();
              window.setTimeout(function () {
                URL.revokeObjectURL(a.href);
              }, 60_000);
            })
            .catch(function (err) {
              exportXlsxShowErr((err && err.message ? err.message : String(err)) || 'Export failed.');
            })
            .finally(function () {
              exportXlsxSetBusy(false);
            });
        });
      }
      // ----- Full backup (all folders) download -----
      window.backupAllBtn = document.getElementById('backup-all-btn');
      window.backupAllIcon = document.getElementById('backup-all-icon');
      window.backupAllSpinner = document.getElementById('backup-all-spinner');
      if (backupAllBtn) {
        backupAllBtn.addEventListener('click', function () {
          exportXlsxShowErr('');
          const ids = getUniqueSelectedLeadIds();
          var url = dashboardJsConfig.exportFullBackupUrl || '/leads/export/backup/';
          if (ids.length) {
            var q = new URLSearchParams();
            q.set('ids', ids.join(','));
            url += (url.indexOf('?') >= 0 ? '&' : '?') + q.toString();
          }
          backupAllSetBusy(true);
          fetch(url, { method: 'GET', credentials: 'same-origin' })
            .then(function (res) {
              if (!res.ok) {
                return res.text().then(function (txt) {
                  throw new Error((txt && txt.slice(0, 200)) || ('HTTP ' + res.status));
                });
              }
              var cd = res.headers.get('Content-Disposition') || '';
              var m = /filename="([^"]+)"/i.exec(cd) || /filename=([^;]+)/i.exec(cd);
              var fname = (m && m[1] ? m[1].trim() : '') || 'clinic_crm_backup.xlsx';
              return res.blob().then(function (blob) {
                return { blob: blob, fname: fname };
              });
            })
            .then(function (o) {
              var a = document.createElement('a');
              a.href = URL.createObjectURL(o.blob);
              a.download = o.fname;
              document.body.appendChild(a);
              a.click();
              a.remove();
              window.setTimeout(function () {
                URL.revokeObjectURL(a.href);
              }, 60_000);
            })
            .catch(function (err) {
              exportXlsxShowErr((err && err.message ? err.message : String(err)) || 'Backup failed.');
            })
            .finally(function () {
              backupAllSetBusy(false);
            });
        });
      }
      // ----- Restore from backup upload -----
      window.restoreBackupBtn = document.getElementById('restore-backup-btn');
      window.restoreBackupInput = document.getElementById('restore-backup-input');
      window.restoreBackupIcon = document.getElementById('restore-backup-icon');
      window.restoreBackupSpinner = document.getElementById('restore-backup-spinner');
      if (restoreBackupBtn && restoreBackupInput) {
        restoreBackupBtn.addEventListener('click', function () {
          exportXlsxShowErr('');
          restoreBackupInput.click();
        });
        restoreBackupInput.addEventListener('change', function () {
          var file = restoreBackupInput.files && restoreBackupInput.files[0];
          if (!file) return;
          if (!window.confirm('Restore leads from "' + file.name + '"?\n\nExisting leads (same name & address) are skipped; only missing leads and their history are added.')) {
            restoreBackupInput.value = '';
            return;
          }
          var fd = new FormData();
          fd.append('backup', file);
          restoreBackupSetBusy(true);
          fetch(dashboardJsConfig.importFullBackupUrl, {
            method: 'POST',
            credentials: 'same-origin',
            headers: { 'X-CSRFToken': getCsrfToken() },
            body: fd,
          })
            .then(function (res) {
              return res.json().then(function (data) {
                return { ok: res.ok, data: data };
              });
            })
            .then(function (o) {
              if (!o.ok || !o.data.ok) {
                throw new Error((o.data && o.data.detail) || 'Restore failed.');
              }
              var d = o.data;
              window.alert(
                'Restore complete:\n' +
                  '• ' + (d.leads_created || 0) + ' leads added (' + (d.leads_skipped || 0) + ' already existed)\n' +
                  '• ' + (d.groups_created || 0) + ' groups, ' + (d.scripts_created || 0) + ' script templates\n' +
                  '• ' + (d.chats_created || 0) + ' chat messages, ' + (d.logs_created || 0) + ' conversation logs\n' +
                  '• ' + (d.config_created || 0) + ' WhatsApp config'
              );
              window.location.reload();
            })
            .catch(function (err) {
              exportXlsxShowErr((err && err.message ? err.message : String(err)) || 'Restore failed.');
            })
            .finally(function () {
              restoreBackupSetBusy(false);
              restoreBackupInput.value = '';
            });
        });
      }
      window.clinicsPanelEl = document.getElementById('clinics-panel');
      if (clinicsPanelEl) {
        clinicsPanelEl.addEventListener('change', function (e) {
          const t = e.target;
          if (!t.classList || !t.classList.contains('clinic-select-cb')) return;
          const v = t.value;
          const on = t.checked;
          clinicsPanelEl.querySelectorAll('.clinic-select-cb').forEach(function (other) {
            if (other.value === v) other.checked = on;
          });
          refreshSelectAllState();
          refreshSelectionVisuals();
        });
      }
      refreshSelectAllState();
      refreshSelectionVisuals();
      window.leadSortMode = readLeadSortMode();
      if (!window.__leadsToolbarDelegated) {
        window.__leadsToolbarDelegated = true;
        document.body.addEventListener('click', function (e) {
          var viewBtn = e.target.closest('.view-mode-btn');
          if (viewBtn && viewBtn.closest('#leads-controls-bar')) {
            setClinicViewMode(viewBtn.getAttribute('data-view-mode') || 'list');
            return;
          }
          var vipBtn = e.target.closest('#filter-very-important-only');
          if (vipBtn) {
            toggleLeadFilterButton(vipBtn, 'amber');
            return;
          }
          var sentBtn = e.target.closest('#filter-sent-message-only');
          if (sentBtn) {
            toggleLeadFilterButton(sentBtn, 'emerald');
            return;
          }
          if (e.target.closest('#leads-page-prev')) {
            e.preventDefault();
            goToLeadPage(currentLeadPage - 1);
            return;
          }
          if (e.target.closest('#leads-page-next')) {
            e.preventDefault();
            goToLeadPage(currentLeadPage + 1);
          }
        });
        document.body.addEventListener('change', function (e) {
          if (e.target && e.target.id === 'lead-sort-select') {
            setLeadSortMode(e.target.value || 'default');
          }
          if (e.target && e.target.id === 'leads-per-page-select') {
            var perPage = parseInt(e.target.value, 10);
            if (!perPage) return;
            try {
              localStorage.setItem(LEADS_PER_PAGE_KEY, String(perPage));
            } catch (err) { /* ignore */ }
            currentLeadPage = 1;
            applyLeadPagination(false);
          }
        });
      }
      initClinicViewModeFromStorage();
      applyLeadSort();
      syncLeadsPerPageSelect();
      applyTableFilter({ resetPage: false });
      bindSelectableSurface(document.getElementById('clinics-view-list'));
      bindSelectableSurface(document.getElementById('clinics-view-grid'));
      window.LEAD_FILTER_TAGS_KEY = 'clinic_crm_lead_filter_tags';
      window.LEAD_FILTER_TAG_MAX = 24;
      window.LEAD_FILTER_TAG_LEN_MAX = 80;
      document.getElementById('lead-filter-tag-save')?.addEventListener('click', function () {
        var si = document.getElementById('table-search');
        if (!si) return;
        addLeadFilterTag(si.value);
      });
      document.getElementById('lead-filter-tags-list')?.addEventListener('click', function (e) {
        var removeBtn = e.target.closest('.lead-filter-tag-remove');
        if (removeBtn) {
          e.preventDefault();
          e.stopPropagation();
          var chip = removeBtn.closest('.lead-filter-tag');
          if (!chip) return;
          removeLeadFilterTag(chip.getAttribute('data-tag') || '');
          return;
        }
        var applyBtn = e.target.closest('.lead-filter-tag-apply');
        if (!applyBtn) return;
        var chip = applyBtn.closest('.lead-filter-tag');
        if (!chip) return;
        var tag = chip.getAttribute('data-tag') || '';
        var si = document.getElementById('table-search');
        if (si && si.value.trim() === tag) {
          si.value = '';
          applyTableFilter({ resetPage: true });
        } else {
          applyLeadFilterTag(tag);
        }
        refreshLeadFilterTagActiveState();
      });
      window.HUNT_KEYWORD_TAGS_KEY = 'clinic_crm_hunt_keyword_tags';
      window.HUNT_KEYWORD_TAG_MAX = 24;
      window.HUNT_KEYWORD_TAG_LEN_MAX = 120;
      document.getElementById('hunt-keyword-tag-save')?.addEventListener('click', function () {
        var input = document.getElementById('hunt-shop-keyword');
        if (!input) return;
        addHuntKeywordTag(input.value);
      });
      document.getElementById('hunt-keyword-tags-list')?.addEventListener('click', function (e) {
        var removeBtn = e.target.closest('.lead-filter-tag-remove');
        if (removeBtn) {
          e.preventDefault();
          e.stopPropagation();
          var chip = removeBtn.closest('.hunt-keyword-tag');
          if (!chip) return;
          removeHuntKeywordTag(chip.getAttribute('data-tag') || '');
          return;
        }
        var applyBtn = e.target.closest('.lead-filter-tag-apply');
        if (!applyBtn) return;
        var chip = applyBtn.closest('.hunt-keyword-tag');
        if (!chip) return;
        var tag = chip.getAttribute('data-tag') || '';
        var input = document.getElementById('hunt-shop-keyword');
        if (input && input.value.trim() === tag) {
          input.value = '';
          refreshHuntKeywordTagSaveButton();
        } else {
          applyHuntKeywordTag(tag);
        }
        refreshHuntKeywordTagActiveState();
      });
      document.getElementById('hunt-shop-keyword')?.addEventListener('input', function () {
        refreshHuntKeywordTagSaveButton();
        refreshHuntKeywordTagActiveState();
      });
      renderHuntKeywordTags();
      window.HUNT_EXCLUDE_TAGS_KEY = 'clinic_crm_hunt_exclude_keywords';
      window.HUNT_EXCLUDE_TAG_MAX = 12;
      window.HUNT_EXCLUDE_TAG_LEN_MAX = 80;
      document.getElementById('hunt-exclude-tag-save')?.addEventListener('click', function () {
        var input = document.getElementById('hunt-exclude-keyword-input');
        if (!input) return;
        addHuntExcludeTag(input.value);
        input.value = '';
        input.focus();
      });
      document.getElementById('hunt-exclude-tags-list')?.addEventListener('click', function (e) {
        var removeBtn = e.target.closest('.lead-filter-tag-remove');
        if (!removeBtn) return;
        e.preventDefault();
        e.stopPropagation();
        var chip = removeBtn.closest('.hunt-exclude-tag');
        if (!chip) return;
        removeHuntExcludeTag(chip.getAttribute('data-tag') || '');
      });
      document.getElementById('hunt-exclude-keyword-input')?.addEventListener('input', refreshHuntExcludeTagSaveButton);
      document.getElementById('hunt-exclude-keyword-input')?.addEventListener('keydown', function (e) {
        if (e.key !== 'Enter') return;
        e.preventDefault();
        var input = document.getElementById('hunt-exclude-keyword-input');
        if (!input || !input.value.trim()) return;
        addHuntExcludeTag(input.value);
        input.value = '';
      });
      renderHuntExcludeTags();
      window.GLOBAL_SEARCH_MIN_LEN = 2;
      window.globalSearchActive = false;
      window.globalSearchQuery = '';
      window.tabBeforeGlobalSearch = 'uncategorized';
      window.globalSearchDebounceTimer = null;
      window.globalSearchRequestId = 0;
      window.pendingHighlightLeadId = null;
      window.searchInput = document.getElementById('table-search');
      if (searchInput) {
        searchInput.addEventListener('input', handleLeadSearchInput);
      }
      document.getElementById('table-search-clear')?.addEventListener('click', function () {
        exitGlobalSearchMode({ clearInput: true });
      });
      document.getElementById('global-search-banner-exit')?.addEventListener('click', function () {
        exitGlobalSearchMode({ clearInput: true });
      });
      document.getElementById('clinics-panel')?.addEventListener('click', function (e) {
        var badge = e.target.closest('.lead-folder-badge');
        if (!badge) return;
        e.preventDefault();
        e.stopPropagation();
        var tabId = badge.getAttribute('data-folder-tab-id');
        var leadId = badge.getAttribute('data-clinic-id');
        if (!tabId || !leadId) return;
        jumpToLeadInFolder(tabId, leadId);
      });
      refreshTableSearchClearVisibility();
      renderLeadFilterTags();
      window.currentLeadGroupTabId = normalizeLeadGroupTabId(
        typeof dashboardJsConfig.initialLeadGroupTabIdFromPage === 'string' && dashboardJsConfig.initialLeadGroupTabIdFromPage
          ? dashboardJsConfig.initialLeadGroupTabIdFromPage
          : 'uncategorized'
      );
      document.addEventListener('visibilitychange', function () {
        if (typeof window.__syncLeadChatIndicatorPolling === 'function') {
          window.__syncLeadChatIndicatorPolling();
        }
      });
      (function bindLeadGroupTabDragDrop() {
        var wrap = document.getElementById('lead-group-tabs');
        if (!wrap) return;
        var dragTabEl = null;

        function enforceTabAfterUncategorized() {
          var unc = wrap.querySelector('.lead-group-tab[data-group-id="uncategorized"]');
          if (!unc || !dragTabEl) return;
          var uncIdx = Array.prototype.indexOf.call(wrap.children, unc);
          var dragIdx = Array.prototype.indexOf.call(wrap.children, dragTabEl);
          if (dragIdx !== -1 && dragIdx < uncIdx) {
            wrap.insertBefore(dragTabEl, unc.nextElementSibling);
          }
        }

        function placeDragTabByPointer(clientX) {
          var newBtn = document.getElementById('lead-group-new-btn');
          var unc = wrap.querySelector('.lead-group-tab[data-group-id="uncategorized"]');
          var list = wrap.querySelectorAll('.lead-group-tab--draggable');
          if (!list.length) return;
          var firstOther = null;
          for (var j = 0; j < list.length; j++) {
            if (list[j] !== dragTabEl) {
              firstOther = list[j];
              break;
            }
          }
          if (firstOther) {
            var r0 = firstOther.getBoundingClientRect();
            if (clientX < r0.left + r0.width / 2) {
              wrap.insertBefore(dragTabEl, firstOther);
              return;
            }
          }
          for (var i = 0; i < list.length; i++) {
            var btn = list[i];
            if (btn === dragTabEl) continue;
            var rect = btn.getBoundingClientRect();
            if (clientX < rect.left + rect.width / 2) {
              wrap.insertBefore(dragTabEl, btn);
              return;
            }
          }
          if (newBtn) wrap.insertBefore(dragTabEl, newBtn);
          else if (unc) {
            var ref = unc.nextElementSibling;
            while (ref && ref === dragTabEl) ref = ref.nextElementSibling;
            if (ref) wrap.insertBefore(dragTabEl, ref);
          }
        }

        wrap.addEventListener('dragstart', function (e) {
          var t = e.target.closest('.lead-group-tab--draggable');
          if (!t || !wrap.contains(t)) return;
          dragTabEl = t;
          e.dataTransfer.effectAllowed = 'move';
          e.dataTransfer.setData('text/plain', t.getAttribute('data-group-id') || '');
          t.classList.add('lead-group-tab--dragging');
        });
        wrap.addEventListener('dragend', function () {
          if (dragTabEl) dragTabEl.classList.remove('lead-group-tab--dragging');
          dragTabEl = null;
        });
        wrap.addEventListener('dragover', function (e) {
          if (!dragTabEl) return;
          e.preventDefault();
          e.dataTransfer.dropEffect = 'move';

          var newBtn = document.getElementById('lead-group-new-btn');
          var unc = wrap.querySelector('.lead-group-tab[data-group-id="uncategorized"]');

          if (newBtn && (e.target === newBtn || newBtn.contains(e.target))) {
            wrap.insertBefore(dragTabEl, newBtn);
            enforceTabAfterUncategorized();
            return;
          }

          var t = e.target.closest('.lead-group-tab[data-group-id]');
          if (t && wrap.contains(t) && t !== dragTabEl) {
            if (t.getAttribute('data-group-id') === 'uncategorized' && unc) {
              var refU = unc.nextElementSibling;
              while (refU && refU === dragTabEl) refU = refU.nextElementSibling;
              if (refU) wrap.insertBefore(dragTabEl, refU);
              else if (newBtn) wrap.insertBefore(dragTabEl, newBtn);
              enforceTabAfterUncategorized();
              return;
            }
            if (t.classList.contains('lead-group-tab--draggable')) {
              var rect = t.getBoundingClientRect();
              var before = e.clientX < rect.left + rect.width / 2;
              if (before) {
                wrap.insertBefore(dragTabEl, t);
              } else {
                var nextEl = t.nextElementSibling;
                while (nextEl && nextEl !== newBtn && nextEl.classList && !nextEl.classList.contains('lead-group-tab--draggable')) {
                  nextEl = nextEl.nextElementSibling;
                }
                if (!nextEl || nextEl === newBtn) wrap.insertBefore(dragTabEl, newBtn);
                else wrap.insertBefore(dragTabEl, nextEl);
              }
            }
          } else {
            placeDragTabByPointer(e.clientX);
          }
          enforceTabAfterUncategorized();
        });
        wrap.addEventListener('drop', function (e) {
          e.preventDefault();
          var ids = [];
          wrap.querySelectorAll('.lead-group-tab--draggable').forEach(function (btn) {
            var id = parseInt(btn.getAttribute('data-group-id'), 10);
            if (!isNaN(id)) ids.push(id);
          });
          if (!ids.length) return;
          fetch(dashboardJsConfig.reorderLeadGroupsUrl, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json', 'X-CSRFToken': getCsrfToken() },
            credentials: 'same-origin',
            body: JSON.stringify({ order: ids }),
          })
            .then(function (res) {
              return res.json().then(function (data) {
                return { res: res, data: data };
              });
            })
            .then(function (o) {
              if (!o.res.ok) {
                window.alert(typeof o.data.detail === 'string' ? o.data.detail : 'Could not save tab order.');
                window.location.reload();
              }
            })
            .catch(function () {
              window.alert('Could not save tab order.');
              window.location.reload();
            });
        });
      })();
      (function bindGridCardDragDrop() {
        var inner = document.getElementById('clinics-grid-inner');
        if (!inner) return;
        var dragCardEl = null;
        inner.addEventListener('dragstart', function (e) {
          if (!canReorderGridCards()) return;
          if (e.target.closest('a, button, input, textarea, label')) {
            e.preventDefault();
            return;
          }
          var card = e.target.closest('.clinic-card');
          if (!card || !inner.contains(card)) return;
          dragCardEl = card;
          e.dataTransfer.effectAllowed = 'move';
          e.dataTransfer.setData('text/plain', card.getAttribute('data-clinic-id') || '');
          card.classList.add('clinic-card--card-dragging');
        });
        inner.addEventListener('dragend', function () {
          if (dragCardEl) dragCardEl.classList.remove('clinic-card--card-dragging');
          dragCardEl = null;
        });
        inner.addEventListener('dragover', function (e) {
          if (!dragCardEl || !canReorderGridCards()) return;
          e.preventDefault();
          e.dataTransfer.dropEffect = 'move';
          var card = e.target.closest('.clinic-card');
          if (!card || !inner.contains(card)) {
            inner.appendChild(dragCardEl);
            return;
          }
          if (card === dragCardEl) return;
          var rect = card.getBoundingClientRect();
          var before = e.clientY < rect.top + rect.height / 2;
          if (before) inner.insertBefore(dragCardEl, card);
          else inner.insertBefore(dragCardEl, card.nextSibling);
        });
        inner.addEventListener('drop', function (e) {
          e.preventDefault();
          if (!canReorderGridCards()) return;
          var ids = [];
          inner.querySelectorAll('.clinic-card').forEach(function (card) {
            var id = card.getAttribute('data-clinic-id');
            if (id) ids.push(parseInt(id, 10));
          });
          if (!ids.length) return;
          var gid = normalizeLeadGroupTabId(currentLeadGroupTabId);
          var body = { group_id: gid, order: ids };
          if (activeSearchRecordId != null) body.search_record = activeSearchRecordId;
          fetch(dashboardJsConfig.reorderLeadsUrl, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json', 'X-CSRFToken': getCsrfToken() },
            credentials: 'same-origin',
            body: JSON.stringify(body),
          })
            .then(function (res) {
              return res.json().then(function (data) {
                return { res: res, data: data };
              });
            })
            .then(function (o) {
              if (!o.res.ok) {
                window.alert(typeof o.data.detail === 'string' ? o.data.detail : 'Could not save card order.');
                switchLeadGroupTab(currentLeadGroupTabId, { force: true, skipHistory: true });
              }
            })
            .catch(function () {
              window.alert('Could not save card order.');
              switchLeadGroupTab(currentLeadGroupTabId, { force: true, skipHistory: true });
            });
        });
      })();
      window.leadGroupTabBusy = false;
      document.getElementById('lead-group-tabs')?.addEventListener('click', function (e) {
        var tab = e.target.closest('.lead-group-tab[data-group-id]');
        if (!tab || tab.id === 'lead-group-new-btn') return;
        e.preventDefault();
        e.stopPropagation();
        var gid = normalizeLeadGroupTabId(tab.getAttribute('data-group-id') || 'uncategorized');
        if (gid === normalizeLeadGroupTabId(currentLeadGroupTabId)) return;
        switchLeadGroupTab(gid, { historyMode: 'push' });
      });
      replaceDashboardUrlForCurrentTab('replace');
      document.getElementById('lead-group-new-btn')?.addEventListener('click', async function (e) {
        e.preventDefault();
        var name = window.prompt('Name for the new group');
        if (name == null) return;
        name = String(name).trim().slice(0, 100);
        if (!name) return;
        try {
          var res = await fetch(dashboardJsConfig.createLeadGroupUrl, {
            method: 'POST',
            headers: {
              'Content-Type': 'application/json',
              'X-CSRFToken': getCsrfToken(),
            },
            credentials: 'same-origin',
            body: JSON.stringify({ name: name }),
          });
          var data = await res.json().catch(function () { return {}; });
          if (!res.ok || !data.ok) {
            window.alert(typeof data.detail === 'string' ? data.detail : 'Could not create group.');
            return;
          }
          var wrap = document.getElementById('lead-group-tabs');
          var newBtn = document.getElementById('lead-group-new-btn');
          if (wrap && newBtn) {
            var b = document.createElement('button');
            b.type = 'button';
            b.setAttribute('role', 'tab');
            b.className = 'lead-group-tab lead-group-tab--draggable rounded-t-md';
            b.setAttribute('draggable', 'true');
            b.setAttribute('data-group-id', String(data.id));
            b.setAttribute('aria-selected', 'false');
            var label = document.createElement('span');
            label.className = 'relative inline-flex';
            label.textContent = data.name;
            var cnt = document.createElement('span');
            cnt.className = 'lead-group-count absolute -right-3.5 -top-2.5 inline-flex min-w-[1.25rem] items-center justify-center rounded-full bg-slate-200 px-1.5 py-0.5 text-[11px] font-bold leading-none text-slate-600 ring-1 ring-white';
            cnt.title = '0 lead(s) in this group';
            cnt.textContent = '0';
            label.appendChild(cnt);
            b.appendChild(label);
            wrap.insertBefore(b, newBtn);
          }
          var moveMenuWrap = document.getElementById('lead-group-move-menu-groups');
          if (moveMenuWrap) {
            var mb = document.createElement('button');
            mb.type = 'button';
            mb.setAttribute('role', 'menuitem');
            mb.className =
              'lead-group-move-pick flex w-full items-center gap-2.5 px-3 py-2.5 text-left text-sm font-medium text-slate-800 transition hover:bg-violet-50/90 focus:bg-violet-50/90 focus:outline-none disabled:cursor-wait disabled:opacity-60';
            mb.setAttribute('data-group-id', String(data.id));
            mb.innerHTML =
              '<svg class="h-5 w-5 shrink-0 text-amber-500" fill="none" stroke="currentColor" stroke-width="1.75" viewBox="0 0 24 24" aria-hidden="true"><path stroke-linecap="round" stroke-linejoin="round" d="M2.25 12.75V12A2.25 2.25 0 014.5 9.75h15A2.25 2.25 0 0121.75 12v.75m-8.69-6.44l-2.12-2.12a1.5 1.5 0 00-1.061-.44H4.5A2.25 2.25 0 002.25 6v12a2.25 2.25 0 002.25 2.25h15A2.25 2.25 0 0021.75 18V9a2.25 2.25 0 00-2.25-2.25h-5.379a1.5 1.5 0 01-1.06-.44z"/></svg><span class="min-w-0 flex-1 truncate"></span>';
            mb.querySelector('span').textContent = data.name;
            moveMenuWrap.appendChild(mb);
          }
          refreshBulkAssignGroupButtonState();
          switchLeadGroupTab(String(data.id));
        } catch (err) {
          console.error(err);
          window.alert('Network error creating group.');
        }
      });
      window.pendingMoveLeadIds = [];
      window.leadGroupMoveMenuOpen = false;
      window.leadGroupMoveMenuAnchor = null;
      document.getElementById('bulk-assign-group-open')?.addEventListener('click', function (e) {
        e.preventDefault();
        e.stopPropagation();
        var ids = getUniqueSelectedLeadIds();
        if (ids.length < 1) return;
        toggleLeadGroupMoveMenu(this, ids);
      });
      document.addEventListener(
        'click',
        function (e) {
          if (!leadGroupMoveMenuOpen) return;
          var t = e.target;
          if (t.closest && t.closest('#lead-group-move-menu')) return;
          if (t.closest && t.closest('#bulk-assign-group-open')) return;
          if (t.closest && t.closest('.move-to-group-btn')) return;
          closeLeadGroupMoveMenu();
        },
        true
      );
      document.addEventListener('keydown', function (e) {
        if (e.key === 'Escape' && leadGroupMoveMenuOpen) closeLeadGroupMoveMenu();
      });
      window.addEventListener('resize', function () {
        if (leadGroupMoveMenuOpen && leadGroupMoveMenuAnchor) positionLeadGroupMoveMenu(leadGroupMoveMenuAnchor);
      });
      document.getElementById('lead-group-move-menu')?.addEventListener('click', async function (e) {
        var pick = e.target.closest('.lead-group-move-pick');
        if (!pick || !this.contains(pick)) return;
        e.preventDefault();
        e.stopPropagation();
        var raw = pick.getAttribute('data-group-id');
        var groupId = raw === '' || raw === null ? null : parseInt(raw, 10);
        if (groupId !== null && isNaN(groupId)) return;
        var ids = pendingMoveLeadIds.map(function (v) { return parseInt(v, 10); }).filter(function (n) { return !isNaN(n); });
        if (!ids.length) {
          closeLeadGroupMoveMenu();
          return;
        }
        var menu = document.getElementById('lead-group-move-menu');
        var picks = menu ? menu.querySelectorAll('.lead-group-move-pick') : [];
        picks.forEach(function (b) {
          b.disabled = true;
        });
        clearLeadGroupMoveMenuErr();
        try {
          var res = await fetch(dashboardJsConfig.bulkAssignGroupUrl, {
            method: 'POST',
            headers: {
              'Content-Type': 'application/json',
              'X-CSRFToken': getCsrfToken(),
            },
            credentials: 'same-origin',
            body: JSON.stringify({ ids: ids, group_id: groupId }),
          });
          var data = await res.json().catch(function () { return {}; });
          if (!res.ok) {
            var errEl = document.getElementById('lead-group-move-menu-error');
            if (errEl) {
              errEl.textContent =
                typeof data.detail === 'string' ? data.detail : JSON.stringify(data.detail || res.statusText);
              errEl.classList.remove('hidden');
              positionLeadGroupMoveMenu(leadGroupMoveMenuAnchor);
            }
            return;
          }
          closeLeadGroupMoveMenu();
          await switchLeadGroupTab(currentLeadGroupTabId, { force: true, skipHistory: true });
        } catch (err) {
          var errEl2 = document.getElementById('lead-group-move-menu-error');
          if (errEl2) {
            errEl2.textContent = 'Network error: ' + err;
            errEl2.classList.remove('hidden');
            positionLeadGroupMoveMenu(leadGroupMoveMenuAnchor);
          }
        } finally {
          picks.forEach(function (b) {
            b.disabled = false;
          });
        }
      });
      window.editDialog = document.getElementById('clinic-edit-dialog');
      window.editForm = document.getElementById('clinic-edit-form');
      window.editErr = document.getElementById('clinic-edit-error');
      window.editSaveBtn = document.getElementById('clinic-edit-save');
      window.editSaveLabel = document.getElementById('clinic-edit-save-label');
      window.editSaveSpin = document.getElementById('clinic-edit-save-spinner');
      /** Name + address only for “click address to copy” (DOM + data-* fallbacks). */
      document.getElementById('clinics-panel')?.addEventListener('click', function (e) {
        var dequeueBtn = e.target.closest('.lead-dequeue-btn');
        if (dequeueBtn && this.contains(dequeueBtn)) {
          e.preventDefault();
          e.stopPropagation();
          handleLeadDequeueClick(dequeueBtn);
          return;
        }
        var moveGrpBtn = e.target.closest('.move-to-group-btn');
        if (moveGrpBtn && this.contains(moveGrpBtn)) {
          e.preventDefault();
          e.stopPropagation();
          var rawM = moveGrpBtn.getAttribute('data-clinic-id');
          if (rawM) toggleLeadGroupMoveMenu(moveGrpBtn, [rawM]);
          return;
        }
        var conversationLogBtn = e.target.closest('.lead-conversation-log-btn');
        if (conversationLogBtn && this.contains(conversationLogBtn)) {
          e.preventDefault();
          e.stopPropagation();
          var rawLog = conversationLogBtn.getAttribute('data-clinic-id');
          var idLog = rawLog ? parseInt(rawLog, 10) : NaN;
          if (!isNaN(idLog)) openLeadConversationLogDialog(idLog);
          return;
        }
        var vipStarBtn = e.target.closest('.lead-vip-star-btn');
        if (vipStarBtn && this.contains(vipStarBtn)) {
          e.preventDefault();
          e.stopPropagation();
          var rawV = vipStarBtn.getAttribute('data-clinic-id');
          var idV = rawV ? parseInt(rawV, 10) : NaN;
          if (isNaN(idV)) return;
          var nextVip = vipStarBtn.getAttribute('data-vip') !== 'true';
          var starNodes = document.querySelectorAll('.clinic-row[data-clinic-id="' + idV + '"] .lead-vip-star-btn');
          starNodes.forEach(function (b) { b.disabled = true; });
          var urlV = leadVipUrlTemplate.replace('__ID__', String(idV));
          fetch(urlV, {
            method: 'PATCH',
            headers: {
              'Content-Type': 'application/json',
              'X-CSRFToken': getCsrfToken(),
            },
            body: JSON.stringify({ is_very_important: nextVip }),
            credentials: 'same-origin',
          })
            .then(function (res) {
              return res.json().then(function (data) {
                if (!res.ok) throw new Error((data && data.detail) ? data.detail : 'Request failed');
                return data;
              });
            })
            .then(function (data) {
              document.querySelectorAll('.clinic-row[data-clinic-id="' + idV + '"]').forEach(function (row) {
                row.querySelectorAll('.lead-vip-star-btn').forEach(function (b) {
                  setLeadVipStarVisual(b, !!data.is_very_important);
                  b.disabled = false;
                });
                syncRowDataSearch(row, undefined, undefined, data.is_very_important);
              });
              applyTableFilter({ resetPage: false });
            })
            .catch(function () {
              starNodes.forEach(function (b) { b.disabled = false; });
            });
          return;
        }
        var copyDetailsBtn = e.target.closest('.lead-card-copy-details-btn');
        if (copyDetailsBtn && this.contains(copyDetailsBtn)) {
          e.preventDefault();
          e.stopPropagation();
          var dn = (copyDetailsBtn.getAttribute('data-copy-name') || '').trim();
          var da = (copyDetailsBtn.getAttribute('data-copy-address') || '').trim();
          var dp = (copyDetailsBtn.getAttribute('data-copy-phone') || '').trim();
          var dw = (copyDetailsBtn.getAttribute('data-copy-website') || '').trim();
          var detailLines = [];
          if (dn) detailLines.push('*' + dn + '*');
          if (da) detailLines.push(da);
          if (dp) detailLines.push(dp);
          if (dw) detailLines.push(dw);
          var clipText = detailLines.join('\n');
          if (!clipText) return;
          function copyDetailsDone() {
            var prevTitle = copyDetailsBtn.getAttribute('title') || '';
            copyDetailsBtn.setAttribute('title', 'Copied!');
            copyDetailsBtn.classList.add('border-emerald-300', 'bg-emerald-50/90', 'text-emerald-800');
            setTimeout(function () {
              copyDetailsBtn.setAttribute('title', prevTitle || 'Copy name, address, phone & website');
              copyDetailsBtn.classList.remove('border-emerald-300', 'bg-emerald-50/90', 'text-emerald-800');
            }, 1600);
          }
          if (navigator.clipboard && navigator.clipboard.writeText) {
            navigator.clipboard.writeText(clipText).then(copyDetailsDone).catch(function () {
              window.prompt('Copy:', clipText);
              copyDetailsDone();
            });
          } else {
            window.prompt('Copy:', clipText);
            copyDetailsDone();
          }
          return;
        }
        var deleteLeadBtn = e.target.closest('.lead-card-delete-btn');
        if (deleteLeadBtn && this.contains(deleteLeadBtn)) {
          e.preventDefault();
          e.stopPropagation();
          var rawDel = deleteLeadBtn.getAttribute('data-clinic-id');
          var idDel = rawDel ? parseInt(rawDel, 10) : NaN;
          if (isNaN(idDel)) return;
          if (!window.confirm('Delete this lead permanently? This cannot be undone.')) return;
          deleteLeadBtn.disabled = true;
          var urlDel = leadDeleteUrlTemplate.replace('__ID__', String(idDel));
          fetch(urlDel, {
            method: 'DELETE',
            headers: {
              'X-CSRFToken': getCsrfToken(),
            },
            credentials: 'same-origin',
          })
            .then(function (res) {
              return res.json().then(function (data) {
                return { res: res, data: data };
              });
            })
            .then(function (o) {
              if (!o.res.ok) {
                var msg = typeof o.data.detail === 'string' ? o.data.detail : 'Could not delete.';
                window.alert(msg);
                return;
              }
              document.querySelectorAll('.clinic-row[data-clinic-id="' + idDel + '"]').forEach(function (row) {
                row.remove();
              });
              refreshSelectAllState();
              refreshSelectionVisuals();
              refreshSetCategoryButtonState();
              refreshBulkAssignGroupButtonState();
              refreshTableSearchClearVisibility();
              applyTableFilter({ resetPage: false });
            })
            .catch(function () {
              window.alert('Network error while deleting.');
            })
            .finally(function () {
              var still = document.querySelector('.lead-card-delete-btn[data-clinic-id="' + idDel + '"]');
              if (still) still.disabled = false;
            });
          return;
        }
        var addrCopyBtn = e.target.closest('.address-copy-trigger');
        if (addrCopyBtn && this.contains(addrCopyBtn)) {
          e.preventDefault();
          e.stopPropagation();
          if (addrCopyBtn.disabled) return;
          var sp = leadRowSnippetFromAddressTrigger(addrCopyBtn);
          var addrLines = [];
          if (sp.name) addrLines.push('*' + sp.name + '*');
          if (sp.address) addrLines.push(sp.address);
          var addrText = addrLines.join('\n');
          if (!addrText) return;
          function addrCopiedOk() {
            var prev = addrCopyBtn.querySelector('.address-copy-done');
            if (prev) prev.remove();
            var prevTitle = addrCopyBtn.getAttribute('title') || '';
            addrCopyBtn.setAttribute('title', 'Copied!');
            addrCopyBtn.style.backgroundColor = 'rgb(236 253 245)';
            addrCopyBtn.style.boxShadow = 'inset 0 0 0 2px rgba(52, 211, 153, 0.55)';
            var tag = document.createElement('span');
            tag.className = 'address-copy-done';
            tag.textContent = 'Copied!';
            tag.setAttribute('aria-hidden', 'true');
            tag.style.cssText = 'position:absolute;top:2px;right:2px;z-index:2;font-size:10px;font-weight:700;line-height:1.2;color:#065f46;background:#a7f3d0;padding:2px 6px;border-radius:4px;pointer-events:none;box-shadow:0 1px 2px rgba(0,0,0,.08)';
            addrCopyBtn.appendChild(tag);
            setTimeout(function () {
              addrCopyBtn.setAttribute('title', prevTitle);
              addrCopyBtn.style.backgroundColor = '';
              addrCopyBtn.style.boxShadow = '';
              var t = addrCopyBtn.querySelector('.address-copy-done');
              if (t) t.remove();
            }, 1600);
          }
          if (navigator.clipboard && navigator.clipboard.writeText) {
            navigator.clipboard.writeText(addrText).then(addrCopiedOk).catch(function () {
              window.prompt('Copy:', addrText);
              addrCopiedOk();
            });
          } else {
            window.prompt('Copy:', addrText);
            addrCopiedOk();
          }
          return;
        }
        var waBtn = e.target.closest('.whatsapp-copy-btn');
        if (waBtn && this.contains(waBtn)) {
          e.preventDefault();
          e.stopPropagation();
          if (waBtn.disabled) return;
          var rowWa = waBtn.closest('.clinic-row');
          var storeWa = rowWa && rowWa.querySelector('.whatsapp-draft-store');
          var text = storeWa ? storeWa.textContent : '';
          if (!String(text).trim()) return;
          function copiedOk() {
            var label = waBtn.querySelector('span');
            if (!label) return;
            var prev = label.textContent;
            label.textContent = 'Copied!';
            setTimeout(function () { label.textContent = prev; }, 1600);
          }
          if (navigator.clipboard && navigator.clipboard.writeText) {
            navigator.clipboard.writeText(text).then(copiedOk).catch(function () {
              window.prompt('Copy message:', text);
            });
          } else {
            window.prompt('Copy message:', text);
          }
          return;
        }
        const btn = e.target.closest('.clinic-edit-btn');
        if (!btn || !this.contains(btn)) return;
        e.preventDefault();
        e.stopPropagation();
        const raw = btn.getAttribute('data-clinic-id');
        const id = raw ? parseInt(raw, 10) : NaN;
        if (!isNaN(id)) openClinicEditModal(id);
      });
      document.getElementById('clinic-edit-close-x')?.addEventListener('click', closeClinicEditDialog);
      document.getElementById('clinic-edit-cancel')?.addEventListener('click', closeClinicEditDialog);
      editDialog?.addEventListener('click', function (e) {
        if (e.target === editDialog) closeClinicEditDialog();
      });
      editForm?.addEventListener('submit', async function (e) {
        e.preventDefault();
        clearEditError();
        const idEl = document.getElementById('clinic-edit-id');
        const id = idEl ? String(idEl.value || '').trim() : '';
        if (!id) {
          showEditError('Lead is still loading — wait a moment, then try again. If this persists, close and reopen Edit.');
          return;
        }
        const nameVal = document.getElementById('clinic-edit-name')
          ? document.getElementById('clinic-edit-name').value.trim()
          : '';
        if (!nameVal) {
          showEditError('Business name is required.');
          return;
        }
        const url = clinicUpdateUrlTemplate.replace('__ID__', id);
        const body = {
          name: nameVal,
          phone_numbers: collectManualPhonePayload(document.getElementById('clinic-edit-phones-list')),
          address: document.getElementById('clinic-edit-address').value.trim(),
          website: document.getElementById('clinic-edit-website').value.trim(),
          search_state: document.getElementById('clinic-edit-search-state').value.trim(),
          search_city: document.getElementById('clinic-edit-search-city').value.trim(),
          search_query: document.getElementById('clinic-edit-search-query').value.trim(),
          category: document.getElementById('clinic-edit-type').value,
          is_chain: document.getElementById('clinic-edit-chain').checked,
          whatsapp_draft: document.getElementById('clinic-edit-whatsapp')
            ? document.getElementById('clinic-edit-whatsapp').value.trim()
            : '',
        };
        if (editSaveBtn) editSaveBtn.disabled = true;
        if (editSaveSpin) editSaveSpin.classList.remove('hidden');
        if (editSaveLabel) editSaveLabel.textContent = 'Saving…';
        try {
          const res = await fetch(url, {
            method: 'PATCH',
            headers: {
              'Content-Type': 'application/json',
              'X-CSRFToken': getCsrfToken(),
            },
            credentials: 'same-origin',
            body: JSON.stringify(body),
          });
          const data = await res.json().catch(function () { return {}; });
          if (!res.ok) {
            showEditError(typeof data.detail === 'string' ? data.detail : JSON.stringify(data.detail || res.statusText));
            return;
          }
          applyClinicEditToDom(data);
          showClinicSaveSuccess(data.name);
          closeClinicEditDialog();
        } catch (err) {
          showEditError('Network error: ' + err);
        } finally {
          if (editSaveBtn) editSaveBtn.disabled = false;
          if (editSaveSpin) editSaveSpin.classList.add('hidden');
          if (editSaveLabel) editSaveLabel.textContent = 'Save changes';
        }
      });
      window.leadCreateDialog = document.getElementById('lead-create-dialog');
      window.leadCreateForm = document.getElementById('lead-create-form');
      window.leadCreateErr = document.getElementById('lead-create-error');
      window.leadCreateSubmit = document.getElementById('lead-create-submit');
      window.leadCreateSubmitLabel = document.getElementById('lead-create-submit-label');
      window.leadCreateSubmitSpinner = document.getElementById('lead-create-submit-spinner');
      document.getElementById('lead-manual-create-open')?.addEventListener('click', function () {
        clearLeadCreateError();
        resetLeadCreateForm();
        leadCreateDialog?.showModal();
        window.setTimeout(function () {
          document.getElementById('lead-create-name')?.focus();
        }, 0);
      });
      document.getElementById('lead-create-close-x')?.addEventListener('click', closeLeadCreateDialog);
      document.getElementById('lead-create-cancel')?.addEventListener('click', closeLeadCreateDialog);
      leadCreateDialog?.addEventListener('click', function (e) {
        if (e.target === leadCreateDialog) closeLeadCreateDialog();
      });
      leadCreateForm?.addEventListener('submit', async function (e) {
        e.preventDefault();
        clearLeadCreateError();
        var gid = normalizeLeadGroupTabId(currentLeadGroupTabId);
        var payload = {
          name: document.getElementById('lead-create-name').value.trim(),
          phone_numbers: collectManualPhonePayload(document.getElementById('lead-create-phones-list')),
          address: document.getElementById('lead-create-address').value.trim(),
          website: document.getElementById('lead-create-website').value.trim(),
          category: document.getElementById('lead-create-type').value,
          group_id: gid === 'uncategorized' ? 'uncategorized' : gid,
        };
        if (!payload.name) {
          showLeadCreateError('Name is required.');
          return;
        }
        if (leadCreateSubmit) leadCreateSubmit.disabled = true;
        if (leadCreateSubmitSpinner) leadCreateSubmitSpinner.classList.remove('hidden');
        if (leadCreateSubmitLabel) leadCreateSubmitLabel.textContent = 'Creating…';
        try {
          var res = await fetch(dashboardJsConfig.leadManualCreateUrl, {
            method: 'POST',
            headers: {
              'Content-Type': 'application/json',
              'X-CSRFToken': getCsrfToken(),
            },
            credentials: 'same-origin',
            body: JSON.stringify(payload),
          });
          var data = await res.json().catch(function () { return {}; });
          if (!res.ok) {
            showLeadCreateError(typeof data.detail === 'string' ? data.detail : JSON.stringify(data.detail || res.statusText));
            return;
          }
          closeLeadCreateDialog();
          await switchLeadGroupTab(currentLeadGroupTabId, { force: true, skipHistory: true });
        } catch (err) {
          showLeadCreateError('Network error: ' + err);
        } finally {
          if (leadCreateSubmit) leadCreateSubmit.disabled = false;
          if (leadCreateSubmitSpinner) leadCreateSubmitSpinner.classList.add('hidden');
          if (leadCreateSubmitLabel) leadCreateSubmitLabel.textContent = 'Create lead';
        }
      });
      window.leadConversationLogDialog = document.getElementById('lead-conversation-log-dialog');
      window.leadConversationLogForm = document.getElementById('lead-conversation-log-form');
      window.leadConversationLogErr = document.getElementById('lead-conversation-log-error');
      window.leadConversationLogOk = document.getElementById('lead-conversation-log-ok');
      window.leadConversationLogSubmitBtn = document.getElementById('lead-conversation-log-submit');
      window.leadConversationLogSubmitLabel = document.getElementById('lead-conversation-log-submit-label');
      window.leadConversationLogSubmitSpinner = document.getElementById('lead-conversation-log-submit-spinner');
      window.leadConversationHistoryList = document.getElementById('lead-conversation-history-list');
      window.leadConversationHistoryEmpty = document.getElementById('lead-conversation-history-empty');
      document.getElementById('lead-conversation-log-close-x')?.addEventListener('click', closeLeadConversationLogDialog);
      document.getElementById('lead-conversation-log-cancel')?.addEventListener('click', closeLeadConversationLogDialog);
      leadConversationLogDialog?.addEventListener('click', function (e) {
        if (e.target === leadConversationLogDialog) closeLeadConversationLogDialog();
      });
      leadConversationLogForm?.addEventListener('submit', async function (e) {
        e.preventDefault();
        clearLeadConversationLogMessages();
        var idEl = document.getElementById('lead-conversation-log-id');
        var dateEl = document.getElementById('lead-conversation-date');
        var remarksEl = document.getElementById('lead-conversation-remarks');
        var leadId = idEl ? String(idEl.value || '').trim() : '';
        var dateVal = dateEl ? String(dateEl.value || '').trim() : '';
        var remarksVal = remarksEl ? String(remarksEl.value || '').trim() : '';
        if (!leadId) {
          showLeadConversationLogError('Lead id is missing. Reopen the modal and try again.');
          return;
        }
        if (!dateVal) {
          showLeadConversationLogError('Date is required.');
          return;
        }
        if (!remarksVal) {
          showLeadConversationLogError('Remarks are required.');
          return;
        }
        var url = leadConversationLogUrlTemplate.replace('__ID__', leadId);
        if (leadConversationLogSubmitBtn) leadConversationLogSubmitBtn.disabled = true;
        if (leadConversationLogSubmitSpinner) leadConversationLogSubmitSpinner.classList.remove('hidden');
        if (leadConversationLogSubmitLabel) leadConversationLogSubmitLabel.textContent = 'Saving...';
        try {
          var res = await fetch(url, {
            method: 'POST',
            headers: {
              'Content-Type': 'application/json',
              'X-CSRFToken': getCsrfToken(),
            },
            credentials: 'same-origin',
            body: JSON.stringify({
              conversation_date: dateVal,
              remarks: remarksVal,
            }),
          });
          var data = await res.json().catch(function () { return {}; });
          if (!res.ok) {
            showLeadConversationLogError(typeof data.detail === 'string' ? data.detail : 'Could not save conversation log.');
            return;
          }
          if (leadConversationLogOk) {
            leadConversationLogOk.textContent = 'Conversation log saved.';
            leadConversationLogOk.classList.remove('hidden');
          }
          await loadLeadConversationHistory(leadId);
          if (remarksEl) remarksEl.value = '';
          showClinicSaveSuccess('Conversation log');
        } catch (err) {
          showLeadConversationLogError('Network error while saving conversation log.');
        } finally {
          if (leadConversationLogSubmitBtn) leadConversationLogSubmitBtn.disabled = false;
          if (leadConversationLogSubmitSpinner) leadConversationLogSubmitSpinner.classList.add('hidden');
          if (leadConversationLogSubmitLabel) leadConversationLogSubmitLabel.textContent = 'Save log';
        }
      });
      leadConversationHistoryList?.addEventListener('click', async function (e) {
        var btn = e.target.closest('.lead-conversation-log-delete-btn');
        if (!btn || !this.contains(btn)) return;
        var idEl = document.getElementById('lead-conversation-log-id');
        var leadId = idEl ? String(idEl.value || '').trim() : '';
        var rawLogId = btn.getAttribute('data-log-id') || '';
        var logId = rawLogId ? parseInt(rawLogId, 10) : NaN;
        if (!leadId || isNaN(logId)) return;
        if (!window.confirm('Delete this conversation log?')) return;
        btn.disabled = true;
        await deleteLeadConversationLog(leadId, logId);
      });
      window.bulkManualDialog = document.getElementById('bulk-manual-dialog');
      window.bulkManualForm = document.getElementById('bulk-manual-form');
      window.bulkManualErr = document.getElementById('bulk-manual-error');
      window.bulkManualCount = document.getElementById('bulk-manual-count');
      window.bulkManualSubmit = document.getElementById('bulk-manual-submit');
      window.bulkManualSubmitLabel = document.getElementById('bulk-manual-submit-label');
      window.bulkManualSpinner = document.getElementById('bulk-manual-spinner');
      document.getElementById('bulk-manual-open')?.addEventListener('click', function () {
        const ids = getUniqueSelectedLeadIds();
        if (ids.length < 1) return;
        clearBulkManualErr();
        if (bulkManualCount) {
          bulkManualCount.classList.remove('text-amber-800', 'font-medium');
          const n = ids.length;
          bulkManualCount.textContent =
            n === 1 ? '1 lead selected.' : n + ' leads selected.';
        }
        bulkManualDialog?.showModal();
      });
      document.getElementById('bulk-manual-close-x')?.addEventListener('click', closeBulkManualDialog);
      document.getElementById('bulk-manual-cancel')?.addEventListener('click', closeBulkManualDialog);
      bulkManualDialog?.addEventListener('click', function (e) {
        if (e.target === bulkManualDialog) closeBulkManualDialog();
      });
      bulkManualForm?.addEventListener('submit', async function (e) {
        e.preventDefault();
        clearBulkManualErr();
        const ids = getUniqueSelectedLeadIds().map(function (v) {
          return parseInt(v, 10);
        }).filter(function (n) { return !isNaN(n); });
        if (!ids.length) {
          if (bulkManualErr) {
            bulkManualErr.textContent = 'No rows selected.';
            bulkManualErr.classList.remove('hidden');
          }
          return;
        }
        const category = document.getElementById('bulk-manual-category').value;
        if (bulkManualSubmit) bulkManualSubmit.disabled = true;
        if (bulkManualSpinner) bulkManualSpinner.classList.remove('hidden');
        if (bulkManualSubmitLabel) bulkManualSubmitLabel.textContent = 'Applying…';
        try {
          const res = await fetch(dashboardJsConfig.bulkManualUrl, {
            method: 'POST',
            headers: {
              'Content-Type': 'application/json',
              'X-CSRFToken': getCsrfToken(),
            },
            credentials: 'same-origin',
            body: JSON.stringify({ ids: ids, category: category }),
          });
          const data = await res.json().catch(function () { return {}; });
          if (!res.ok) {
            if (bulkManualErr) {
              bulkManualErr.textContent = typeof data.detail === 'string' ? data.detail : JSON.stringify(data.detail || res.statusText);
              bulkManualErr.classList.remove('hidden');
            }
            return;
          }
          closeBulkManualDialog();
          window.location.reload();
        } catch (err) {
          if (bulkManualErr) {
            bulkManualErr.textContent = 'Network error: ' + err;
            bulkManualErr.classList.remove('hidden');
          }
        } finally {
          if (bulkManualSubmit) bulkManualSubmit.disabled = false;
          if (bulkManualSpinner) bulkManualSpinner.classList.add('hidden');
          if (bulkManualSubmitLabel) bulkManualSubmitLabel.textContent = 'Apply to selected';
        }
      });
      window.__dashboardOnWorkspaceShown = function () {
        initClinicViewModeFromStorage();
        syncLeadSortSelect();
        applyLeadSort();
        if (typeof window.__ensureGridHtmxBound === 'function') window.__ensureGridHtmxBound();
        if (typeof window.__syncLeadChatIndicatorPolling === 'function') {
          window.__syncLeadChatIndicatorPolling();
        }
        if (typeof window.mountLeadGroupDrawer === 'function') window.mountLeadGroupDrawer();
        if (typeof window.__bindLeadsPullToRefresh === 'function') window.__bindLeadsPullToRefresh();
      };
      window.__dashboardOnWorkspaceShown();
      window.huntForm = document.getElementById('hunt-form');
      window.huntStatus = document.getElementById('hunt-status');
      window.huntBtn = document.getElementById('hunt-btn');
      window.huntBtnLabel = document.getElementById('hunt-btn-label');
      window.huntSpinner = document.getElementById('hunt-spinner');
      if (huntForm) {
        huntForm.addEventListener('submit', function (e) {
          e.preventDefault();
          runHunt();
        });
      }
      window.STATE_CITY_SUGGESTIONS = {
        'Johor': ['Johor Bahru', 'Iskandar Puteri', 'Batu Pahat', 'Muar', 'Kluang', 'Skudai', 'Pasir Gudang', 'Segamat'],
        'Kedah': ['Alor Setar', 'Sungai Petani', 'Kulim', 'Jitra', 'Langkawi', 'Gurun'],
        'Kelantan': ['Kota Bharu', 'Pasir Mas', 'Tanah Merah', 'Tumpat', 'Gua Musang'],
        'Kuala Lumpur': ['Bukit Bintang', 'Cheras', 'Kepong', 'Setapak', 'Bangsar', 'Mont Kiara', 'Sentul', 'Wangsa Maju'],
        'Labuan': ['Victoria', 'Labuan Town'],
        'Melaka': ['Melaka City', 'Ayer Keroh', 'Alor Gajah', 'Jasin', 'Batu Berendam'],
        'Negeri Sembilan': ['Seremban', 'Port Dickson', 'Nilai', 'Bahau', 'Tampin'],
        'Pahang': ['Kuantan', 'Temerloh', 'Bentong', 'Raub', 'Cameron Highlands', 'Pekan'],
        'Penang': ['George Town', 'Bayan Lepas', 'Butterworth', 'Bukit Mertajam', 'Seberang Jaya', 'Tanjung Tokong'],
        'Perak': ['Ipoh', 'Taiping', 'Teluk Intan', 'Sitiawan', 'Kampar', 'Batu Gajah', 'Lumut'],
        'Perlis': ['Kangar', 'Arau', 'Padang Besar'],
        'Putrajaya': ['Putrajaya'],
        'Sabah': ['Kota Kinabalu', 'Sandakan', 'Tawau', 'Lahad Datu', 'Keningau', 'Penampang'],
        'Sarawak': ['Kuching', 'Miri', 'Sibu', 'Bintulu', 'Samarahan', 'Sri Aman'],
        'Selangor': ['Shah Alam', 'Petaling Jaya', 'Subang Jaya', 'Klang', 'Kajang', 'Puchong', 'Ampang', 'Cyberjaya', 'Rawang', 'Cheras'],
        'Terengganu': ['Kuala Terengganu', 'Kemaman', 'Dungun', 'Chukai', 'Marang'],
      };
      window.citySuggestBtn = document.getElementById('hunt-city-suggest');
      window.cityInput = document.getElementById('city');
      window.stateSelect = document.getElementById('hunt-state');
      window.citySuggestIndex = 0;
      window.citySuggestState = stateSelect ? stateSelect.value : '';
      if (citySuggestBtn && cityInput && stateSelect) {
        stateSelect.addEventListener('change', function () {
          citySuggestIndex = 0;
          citySuggestState = stateSelect.value;
        });
        citySuggestBtn.addEventListener('click', function () {
          const state = stateSelect.value;
          const options = STATE_CITY_SUGGESTIONS[state] || [];
          if (!options.length) return;
          if (state !== citySuggestState) {
            citySuggestState = state;
            citySuggestIndex = 0;
          }
          cityInput.value = options[citySuggestIndex % options.length];
          citySuggestIndex += 1;
          cityInput.dispatchEvent(new Event('input', { bubbles: true }));
          cityInput.focus();
        });
      }
      window.applyTableFilter = applyTableFilter;
      window.refreshSelectAllState = refreshSelectAllState;
      window.refreshSelectionVisuals = refreshSelectionVisuals;
      (function initFolderTotalPipelineCount() {
        var totalEl = document.getElementById('funnel-metric-total');
        if (totalEl) {
          var parsed = parseInt(String(totalEl.textContent || '').trim(), 10);
          if (!isNaN(parsed)) folderTotalPipelineCount = parsed;
        }
        refreshFilteredLeadCount();
      })();
})();
