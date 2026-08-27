(function () {
  if (window.__leadsDashboardSkip) return;
      function syncManualPhoneRemoveVisibility(container) {
        if (!container) return;
        var rows = container.querySelectorAll('.manual-phone-row');
        var multi = rows.length > 1;
        rows.forEach(function (row) {
          var btn = row.querySelector('.manual-phone-remove');
          if (btn) {
            btn.style.visibility = multi ? 'visible' : 'hidden';
            btn.disabled = !multi;
          }
        });
      }
      window.syncManualPhoneRemoveVisibility = syncManualPhoneRemoveVisibility;
      function appendManualPhoneRow(container, localDigits, skipCapCheck) {
        if (!container || !manualPhoneRowTpl) return;
        if (!skipCapCheck && container.querySelectorAll('.manual-phone-row').length >= MANUAL_PHONE_MAX) return;
        var frag = manualPhoneRowTpl.content.cloneNode(true);
        var inp = frag.querySelector('.manual-phone-local');
        if (inp && localDigits != null && localDigits !== '') inp.value = localDigits;
        container.appendChild(frag);
        syncManualPhoneRemoveVisibility(container);
      }
      window.appendManualPhoneRow = appendManualPhoneRow;
      function fillManualPhoneList(container, storedPhonesE164) {
        if (!container) return;
        container.innerHTML = '';
        var localList = [];
        if (Array.isArray(storedPhonesE164) && storedPhonesE164.length) {
          storedPhonesE164.forEach(function (s) {
            localList.push(window.phoneStoredToLocalField(s));
          });
        } else {
          localList.push('');
        }
        localList.forEach(function (localVal) {
          appendManualPhoneRow(container, localVal, true);
        });
        if (!container.querySelector('.manual-phone-row')) appendManualPhoneRow(container, '', true);
        syncManualPhoneRemoveVisibility(container);
      }
      window.fillManualPhoneList = fillManualPhoneList;
      function collectManualPhonePayload(container) {
        var out = [];
        if (!container) return out;
        container.querySelectorAll('.manual-phone-local').forEach(function (inp) {
          var n = window.normalizeManualPhoneFromLocal(inp.value || '');
          if (n && out.indexOf(n) === -1) out.push(n);
        });
        return out;
      }
      window.collectManualPhonePayload = collectManualPhonePayload;
      function collectTagPickerSlugs(container) {
        var out = [];
        if (!container) return out;
        container.querySelectorAll('.lead-tag-picker-cb:checked').forEach(function (cb) {
          var v = String(cb.value || '').trim().toLowerCase();
          if (v && out.indexOf(v) === -1) out.push(v);
        });
        return out;
      }
      window.collectTagPickerSlugs = collectTagPickerSlugs;
      function setTagPickerSlugs(container, slugs) {
        var wanted = Object.create(null);
        (Array.isArray(slugs) ? slugs : []).forEach(function (s) {
          var key = String(s || '').trim().toLowerCase();
          if (key) wanted[key] = true;
        });
        if (!container) return;
        container.querySelectorAll('.lead-tag-picker-cb').forEach(function (cb) {
          cb.checked = !!wanted[String(cb.value || '').trim().toLowerCase()];
        });
      }
      window.setTagPickerSlugs = setTagPickerSlugs;
      function closeClinicEditDialog() {
        if (editDialog) editDialog.close();
      }
      window.closeClinicEditDialog = closeClinicEditDialog;
      function showEditError(msg) {
        if (!editErr) return;
        editErr.textContent = msg;
        editErr.classList.remove('hidden');
      }
      window.showEditError = showEditError;
      function clearEditError() {
        if (!editErr) return;
        editErr.classList.add('hidden');
        editErr.textContent = '';
      }
      window.clearEditError = clearEditError;
      async function openClinicEditModal(clinicId) {
        if (!editDialog || !editForm) return;
        clearEditError();
        var idHidden = document.getElementById('clinic-edit-id');
        if (idHidden) idHidden.value = '';
        if (editSaveBtn) editSaveBtn.disabled = true;
        editDialog.showModal();
        try {
          const res = await fetch(clinicApiDetailPrefix + clinicId, { credentials: 'same-origin' });
          const data = await res.json().catch(function () { return null; });
          if (!res.ok || !data) {
            showEditError(data && data.detail ? String(data.detail) : 'Could not load lead.');
            return;
          }
          document.getElementById('clinic-edit-id').value = String(data.id);
          document.getElementById('clinic-edit-name').value = data.name || '';
          var nums = Array.isArray(data.phone_numbers) && data.phone_numbers.length
            ? data.phone_numbers
            : (data.phone_number ? [data.phone_number] : []);
          fillManualPhoneList(document.getElementById('clinic-edit-phones-list'), nums);
          document.getElementById('clinic-edit-address').value = data.address || '';
          document.getElementById('clinic-edit-website').value = data.website || '';
          document.getElementById('clinic-edit-search-state').value = data.search_state || '';
          document.getElementById('clinic-edit-search-city').value = data.search_city || '';
          document.getElementById('clinic-edit-search-query').value = data.search_query || '';
          var tagSlugs = Array.isArray(data.tags) ? data.tags : [];
          if (!tagSlugs.length && (data.category || data.clinic_type)) {
            tagSlugs = [data.category || data.clinic_type];
          }
          setTagPickerSlugs(document.getElementById('clinic-edit-tags'), tagSlugs);
          document.getElementById('clinic-edit-chain').checked = !!data.is_chain;
          var waEl = document.getElementById('clinic-edit-whatsapp');
          if (waEl) waEl.value = data.whatsapp_draft || '';
          if (editSaveBtn) editSaveBtn.disabled = false;
        } catch (e) {
          showEditError('Could not load clinic.');
        }
      }
      window.openClinicEditModal = openClinicEditModal;
      function leadRowSnippetFromAddressTrigger(addrBtn) {
        var row = addrBtn.closest('.clinic-row');
        var name = '';
        if (row) {
          var link = row.querySelector('.clinic-name-link');
          if (link) name = (link.textContent || '').replace(/\s+/g, ' ').trim();
        }
        var addr = (addrBtn.getAttribute('data-address-copy') || '').trim();
        if (!addr) {
          var clone = addrBtn.cloneNode(true);
          var badge = clone.querySelector('.address-copy-done');
          if (badge) badge.remove();
          var tx = (clone.textContent || '').replace(/\s+/g, ' ').trim();
          if (tx && tx !== '—') addr = tx;
        }
        if (!name) name = (addrBtn.getAttribute('data-clinic-name') || '').trim();
        return { name: name, address: addr };
      }
      window.leadRowSnippetFromAddressTrigger = leadRowSnippetFromAddressTrigger;
      function closeLeadCreateDialog() {
        if (leadCreateDialog) leadCreateDialog.close();
      }
      window.closeLeadCreateDialog = closeLeadCreateDialog;
      function clearLeadCreateError() {
        if (!leadCreateErr) return;
        leadCreateErr.classList.add('hidden');
        leadCreateErr.textContent = '';
      }
      window.clearLeadCreateError = clearLeadCreateError;
      function showLeadCreateError(msg) {
        if (!leadCreateErr) return;
        leadCreateErr.textContent = msg;
        leadCreateErr.classList.remove('hidden');
      }
      window.showLeadCreateError = showLeadCreateError;
      function resetLeadCreateForm() {
        if (!leadCreateForm) return;
        leadCreateForm.reset();
        setTagPickerSlugs(document.getElementById('lead-create-tags'), ['unknown']);
        fillManualPhoneList(document.getElementById('lead-create-phones-list'), []);
      }
      window.resetLeadCreateForm = resetLeadCreateForm;
      function closeLeadConversationLogDialog() {
        if (leadConversationLogDialog) leadConversationLogDialog.close();
      }
      window.closeLeadConversationLogDialog = closeLeadConversationLogDialog;
      function clearLeadConversationLogMessages() {
        if (leadConversationLogErr) {
          leadConversationLogErr.classList.add('hidden');
          leadConversationLogErr.textContent = '';
        }
        if (leadConversationLogOk) {
          leadConversationLogOk.classList.add('hidden');
          leadConversationLogOk.textContent = '';
        }
      }
      window.clearLeadConversationLogMessages = clearLeadConversationLogMessages;
      function showLeadConversationLogError(msg) {
        if (!leadConversationLogErr) return;
        leadConversationLogErr.textContent = msg;
        leadConversationLogErr.classList.remove('hidden');
      }
      window.showLeadConversationLogError = showLeadConversationLogError;
      function setLeadConversationLogVisual(leadId, hasLogs) {
        // The left green "conversation log" ribbon was removed; the green frame
        // (chat-record dispatched chrome) is the only card indicator now.
      }
      window.setLeadConversationLogVisual = setLeadConversationLogVisual;
      function renderLeadConversationHistory(logs) {
        if (!leadConversationHistoryList || !leadConversationHistoryEmpty) return;
        leadConversationHistoryList.innerHTML = '';
        var list = Array.isArray(logs) ? logs.slice() : [];
        list.sort(function (a, b) {
          var ad = String((a && a.conversation_date) || '');
          var bd = String((b && b.conversation_date) || '');
          if (ad !== bd) return ad.localeCompare(bd);
          var ac = String((a && a.created_at) || '');
          var bc = String((b && b.created_at) || '');
          return ac.localeCompare(bc);
        });
        if (!list.length) {
          leadConversationHistoryEmpty.classList.remove('hidden');
          return;
        }
        leadConversationHistoryEmpty.classList.add('hidden');
        list.forEach(function (item) {
          var wrap = document.createElement('div');
          wrap.className = 'grid grid-cols-[9rem,1fr] gap-3 rounded-xl border border-slate-200/90 bg-slate-50/70 px-3 py-2';
          var dateP = document.createElement('p');
          dateP.className = 'text-[11px] font-semibold text-slate-700';
          dateP.textContent = String(item && item.conversation_date ? item.conversation_date : '');
          var rightCol = document.createElement('div');
          rightCol.className = 'min-w-0 flex items-start gap-2';
          var remarksP = document.createElement('p');
          remarksP.className = 'min-w-0 flex-1 whitespace-pre-wrap break-words text-xs text-slate-700';
          remarksP.textContent = String(item && item.remarks ? item.remarks : '');
          var delBtn = document.createElement('button');
          delBtn.type = 'button';
          delBtn.className = 'lead-conversation-log-delete-btn inline-flex h-6 w-6 shrink-0 items-center justify-center rounded-md border border-red-200 bg-white text-red-700 transition hover:bg-red-50 focus:outline-none focus-visible:ring-2 focus-visible:ring-red-500/30';
          delBtn.setAttribute('data-log-id', String(item && item.id ? item.id : ''));
          delBtn.setAttribute('title', 'Delete log');
          delBtn.setAttribute('aria-label', 'Delete log');
          delBtn.innerHTML = '<svg class="h-3.5 w-3.5" fill="none" stroke="currentColor" stroke-width="2" viewBox="0 0 24 24" aria-hidden="true"><path stroke-linecap="round" stroke-linejoin="round" d="M6 18L18 6M6 6l12 12"/></svg>';
          wrap.appendChild(dateP);
          rightCol.appendChild(remarksP);
          rightCol.appendChild(delBtn);
          wrap.appendChild(rightCol);
          leadConversationHistoryList.appendChild(wrap);
        });
      }
      window.renderLeadConversationHistory = renderLeadConversationHistory;
      async function loadLeadConversationHistory(leadId) {
        if (!leadId) return;
        if (leadConversationHistoryList) {
          leadConversationHistoryList.innerHTML = '<p class="text-xs text-slate-400">Loading history...</p>';
        }
        if (leadConversationHistoryEmpty) {
          leadConversationHistoryEmpty.classList.add('hidden');
        }
        var url = leadConversationLogUrlTemplate.replace('__ID__', String(leadId));
        try {
          var res = await fetch(url, { credentials: 'same-origin' });
          var data = await res.json().catch(function () { return {}; });
          if (!res.ok) {
            renderLeadConversationHistory([]);
            setLeadConversationLogVisual(leadId, false);
            return;
          }
          var logs = data.logs || [];
          renderLeadConversationHistory(logs);
          setLeadConversationLogVisual(leadId, Array.isArray(logs) && logs.length > 0);
        } catch (err) {
          renderLeadConversationHistory([]);
          setLeadConversationLogVisual(leadId, false);
        }
      }
      window.loadLeadConversationHistory = loadLeadConversationHistory;
      async function deleteLeadConversationLog(leadId, logId) {
        if (!leadId || !logId) return;
        var url = leadConversationLogUrlTemplate.replace('__ID__', String(leadId)) + String(logId) + '/delete/';
        try {
          var res = await fetch(url, {
            method: 'DELETE',
            headers: {
              'X-CSRFToken': getCsrfToken(),
            },
            credentials: 'same-origin',
          });
          var data = await res.json().catch(function () { return {}; });
          if (!res.ok) {
            showLeadConversationLogError(typeof data.detail === 'string' ? data.detail : 'Could not delete log.');
            return;
          }
          await loadLeadConversationHistory(leadId);
        } catch (err) {
          showLeadConversationLogError('Network error while deleting log.');
        }
      }
      window.deleteLeadConversationLog = deleteLeadConversationLog;
      function openLeadConversationLogDialog(clinicId) {
        if (!leadConversationLogDialog) return;
        clearLeadConversationLogMessages();
        var idEl = document.getElementById('lead-conversation-log-id');
        var dateEl = document.getElementById('lead-conversation-date');
        var remarksEl = document.getElementById('lead-conversation-remarks');
        if (idEl) idEl.value = String(clinicId);
        if (dateEl) dateEl.value = new Date().toISOString().slice(0, 10);
        if (remarksEl) {
          remarksEl.value = '';
          remarksEl.focus();
        }
        if (leadConversationLogSubmitBtn) leadConversationLogSubmitBtn.disabled = false;
        leadConversationLogDialog.showModal();
        loadLeadConversationHistory(clinicId);
      }
      window.openLeadConversationLogDialog = openLeadConversationLogDialog;
})();
