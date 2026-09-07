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
      document.querySelectorAll('.hunt-provider-btn').forEach(function (btn) {
        btn.addEventListener('click', function () {
          setHuntProvider(btn.getAttribute('data-provider'), true);
        });
      });
      (function initHuntProvider() {
        var stored = '';
        try { stored = localStorage.getItem(HUNT_PROVIDER_KEY) || ''; } catch (e) { stored = ''; }
        var flags = (dashboardJsConfig && dashboardJsConfig.huntProviders) || {};
        var initial = stored;
        if (initial !== 'serper' && initial !== 'outscraper') {
          initial = flags.outscraper && !flags.serper ? 'outscraper' : 'serper';
        }
        setHuntProvider(initial, true);
      })();
      window.requireWebsiteToggle = document.getElementById('hunt-require-website');
      bindHuntOptionToggle(requireWebsiteToggle, REQUIRE_WEBSITE_KEY);
      window.clinicSaveStatusTimer = null;
      window.selectAll = document.getElementById('select-all-clinics');
      window.currentLeadPage = 1;
      window.folderTotalPipelineCount = 0;
      window.leadChatIndicatorPollTimer = null;
      window.leadChatIndicatorSnapshot = '';
      document.getElementById('bulk-move-ready-btn')?.addEventListener('click', function () {
        bulkMoveSelectedToReady();
      });
      document.getElementById('bulk-mark-sent-btn')?.addEventListener('click', function () {
        bulkMarkSelectedSent();
      });
      document.getElementById('bulk-wa-queue-btn')?.addEventListener('click', function () {
        bulkPushSelectedToWhatsappQueue();
      });
      document.getElementById('bulk-dequeue-btn')?.addEventListener('click', function () {
        bulkDequeueSelectedFromQueue();
      });
      // --- Choose batch (assign selected Ready / Queue leads to a WhatsApp batch) ---
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
      chooseBatchDialog?.addEventListener('close', function () {
        window.chooseBatchTargetIds = null;
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
      try {
        refreshBulkActionDock();
      } catch (err) {
        console.error(err);
      }
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
      // ----- Import from Excel (Export to Excel format) -----
      window.importXlsxBtn = document.getElementById('import-xlsx-btn');
      window.importXlsxInput = document.getElementById('import-xlsx-input');
      window.importXlsxIcon = document.getElementById('import-xlsx-icon');
      window.importXlsxSpinner = document.getElementById('import-xlsx-spinner');
      if (importXlsxBtn && importXlsxInput) {
        importXlsxBtn.addEventListener('click', function () {
          exportXlsxShowErr('');
          importXlsxInput.click();
        });
        importXlsxInput.addEventListener('change', function () {
          var file = importXlsxInput.files && importXlsxInput.files[0];
          if (!file) return;
          window.appConfirm({
            title: 'Import from Excel?',
            message: 'Import leads from "' + file.name + '"?\n\nThis accepts files from Export to Excel. Existing leads (same name & address) are skipped. New rows are added to the current view.',
            confirmLabel: 'Import',
          }).then(function (ok) {
            if (!ok) {
              importXlsxInput.value = '';
              return;
            }
            var fd = new FormData();
            fd.append('xlsx', file);
            var gid = typeof currentLeadGroupTabId !== 'undefined' && currentLeadGroupTabId != null
              ? String(currentLeadGroupTabId)
              : 'uncategorized';
            fd.append('group_id', gid);
            importXlsxSetBusy(true);
            fetch(dashboardJsConfig.importXlsxUrl || '/leads/import/xlsx/', {
              method: 'POST',
              credentials: 'same-origin',
              headers: { 'X-CSRFToken': getCsrfToken() },
              body: fd,
            })
              .then(function (res) {
                return res.json().then(function (data) {
                  return { ok: res.ok, data: data };
                }).catch(function () {
                  return { ok: res.ok, data: {} };
                });
              })
              .then(function (o) {
                if (!o.ok || !o.data.ok) {
                  throw new Error((o.data && o.data.detail) || 'Import failed.');
                }
                var d = o.data;
                return window.appAlert({
                  title: 'Import complete',
                  message:
                    '• ' + (d.leads_created || 0) + ' leads added\n' +
                    '• ' + (d.leads_skipped || 0) + ' already existed',
                }).then(function () {
                  window.location.reload();
                });
              })
              .catch(function (err) {
                exportXlsxShowErr((err && err.message ? err.message : String(err)) || 'Import failed.');
              })
              .finally(function () {
                importXlsxSetBusy(false);
                importXlsxInput.value = '';
              });
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
          window.appConfirm({
            title: 'Restore from backup?',
            message: 'Restore leads from "' + file.name + '"?\n\nExisting leads (same name & address) are skipped; only missing leads and their history are added.',
            confirmLabel: 'Restore',
          }).then(function (ok) {
            if (!ok) {
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
                return window.appAlert({
                  title: 'Restore complete',
                  message:
                    '• ' + (d.leads_created || 0) + ' leads added (' + (d.leads_skipped || 0) + ' already existed)\n' +
                    '• ' + (d.groups_created || 0) + ' groups, ' + (d.scripts_created || 0) + ' script templates\n' +
                    '• ' + (d.chats_created || 0) + ' chat messages, ' + (d.logs_created || 0) + ' conversation logs\n' +
                    '• ' + (d.config_created || 0) + ' WhatsApp config',
                }).then(function () {
                  window.location.reload();
                });
              })
              .catch(function (err) {
                exportXlsxShowErr((err && err.message ? err.message : String(err)) || 'Restore failed.');
              })
              .finally(function () {
                restoreBackupSetBusy(false);
                restoreBackupInput.value = '';
              });
          });
        });
      }
      (function bindLeadsMoreMenu() {
        var openBtn = document.getElementById('leads-more-open');
        var panel = document.getElementById('leads-more-panel');
        if (!openBtn || !panel) return;
        function closeMore() {
          panel.classList.add('hidden');
          panel.setAttribute('aria-hidden', 'true');
          openBtn.setAttribute('aria-expanded', 'false');
        }
        function isMoreOpen() {
          return !panel.classList.contains('hidden');
        }
        openBtn.addEventListener('click', function (e) {
          e.preventDefault();
          e.stopPropagation();
          if (isMoreOpen()) {
            closeMore();
            return;
          }
          panel.classList.remove('hidden');
          panel.setAttribute('aria-hidden', 'false');
          openBtn.setAttribute('aria-expanded', 'true');
        });
        document.addEventListener(
          'click',
          function (e) {
            if (!isMoreOpen()) return;
            var t = e.target;
            if (t.closest && t.closest('#leads-more-menu')) return;
            closeMore();
          },
          true
        );
        document.addEventListener('keydown', function (e) {
          if (e.key === 'Escape' && isMoreOpen()) closeMore();
        });
        panel.addEventListener('click', function (e) {
          var item = e.target.closest && e.target.closest('button[role="menuitem"]');
          if (!item || item.id === 'restore-backup-btn' || item.id === 'import-xlsx-btn') return;
          closeMore();
        });
      })();
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
      function manageTagsDialogEl() {
        return document.getElementById('manage-tags-dialog');
      }
      function tagDeleteUrl(id) {
        var tmpl = dashboardJsConfig.categoryTypeDeleteUrlTemplate || '/categories/types/__ID__/delete/';
        return tmpl.replace('__ID__', String(id));
      }
      function setManageTagsError(message) {
        var err = document.getElementById('manage-tags-error');
        if (!err) return;
        var text = String(message || '').trim();
        err.textContent = text;
        err.classList.toggle('hidden', !text);
      }
      function closeManageTagsDialog() {
        var dialog = manageTagsDialogEl();
        if (dialog && dialog.open) dialog.close();
      }
      async function postTagJson(url, body) {
        var res = await fetch(url, {
          method: 'POST',
          credentials: 'same-origin',
          headers: {
            Accept: 'application/json',
            'X-Tag-Json': '1',
            'X-CSRFToken': getCsrfToken(),
            'Content-Type': 'application/x-www-form-urlencoded;charset=UTF-8',
          },
          body: body ? body.toString() : '',
        });
        var data = {};
        var raw = await res.text();
        try { data = JSON.parse(raw); } catch (err) { data = {}; }
        if (!res.ok || !data.ok) {
          throw new Error((data.detail && String(data.detail)) || raw.slice(0, 160) || ('HTTP ' + res.status));
        }
        return data;
      }
      function appendCreatedTagToUi(slug, label) {
        if (!slug) return;
        var filter = document.getElementById('lead-tag-filter');
        if (filter && !filter.querySelector('.lead-tag-filter-chip[data-tag-slug="' + slug + '"]')) {
          var empty = filter.querySelector('.lead-tag-filter-empty');
          if (empty) empty.remove();
          var chip = document.createElement('button');
          chip.type = 'button';
          chip.className = 'lead-tag-filter-chip';
          chip.setAttribute('data-tag-slug', slug);
          chip.setAttribute('aria-pressed', 'false');
          chip.title = label + ' · 0 lead(s)';
          var labelEl = document.createElement('span');
          labelEl.className = 'lead-tag-filter-label';
          labelEl.textContent = label;
          var countEl = document.createElement('span');
          countEl.className = 'lead-tag-filter-count';
          countEl.setAttribute('aria-hidden', 'true');
          countEl.textContent = '0';
          chip.appendChild(labelEl);
          chip.appendChild(countEl);
          chip.hidden = true;
          var manageBtn = document.getElementById('lead-tag-filter-manage');
          if (manageBtn) filter.insertBefore(chip, manageBtn);
          else filter.appendChild(chip);
        }
        document.querySelectorAll('.lead-tag-picker').forEach(function (picker) {
          if (picker.querySelector('.lead-tag-picker-cb[value="' + slug + '"]')) return;
          var emptyP = picker.querySelector('p');
          if (emptyP) emptyP.remove();
          var wrap = document.createElement('label');
          wrap.className = 'lead-tag-picker-chip';
          var cb = document.createElement('input');
          cb.type = 'checkbox';
          cb.className = 'lead-tag-picker-cb';
          cb.value = slug;
          var span = document.createElement('span');
          span.className = 'lead-tag-picker-chip-label';
          span.textContent = label;
          wrap.appendChild(cb);
          wrap.appendChild(span);
          picker.appendChild(wrap);
        });
        if (typeof window.syncLeadTagFilterUi === 'function') window.syncLeadTagFilterUi();
      }
      function renameTagInUi(oldSlug, newSlug, label) {
        document.querySelectorAll('.lead-tag-filter-chip[data-tag-slug="' + oldSlug + '"]').forEach(function (chip) {
          chip.setAttribute('data-tag-slug', newSlug);
          var labelEl = chip.querySelector('.lead-tag-filter-label');
          if (labelEl) labelEl.textContent = label;
          else chip.textContent = label;
          var countEl = chip.querySelector('.lead-tag-filter-count');
          var n = countEl ? String(countEl.textContent || '0').trim() : '0';
          chip.title = label + ' · ' + n + ' lead(s)';
        });
        document.querySelectorAll('.lead-tag-picker-cb[value="' + oldSlug + '"]').forEach(function (cb) {
          cb.value = newSlug;
          var span = cb.parentElement && cb.parentElement.querySelector('.lead-tag-picker-chip-label');
          if (span) span.textContent = label;
        });
        if (oldSlug !== newSlug && typeof window.getLeadTagFilterSlugs === 'function' && typeof window.saveLeadTagFilterSlugs === 'function') {
          var slugs = window.getLeadTagFilterSlugs();
          var idx = slugs.indexOf(oldSlug);
          if (idx !== -1) {
            slugs[idx] = newSlug;
            window.saveLeadTagFilterSlugs(slugs);
          }
        }
        if (typeof window.syncLeadTagFilterUi === 'function') window.syncLeadTagFilterUi();
      }
      function removeTagFromUi(slug) {
        document.querySelectorAll('.lead-tag-filter-chip[data-tag-slug="' + slug + '"]').forEach(function (chip) {
          chip.remove();
        });
        var filter = document.getElementById('lead-tag-filter');
        if (filter && !filter.querySelector('.lead-tag-filter-chip') && !filter.querySelector('.lead-tag-filter-empty')) {
          var empty = document.createElement('span');
          empty.className = 'lead-tag-filter-empty px-1 text-xs font-medium text-slate-400';
          empty.textContent = 'No tags yet';
          var manageBtn = document.getElementById('lead-tag-filter-manage');
          if (manageBtn) filter.insertBefore(empty, manageBtn);
          else filter.prepend(empty);
        }
        document.querySelectorAll('.lead-tag-picker-cb[value="' + slug + '"]').forEach(function (cb) {
          var wrap = cb.closest('.lead-tag-picker-chip');
          if (wrap) wrap.remove();
        });
        document.querySelectorAll('.lead-tag-picker').forEach(function (picker) {
          if (picker.querySelector('.lead-tag-picker-cb')) return;
          if (picker.querySelector('p')) return;
          var emptyP = document.createElement('p');
          emptyP.className = 'text-xs text-slate-400';
          emptyP.textContent = 'No tags yet';
          picker.appendChild(emptyP);
        });
        if (typeof window.getLeadTagFilterSlugs === 'function' && typeof window.saveLeadTagFilterSlugs === 'function') {
          var slugs = window.getLeadTagFilterSlugs().filter(function (item) { return item !== slug; });
          window.saveLeadTagFilterSlugs(slugs);
        }
        if (typeof window.syncLeadTagFilterUi === 'function') window.syncLeadTagFilterUi();
        if (typeof window.applyTableFilter === 'function') window.applyTableFilter({ resetPage: true });
      }
      function renderManageTagsList(tags) {
        var list = document.getElementById('manage-tags-list');
        if (!list) return;
        list.replaceChildren();
        if (!tags.length) {
          var empty = document.createElement('p');
          empty.className = 'px-1 py-6 text-center text-xs text-slate-400';
          empty.textContent = 'No tags yet';
          list.appendChild(empty);
          return;
        }
        tags.forEach(function (tag) {
          var row = document.createElement('div');
          row.className = 'manage-tags-row';
          row.setAttribute('role', 'listitem');
          row.setAttribute('data-tag-id', String(tag.id));
          row.setAttribute('data-tag-slug', tag.slug || '');
          row.setAttribute('data-sort-order', String(tag.sort_order != null ? tag.sort_order : 100));
          row.setAttribute('data-is-system', tag.is_system ? '1' : '0');
          var input = document.createElement('input');
          input.type = 'text';
          input.className = 'manage-tags-label';
          input.maxLength = 80;
          input.value = tag.label || '';
          input.setAttribute('aria-label', 'Tag name');
          var save = document.createElement('button');
          save.type = 'button';
          save.className = 'manage-tags-save';
          save.textContent = 'Save';
          row.appendChild(input);
          row.appendChild(save);
          if (tag.is_system) {
            var sys = document.createElement('span');
            sys.className = 'manage-tags-system';
            sys.textContent = 'System';
            sys.title = 'System tags cannot be deleted';
            row.appendChild(sys);
          } else {
            var del = document.createElement('button');
            del.type = 'button';
            del.className = 'manage-tags-delete';
            del.textContent = 'Delete';
            if (tag.lead_count) {
              del.title = tag.lead_count + ' lead(s) still use this tag';
            }
            row.appendChild(del);
          }
          list.appendChild(row);
        });
      }
      async function loadManageTagsList() {
        var list = document.getElementById('manage-tags-list');
        if (list) {
          list.replaceChildren();
          var loading = document.createElement('p');
          loading.className = 'px-1 py-6 text-center text-xs text-slate-400';
          loading.textContent = 'Loading…';
          list.appendChild(loading);
        }
        var res = await fetch(dashboardJsConfig.tagsJsonUrl || '/categories/types/json/', {
          credentials: 'same-origin',
          headers: { Accept: 'application/json' },
        });
        var data = {};
        var raw = await res.text();
        try { data = JSON.parse(raw); } catch (err) { data = {}; }
        if (!res.ok || !data.ok) {
          throw new Error((data.detail && String(data.detail)) || raw.slice(0, 160) || ('HTTP ' + res.status));
        }
        renderManageTagsList(Array.isArray(data.tags) ? data.tags : []);
      }
      async function openManageTagsDialog() {
        var dialog = manageTagsDialogEl();
        if (!dialog || typeof dialog.showModal !== 'function') return;
        setManageTagsError('');
        var createInput = document.getElementById('manage-tags-create-label');
        if (createInput) createInput.value = '';
        bindManageTagsDialog();
        if (!dialog.open) dialog.showModal();
        try {
          await loadManageTagsList();
        } catch (err) {
          setManageTagsError((err && err.message) || 'Could not load tags.');
        }
        if (createInput) window.setTimeout(function () { createInput.focus(); }, 0);
      }
      async function createTagFromModal() {
        var input = document.getElementById('manage-tags-create-label');
        var submitBtn = document.getElementById('manage-tags-create-submit');
        var label = input ? String(input.value || '').trim() : '';
        if (!label) {
          setManageTagsError('Enter a tag name.');
          if (input) input.focus();
          return;
        }
        setManageTagsError('');
        if (submitBtn) submitBtn.disabled = true;
        try {
          var body = new URLSearchParams();
          body.set('label', label);
          var data = await postTagJson(dashboardJsConfig.categoryTypeSaveUrl, body);
          appendCreatedTagToUi(String(data.slug || ''), String(data.label || label));
          if (input) input.value = '';
          await loadManageTagsList();
        } catch (err) {
          setManageTagsError((err && err.message) || 'Could not create tag.');
        } finally {
          if (submitBtn) submitBtn.disabled = false;
        }
      }
      async function saveManageTagsRow(row) {
        if (!row) return;
        var input = row.querySelector('.manage-tags-label');
        var saveBtn = row.querySelector('.manage-tags-save');
        var label = input ? String(input.value || '').trim() : '';
        var tagId = row.getAttribute('data-tag-id') || '';
        var slug = row.getAttribute('data-tag-slug') || '';
        if (!label) {
          setManageTagsError('Enter a tag name.');
          if (input) input.focus();
          return;
        }
        setManageTagsError('');
        if (saveBtn) saveBtn.disabled = true;
        try {
          var body = new URLSearchParams();
          body.set('id', tagId);
          body.set('label', label);
          if (slug) body.set('slug', slug);
          body.set('sort_order', row.getAttribute('data-sort-order') || '100');
          var data = await postTagJson(dashboardJsConfig.categoryTypeSaveUrl, body);
          var newSlug = String(data.slug || slug);
          var newLabel = String(data.label || label);
          row.setAttribute('data-tag-slug', newSlug);
          if (input) input.value = newLabel;
          renameTagInUi(slug, newSlug, newLabel);
        } catch (err) {
          setManageTagsError((err && err.message) || 'Could not save tag.');
        } finally {
          if (saveBtn) saveBtn.disabled = false;
        }
      }
      async function deleteManageTagsRow(row) {
        if (!row || row.getAttribute('data-is-system') === '1') return;
        var tagId = row.getAttribute('data-tag-id') || '';
        var slug = row.getAttribute('data-tag-slug') || '';
        var input = row.querySelector('.manage-tags-label');
        var label = input ? String(input.value || '').trim() : slug;
        var ok = true;
        if (typeof window.appConfirm === 'function') {
          ok = await window.appConfirm({
            title: 'Delete tag?',
            message: 'Delete “' + label + '”? This cannot be undone.',
            confirmLabel: 'Delete',
            danger: true,
          });
        }
        if (!ok) return;
        setManageTagsError('');
        var delBtn = row.querySelector('.manage-tags-delete');
        if (delBtn) delBtn.disabled = true;
        try {
          await postTagJson(tagDeleteUrl(tagId), new URLSearchParams());
          removeTagFromUi(slug);
          row.remove();
          var list = document.getElementById('manage-tags-list');
          if (list && !list.querySelector('.manage-tags-row')) {
            renderManageTagsList([]);
          }
        } catch (err) {
          setManageTagsError((err && err.message) || 'Could not delete tag.');
          if (delBtn) delBtn.disabled = false;
        }
      }
      function bindManageTagsDialog() {
        if (window.__manageTagsDialogBound) return;
        window.__manageTagsDialogBound = true;
        document.body.addEventListener('submit', function (e) {
          if (!e.target || e.target.id !== 'manage-tags-create') return;
          e.preventDefault();
          createTagFromModal();
        }, true);
        document.body.addEventListener('click', function (e) {
          if (e.target.closest('#manage-tags-close-x') || e.target.closest('#manage-tags-done')) {
            closeManageTagsDialog();
            return;
          }
          var dialog = manageTagsDialogEl();
          if (dialog && e.target === dialog) {
            closeManageTagsDialog();
            return;
          }
          var saveBtn = e.target.closest('.manage-tags-save');
          if (saveBtn) {
            saveManageTagsRow(saveBtn.closest('.manage-tags-row'));
            return;
          }
          var delBtn = e.target.closest('.manage-tags-delete');
          if (delBtn) {
            deleteManageTagsRow(delBtn.closest('.manage-tags-row'));
          }
        });
        document.body.addEventListener('keydown', function (e) {
          if (e.key !== 'Enter') return;
          var input = e.target.closest('.manage-tags-label');
          if (!input) return;
          e.preventDefault();
          saveManageTagsRow(input.closest('.manage-tags-row'));
        });
      }
      window.openManageTagsDialog = openManageTagsDialog;
      window.closeManageTagsDialog = closeManageTagsDialog;
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
            toggleLeadFilterButton(vipBtn);
            return;
          }
          var chainBtn = e.target.closest('#filter-chain-only');
          if (chainBtn) {
            toggleLeadFilterButton(chainBtn);
            return;
          }
          var noChainBtn = e.target.closest('#filter-no-chain-only');
          if (noChainBtn) {
            toggleLeadFilterButton(noChainBtn);
            return;
          }
          var queuedBtn = e.target.closest('#filter-queued-only');
          if (queuedBtn) {
            toggleLeadFilterButton(queuedBtn);
            if (typeof window.__refreshCurrentLeadFolder === 'function') {
              window.__refreshCurrentLeadFolder();
            }
            return;
          }
          var sentBtn = e.target.closest('#filter-sent-message-only');
          if (sentBtn) {
            toggleLeadFilterButton(sentBtn);
            return;
          }
          var unsentBtn = e.target.closest('#filter-unsent-message-only');
          if (unsentBtn) {
            toggleLeadFilterButton(unsentBtn);
            return;
          }
          var tagChip = e.target.closest('.lead-tag-filter-chip');
          if (tagChip) {
            var slug = tagChip.getAttribute('data-tag-slug') || '';
            var slugs = getLeadTagFilterSlugs();
            var idx = slugs.indexOf(slug);
            if (!slug) return;
            if (idx === -1) slugs.push(slug);
            else slugs.splice(idx, 1);
            saveLeadTagFilterSlugs(slugs);
            applyTableFilter({ resetPage: true });
            refreshSelectAllState();
            refreshSelectionVisuals();
            return;
          }
          var tagManageBtn = e.target.closest('#lead-tag-filter-manage');
          if (tagManageBtn) {
            openManageTagsDialog();
            return;
          }
          var tagFilterClear = e.target.closest('#lead-tag-filter-clear');
          if (tagFilterClear) {
            saveLeadTagFilterSlugs([]);
            applyTableFilter({ resetPage: true });
            refreshSelectAllState();
            refreshSelectionVisuals();
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
      window.tabBeforeGlobalSearch = dashboardJsConfig.readyGroupTabId || 'uncategorized';
      window.globalSearchDebounceTimer = null;
      window.globalSearchRequestId = 0;
      window.pendingHighlightLeadId = null;
      window.searchInput = document.getElementById('table-search');
      if (searchInput) {
        searchInput.addEventListener('input', handleLeadSearchInput);
      }
      document.getElementById('table-search-clear')?.addEventListener('click', function () {
        clearLeadToolbarQuickFilters();
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
          : (dashboardJsConfig.readyGroupTabId || 'uncategorized')
      );
      if (typeof rememberLeadTabFragment === 'function') {
        var bootTb = document.getElementById('clinics-table-body');
        var bootGrid = document.getElementById('clinics-grid-inner');
        if (bootTb && bootGrid) {
          rememberLeadTabFragment(currentLeadGroupTabId, {
            ok: true,
            tbody_html: bootTb.innerHTML,
            grid_html: bootGrid.innerHTML,
          });
        }
      }
      document.addEventListener('visibilitychange', function () {
        if (typeof window.__syncLeadChatIndicatorPolling === 'function') {
          window.__syncLeadChatIndicatorPolling();
        }
      });
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
                window.appAlert({
                  title: 'Could not save card order',
                  message: typeof o.data.detail === 'string' ? o.data.detail : 'Could not save card order.',
                }).then(function () {
                  switchLeadGroupTab(currentLeadGroupTabId, { force: true, skipHistory: true });
                });
              }
            })
            .catch(function () {
              window.appAlert('Could not save card order.').then(function () {
                switchLeadGroupTab(currentLeadGroupTabId, { force: true, skipHistory: true });
              });
            });
        });
      })();
      window.leadGroupTabBusy = false;
      document.getElementById('lead-group-tabs')?.addEventListener('click', function (e) {
        var tab = e.target.closest('.lead-group-tab[data-group-id]');
        if (!tab) return;
        e.preventDefault();
        e.stopPropagation();
        var gid = normalizeLeadGroupTabId(tab.getAttribute('data-group-id') || 'uncategorized');
        if (gid === normalizeLeadGroupTabId(currentLeadGroupTabId)) return;
        switchLeadGroupTab(gid, { historyMode: 'push' });
      });
      replaceDashboardUrlForCurrentTab('replace');
      document.getElementById('bulk-assign-owner-open')?.addEventListener('click', function (e) {
        e.preventDefault();
        e.stopPropagation();
        var ids = getUniqueSelectedLeadIds();
        if (ids.length < 1) return;
        toggleLeadOwnerAssignMenu(this, ids);
      });
      document.addEventListener(
        'click',
        function (e) {
          if (!leadOwnerAssignMenuOpen) return;
          var t = e.target;
          if (t.closest && t.closest('#lead-owner-assign-menu')) return;
          if (t.closest && t.closest('#bulk-assign-owner-open')) return;
          if (t.closest && t.closest('.assign-to-user-btn')) return;
          closeLeadOwnerAssignMenu();
        },
        true
      );
      document.addEventListener('keydown', function (e) {
        if (e.key === 'Escape' && leadOwnerAssignMenuOpen) closeLeadOwnerAssignMenu();
      });
      window.addEventListener('resize', function () {
        if (leadOwnerAssignMenuOpen && leadOwnerAssignMenuAnchor) positionLeadOwnerAssignMenu(leadOwnerAssignMenuAnchor);
      });
      document.getElementById('lead-owner-assign-menu')?.addEventListener('click', async function (e) {
        var pick = e.target.closest('.lead-owner-assign-pick');
        if (!pick || !this.contains(pick)) return;
        e.preventDefault();
        e.stopPropagation();
        var raw = pick.getAttribute('data-user-id');
        var userId = raw ? parseInt(raw, 10) : NaN;
        if (isNaN(userId)) return;
        var ids = pendingOwnerAssignLeadIds.map(function (v) { return parseInt(v, 10); }).filter(function (n) { return !isNaN(n); });
        if (!ids.length) {
          closeLeadOwnerAssignMenu();
          return;
        }
        var menu = document.getElementById('lead-owner-assign-menu');
        var picks = menu ? menu.querySelectorAll('.lead-owner-assign-pick') : [];
        picks.forEach(function (b) {
          b.disabled = true;
        });
        clearLeadOwnerAssignMenuErr();
        try {
          var res = await fetch(dashboardJsConfig.bulkAssignOwnerUrl, {
            method: 'POST',
            headers: {
              'Content-Type': 'application/json',
              'X-CSRFToken': getCsrfToken(),
            },
            credentials: 'same-origin',
            body: JSON.stringify({ ids: ids, user_id: userId }),
          });
          var data = await res.json().catch(function () { return {}; });
          if (!res.ok) {
            var errEl = document.getElementById('lead-owner-assign-menu-error');
            if (errEl) {
              errEl.textContent =
                typeof data.detail === 'string' ? data.detail : JSON.stringify(data.detail || res.statusText);
              errEl.classList.remove('hidden');
              positionLeadOwnerAssignMenu(leadOwnerAssignMenuAnchor);
            }
            return;
          }
          closeLeadOwnerAssignMenu();
          await switchLeadGroupTab(currentLeadGroupTabId, { force: true, skipHistory: true });
        } catch (err) {
          var errEl2 = document.getElementById('lead-owner-assign-menu-error');
          if (errEl2) {
            errEl2.textContent = 'Network error: ' + err;
            errEl2.classList.remove('hidden');
            positionLeadOwnerAssignMenu(leadOwnerAssignMenuAnchor);
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
        var assignUserBtn = e.target.closest('.assign-to-user-btn');
        if (assignUserBtn && this.contains(assignUserBtn)) {
          e.preventDefault();
          e.stopPropagation();
          var rawA = assignUserBtn.getAttribute('data-clinic-id');
          if (rawA) toggleLeadOwnerAssignMenu(assignUserBtn, [rawA]);
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
              fadeLeadsOutOfCurrentFilters([idV]);
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
          window.appConfirm({
            title: 'Delete this lead?',
            message: 'Delete this lead permanently? This cannot be undone.',
            confirmLabel: 'Delete',
            danger: true,
          }).then(function (ok) {
            if (!ok) return;
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
                  return window.appAlert(msg);
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
                return window.appAlert('Network error while deleting.');
              })
              .finally(function () {
                var still = document.querySelector('.lead-card-delete-btn[data-clinic-id="' + idDel + '"]');
                if (still) still.disabled = false;
              });
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
          tags: collectTagPickerSlugs(document.getElementById('clinic-edit-tags')),
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
          tags: collectTagPickerSlugs(document.getElementById('lead-create-tags')),
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
        var ok = await window.appConfirm({
          title: 'Delete conversation log?',
          message: 'Delete this conversation log?',
          confirmLabel: 'Delete',
          danger: true,
        });
        if (!ok) return;
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
        const tags = collectTagPickerSlugs(document.getElementById('bulk-manual-tags'));
        if (!tags.length) {
          if (bulkManualErr) {
            bulkManualErr.textContent = 'Select at least one tag.';
            bulkManualErr.classList.remove('hidden');
          }
          return;
        }
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
            body: JSON.stringify({ ids: ids, tags: tags }),
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
          var appliedTags = Array.isArray(data.tags) && data.tags.length ? data.tags : tags;
          ids.forEach(function (leadId) {
            applyLeadTagSlugsToDom(leadId, appliedTags);
          });
          if (typeof window.invalidateLeadTabFragmentCache === 'function') {
            window.invalidateLeadTabFragmentCache();
          }
          fadeLeadsOutOfCurrentFilters(ids);
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
      document.getElementById('bulk-auto-classify')?.addEventListener('click', async function () {
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
        const ok = await window.appConfirm({
          title: 'Auto-classify from name?',
          message: 'Re-tag selected leads that currently have only the Unknown tag, using match phrases. Leads that already have a real tag are skipped.',
          confirmLabel: 'Auto-classify',
        });
        if (!ok) return;
        const classifyBtn = document.getElementById('bulk-auto-classify');
        const classifyLabel = document.getElementById('bulk-auto-classify-label');
        const classifySpinner = document.getElementById('bulk-auto-classify-spinner');
        if (classifyBtn) classifyBtn.disabled = true;
        if (bulkManualSubmit) bulkManualSubmit.disabled = true;
        if (classifySpinner) classifySpinner.classList.remove('hidden');
        if (classifyLabel) classifyLabel.textContent = 'Classifying…';
        try {
          const res = await fetch(dashboardJsConfig.bulkAutoClassifyUrl, {
            method: 'POST',
            headers: {
              'Content-Type': 'application/json',
              'X-CSRFToken': getCsrfToken(),
            },
            credentials: 'same-origin',
            body: JSON.stringify({ ids: ids }),
          });
          const data = await res.json().catch(function () { return {}; });
          if (!res.ok) {
            if (bulkManualErr) {
              bulkManualErr.textContent = typeof data.detail === 'string' ? data.detail : JSON.stringify(data.detail || res.statusText);
              bulkManualErr.classList.remove('hidden');
            }
            return;
          }
          const summary = typeof data.message === 'string' && data.message
            ? data.message
            : ('Updated ' + (data.updated || 0) + ' leads.');
          closeBulkManualDialog();
          await window.appAlert({
            title: 'Auto-classify from name',
            message: summary,
          });
          if ((data.updated || 0) > 0) window.location.reload();
        } catch (err) {
          if (bulkManualErr) {
            bulkManualErr.textContent = 'Network error: ' + err;
            bulkManualErr.classList.remove('hidden');
          }
        } finally {
          if (classifyBtn) classifyBtn.disabled = false;
          if (bulkManualSubmit) bulkManualSubmit.disabled = false;
          if (classifySpinner) classifySpinner.classList.add('hidden');
          if (classifyLabel) classifyLabel.textContent = 'Auto-classify from name';
        }
      });
      window.__dashboardOnWorkspaceShown = function () {
        initClinicViewModeFromStorage();
        syncLeadSortSelect();
        applyLeadSort();
        if (typeof window.syncLeadTagFilterUi === 'function') window.syncLeadTagFilterUi();
        if (typeof window.applyTableFilter === 'function') window.applyTableFilter({ resetPage: false });
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
