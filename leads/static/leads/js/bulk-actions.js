(function () {
  if (window.__leadsDashboardSkip) return;
      function refreshBulkActionDock() {
        var dock = document.getElementById('bulk-action-dock');
        if (!dock) return;
        var n = getUniqueSelectedLeadIds().length;
        var countEl = document.getElementById('bulk-action-dock-count');
        if (countEl) {
          countEl.textContent = n + (n === 1 ? ' selected' : ' selected');
        }

        // Only ever show the dock on the Leads workspace panel.
        var dashPanel = document.getElementById('workspace-panel-dashboard');
        var onLeadsPage = !!dashPanel && !dashPanel.hasAttribute('hidden');

        var gid = typeof currentLeadGroupTabId !== 'undefined' && currentLeadGroupTabId != null
          ? String(currentLeadGroupTabId)
          : 'uncategorized';
        var onQueueTab = dashboardJsConfig.queueGroupTabId &&
          gid === String(dashboardJsConfig.queueGroupTabId);
        var onTrashTab = dashboardJsConfig.trashGroupTabId &&
          gid === String(dashboardJsConfig.trashGroupTabId);

        // Queue → "Choose batch" + "Remove from queue"; Trash → no bulk action; else → "Push to queue".
        var showQueueBtn = onLeadsPage && !onQueueTab && !onTrashTab;
        var showBatchBtn = onLeadsPage && onQueueTab;
        var showDequeueBtn = onLeadsPage && onQueueTab;

        var visible = n > 0 && onLeadsPage && (showQueueBtn || showBatchBtn || showDequeueBtn);
        dock.hidden = !visible;
        dock.setAttribute('aria-hidden', visible ? 'false' : 'true');
        dock.classList.toggle('bulk-action-dock--visible', visible);

        var queueBtn = document.getElementById('bulk-wa-queue-btn');
        var batchBtn = document.getElementById('bulk-choose-batch-btn');
        var dequeueBtn = document.getElementById('bulk-dequeue-btn');
        // NOTE: the Tailwind `inline-flex` utility on these buttons overrides the
        // `[hidden]` UA rule, so toggling the `hidden` property alone won't hide
        // them. Force visibility via inline `display` (highest specificity).
        if (queueBtn) {
          queueBtn.hidden = !showQueueBtn;
          queueBtn.style.display = showQueueBtn ? '' : 'none';
        }
        if (batchBtn) {
          batchBtn.hidden = !showBatchBtn;
          batchBtn.style.display = showBatchBtn ? '' : 'none';
        }
        if (dequeueBtn) {
          dequeueBtn.hidden = !showDequeueBtn;
          dequeueBtn.style.display = showDequeueBtn ? '' : 'none';
        }
      }
      window.refreshBulkActionDock = refreshBulkActionDock;
      async function bulkDequeueSelectedFromQueue() {
        var ids = getUniqueSelectedLeadIds();
        if (!ids.length) return;
        var ok = await window.appConfirm({
          title: 'Remove from queue?',
          message: 'Remove ' + ids.length + ' selected lead(s) from the WhatsApp queue?',
          confirmLabel: 'Remove',
          danger: true,
        });
        if (!ok) return;
        var btn = document.getElementById('bulk-dequeue-btn');
        if (btn) btn.disabled = true;
        try {
          var res = await fetch(dashboardJsConfig.bulkDequeueUrl, {
            method: 'POST',
            credentials: 'same-origin',
            headers: {
              'Content-Type': 'application/json',
              'X-CSRFToken': getCsrfToken(),
            },
            body: JSON.stringify({ ids: ids }),
          });
          var data = await res.json();
          if (!res.ok || !data.ok) {
            throw new Error((data.detail && String(data.detail)) || ('HTTP ' + res.status));
          }
          var statusEl = document.getElementById('clinic-save-status');
          if (statusEl) {
            var msg = 'Removed ' + (data.updated || 0) + ' lead(s) from the queue.';
            if (data.skipped) msg += ' ' + data.skipped + ' skipped (not pending).';
            statusEl.textContent = msg;
            statusEl.classList.remove('hidden');
            window.setTimeout(function () { statusEl.classList.add('hidden'); }, 3200);
          }
          if (selectAll) selectAll.checked = false;
          await switchLeadGroupTab(currentLeadGroupTabId, { force: true, skipHistory: true });
        } catch (err) {
          console.error(err);
          await window.appAlert((err && err.message) || 'Could not remove selected leads from the queue.');
        } finally {
          if (btn) btn.disabled = false;
        }
      }
      window.bulkDequeueSelectedFromQueue = bulkDequeueSelectedFromQueue;
      async function bulkPushSelectedToWhatsappQueue() {
        var ids = getUniqueSelectedLeadIds();
        if (!ids.length) return;
        var btn = document.getElementById('bulk-wa-queue-btn');
        if (btn) btn.disabled = true;
        try {
          var res = await fetch(dashboardJsConfig.bulkWhatsappQueueUrl, {
            method: 'POST',
            credentials: 'same-origin',
            headers: {
              'Content-Type': 'application/json',
              'X-CSRFToken': getCsrfToken(),
            },
            body: JSON.stringify({ ids: ids }),
          });
          var data = await res.json();
          if (!res.ok || !data.ok) {
            throw new Error((data.detail && String(data.detail)) || ('HTTP ' + res.status));
          }
          var statusEl = document.getElementById('clinic-save-status');
          if (statusEl) {
            statusEl.textContent = 'Queued ' + (data.updated || 0) + ' lead(s) for WhatsApp outreach.';
            statusEl.classList.remove('hidden');
            window.setTimeout(function () { statusEl.classList.add('hidden'); }, 3200);
          }
          if (selectAll) selectAll.checked = false;
          await switchLeadGroupTab(currentLeadGroupTabId, { force: true, skipHistory: true });
        } catch (err) {
          console.error(err);
          await window.appAlert((err && err.message) || 'Could not queue selected leads.');
        } finally {
          if (btn) btn.disabled = false;
        }
      }
      window.bulkPushSelectedToWhatsappQueue = bulkPushSelectedToWhatsappQueue;
      function showChooseBatchError(msg) {
        var el = document.getElementById('choose-batch-error');
        if (!el) return;
        el.textContent = msg || 'Something went wrong.';
        el.classList.remove('hidden');
      }
      window.showChooseBatchError = showChooseBatchError;
      function clearChooseBatchError() {
        var el = document.getElementById('choose-batch-error');
        if (el) el.classList.add('hidden');
      }
      window.clearChooseBatchError = clearChooseBatchError;
      function toggleChooseBatchNewFields() {
        var sel = document.getElementById('choose-batch-select');
        var fields = document.getElementById('choose-batch-new-fields');
        if (!sel || !fields) return;
        fields.classList.toggle('hidden', sel.value !== 'new');
      }
      window.toggleChooseBatchNewFields = toggleChooseBatchNewFields;
      async function populateChooseBatchDialog() {
        var sel = document.getElementById('choose-batch-select');
        var tplSel = document.getElementById('choose-batch-template');
        if (sel) sel.innerHTML = '<option value="">Loading…</option>';
        try {
          var res = await fetch(dashboardJsConfig.whatsappBatchesJsonUrl, { credentials: 'same-origin' });
          var data = await res.json();
          if (!res.ok || !data.ok) throw new Error('HTTP ' + res.status);
          if (sel) {
            sel.innerHTML = '';
            (data.batches || []).forEach(function (b) {
              var opt = document.createElement('option');
              opt.value = String(b.id);
              opt.textContent = b.label;
              sel.appendChild(opt);
            });
            var newOpt = document.createElement('option');
            newOpt.value = 'new';
            newOpt.textContent = '+ New batch…';
            sel.appendChild(newOpt);
            if (!data.batches || !data.batches.length) sel.value = 'new';
          }
          if (tplSel) {
            tplSel.innerHTML = '';
            (data.templates || []).forEach(function (pair) {
              var opt = document.createElement('option');
              opt.value = pair[0];
              opt.textContent = pair[1];
              if (pair[0] === data.default_template) opt.selected = true;
              tplSel.appendChild(opt);
            });
          }
          toggleChooseBatchNewFields();
        } catch (e) {
          showChooseBatchError('Could not load batches.');
        }
      }
      window.populateChooseBatchDialog = populateChooseBatchDialog;
      function openChooseBatchDialog() {
        var ids = getUniqueSelectedLeadIds();
        if (!ids.length || !chooseBatchDialog) return;
        clearChooseBatchError();
        var countEl = document.getElementById('choose-batch-count');
        if (countEl) countEl.textContent = String(ids.length);
        chooseBatchDialog.showModal();
        populateChooseBatchDialog();
      }
      window.openChooseBatchDialog = openChooseBatchDialog;
      function closeChooseBatchDialog() {
        if (chooseBatchDialog) chooseBatchDialog.close();
      }
      window.closeChooseBatchDialog = closeChooseBatchDialog;
      async function submitChooseBatch() {
        var ids = getUniqueSelectedLeadIds();
        if (!ids.length) return;
        var sel = document.getElementById('choose-batch-select');
        var submitBtn = document.getElementById('choose-batch-submit');
        clearChooseBatchError();
        var payload = { ids: ids, batch_id: sel ? sel.value : '' };
        if (!payload.batch_id) {
          showChooseBatchError('Pick a batch or create a new one.');
          return;
        }
        if (payload.batch_id === 'new') {
          payload.new_batch = {
            outbound_template_name: (document.getElementById('choose-batch-template') || {}).value || '',
            scheduled_date: (document.getElementById('choose-batch-date') || {}).value || '',
            scheduled_time: (document.getElementById('choose-batch-time') || {}).value || '',
          };
        }
        if (submitBtn) submitBtn.disabled = true;
        try {
          var res = await fetch(dashboardJsConfig.bulkAssignBatchUrl, {
            method: 'POST',
            credentials: 'same-origin',
            headers: { 'Content-Type': 'application/json', 'X-CSRFToken': getCsrfToken() },
            body: JSON.stringify(payload),
          });
          var data = await res.json();
          if (!res.ok || !data.ok) {
            throw new Error((data.detail && String(data.detail)) || ('HTTP ' + res.status));
          }
          var assigned = data.updated || 0;
          var skipped = data.skipped || 0;
          var msg = 'Assigned ' + assigned + ' lead' + (assigned === 1 ? '' : 's') + ' to the batch.';
          if (skipped > 0) {
            msg += ' ' + skipped + ' already in a pending batch — skipped.';
          }
          var statusEl = document.getElementById('clinic-save-status');
          if (statusEl) {
            var warnClasses = ['bg-amber-50', 'text-amber-900', 'ring-amber-200/90'];
            var okClasses = ['bg-emerald-50', 'text-emerald-900', 'ring-emerald-200/90'];
            statusEl.classList.remove.apply(statusEl.classList, skipped > 0 ? okClasses : warnClasses);
            statusEl.classList.add.apply(statusEl.classList, skipped > 0 ? warnClasses : okClasses);
            statusEl.textContent = msg;
            statusEl.classList.remove('hidden');
            window.setTimeout(function () { statusEl.classList.add('hidden'); }, skipped > 0 ? 5200 : 3200);
          }
          closeChooseBatchDialog();
          if (selectAll) selectAll.checked = false;
          await switchLeadGroupTab(currentLeadGroupTabId, { force: true, skipHistory: true });
        } catch (err) {
          showChooseBatchError((err && err.message) || 'Could not assign leads.');
        } finally {
          if (submitBtn) submitBtn.disabled = false;
        }
      }
      window.submitChooseBatch = submitChooseBatch;
      function getUniqueSelectedLeadIds() {
        const seen = Object.create(null);
        const out = [];
        getVisibleClinicRows().forEach(function (row) {
          const cb = row.querySelector('.clinic-select-cb');
          if (!cb || !cb.checked) return;
          const v = cb.value;
          if (v != null && v !== '' && !seen[v]) {
            seen[v] = true;
            out.push(v);
          }
        });
        return out;
      }
      window.getUniqueSelectedLeadIds = getUniqueSelectedLeadIds;
      function refreshSetCategoryButtonState() {
        const btn = document.getElementById('bulk-manual-open');
        if (!btn) return;
        const n = getUniqueSelectedLeadIds().length;
        btn.disabled = n < 1;
      }
      window.refreshSetCategoryButtonState = refreshSetCategoryButtonState;
      function refreshBulkAssignGroupButtonState() {
        const n = getUniqueSelectedLeadIds().length;
        const btn = document.getElementById('bulk-assign-group-open');
        if (btn) btn.disabled = n < 1;
        const ownerBtn = document.getElementById('bulk-assign-owner-open');
        if (ownerBtn) ownerBtn.disabled = n < 1;
      }
      window.refreshBulkAssignGroupButtonState = refreshBulkAssignGroupButtonState;
      function bindSelectableSurface(root) {
        if (!root) return;
        // Stop shift+click from highlighting card text as a side-effect.
        root.addEventListener('mousedown', function (e) {
          if (!e.shiftKey) return;
          const row = e.target.closest('.clinic-row--selectable');
          if (!row || !root.contains(row)) return;
          if (e.target.closest('a, button, input, textarea, select, label')) return;
          e.preventDefault();
        });
        root.addEventListener('click', function (e) {
          const row = e.target.closest('.clinic-row--selectable');
          if (!row || !root.contains(row)) return;
          if (e.target.closest('a, button, input, textarea, select, label')) return;
          const cb = row.querySelector('.clinic-select-cb');
          if (!cb) return;

          // Shift+click selects the contiguous range from the anchor to here.
          if (e.shiftKey && selectionAnchorId != null) {
            const rows = getVisibleClinicRows(root);
            const clickedIdx = rows.indexOf(row);
            let anchorIdx = -1;
            for (let i = 0; i < rows.length; i++) {
              const rcb = rows[i].querySelector('.clinic-select-cb');
              if (rcb && rcb.value === selectionAnchorId) { anchorIdx = i; break; }
            }
            if (anchorIdx >= 0 && clickedIdx >= 0) {
              const newState = !cb.checked;
              const start = Math.min(anchorIdx, clickedIdx);
              const end = Math.max(anchorIdx, clickedIdx);
              const seen = Object.create(null);
              for (let i = start; i <= end; i++) {
                const rcb = rows[i].querySelector('.clinic-select-cb');
                if (!rcb || seen[rcb.value]) continue;
                seen[rcb.value] = true;
                setLeadCheckboxSelected(rcb.value, newState);
              }
              selectionAnchorId = cb.value;
              if (window.getSelection) { try { window.getSelection().removeAllRanges(); } catch (err) {} }
              refreshSelectAllState();
              refreshSelectionVisuals();
              return;
            }
          }

          cb.checked = !cb.checked;
          selectionAnchorId = cb.value;
          cb.dispatchEvent(new Event('change', { bubbles: true }));
        });
      }
      window.bindSelectableSurface = bindSelectableSurface;
      function exportXlsxSetBusy(busy) {
        if (!exportXlsxBtn) return;
        exportXlsxBtn.disabled = !!busy;
        if (exportXlsxIcon) exportXlsxIcon.classList.toggle('hidden', !!busy);
        if (exportXlsxSpinner) exportXlsxSpinner.classList.toggle('hidden', !busy);
      }
      window.exportXlsxSetBusy = exportXlsxSetBusy;
      function exportXlsxShowErr(msg) {
        if (!exportXlsxStatus) return;
        exportXlsxStatus.textContent = msg || '';
        exportXlsxStatus.classList.toggle('hidden', !msg);
      }
      window.exportXlsxShowErr = exportXlsxShowErr;
      function backupAllSetBusy(busy) {
        if (!backupAllBtn) return;
        backupAllBtn.disabled = !!busy;
        if (backupAllIcon) backupAllIcon.classList.toggle('hidden', !!busy);
        if (backupAllSpinner) backupAllSpinner.classList.toggle('hidden', !busy);
      }
      window.backupAllSetBusy = backupAllSetBusy;
      function restoreBackupSetBusy(busy) {
        if (!restoreBackupBtn) return;
        restoreBackupBtn.disabled = !!busy;
        if (restoreBackupIcon) restoreBackupIcon.classList.toggle('hidden', !!busy);
        if (restoreBackupSpinner) restoreBackupSpinner.classList.toggle('hidden', !busy);
      }
      window.restoreBackupSetBusy = restoreBackupSetBusy;
      function closeBulkManualDialog() {
        if (bulkManualDialog) bulkManualDialog.close();
      }
      window.closeBulkManualDialog = closeBulkManualDialog;
      function clearBulkManualErr() {
        if (!bulkManualErr) return;
        bulkManualErr.classList.add('hidden');
        bulkManualErr.textContent = '';
      }
      window.clearBulkManualErr = clearBulkManualErr;
})();
