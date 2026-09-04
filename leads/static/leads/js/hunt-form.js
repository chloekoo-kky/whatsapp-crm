(function () {
  if (window.__leadsDashboardSkip) return;
      function setLimit(limit, syncButtons) {
        const n = parseInt(limit, 10);
        const v = (isNaN(n) ? dashboardJsConfig.defaultLimit : n).toString();
        if (huntLimitInput) huntLimitInput.value = v;
        if (syncButtons) {
          limitButtons.forEach(function (btn) {
            const active = btn.getAttribute('data-limit') === v;
            btn.classList.toggle('limit-btn--active', active);
            btn.classList.toggle('bg-indigo-600', active);
            btn.classList.toggle('text-white', active);
            btn.classList.toggle('shadow-sm', active);
            btn.classList.toggle('text-slate-600', !active);
            btn.classList.toggle('hover:bg-slate-50', !active);
            btn.classList.toggle('hover:text-slate-900', !active);
          });
        }
      }
      window.setLimit = setLimit;
      function setHuntProvider(provider, syncButtons) {
        var allowed = { serper: true, outscraper: true };
        var v = allowed[provider] ? provider : 'serper';
        var input = document.getElementById('hunt-provider-value');
        if (input) input.value = v;
        if (syncButtons) {
          document.querySelectorAll('.hunt-provider-btn').forEach(function (btn) {
            var active = btn.getAttribute('data-provider') === v;
            btn.classList.toggle('limit-btn--active', active);
            btn.classList.toggle('bg-indigo-600', active);
            btn.classList.toggle('text-white', active);
            btn.classList.toggle('shadow-sm', active);
            btn.classList.toggle('text-slate-600', !active);
            btn.classList.toggle('hover:bg-slate-50', !active);
            btn.classList.toggle('hover:text-slate-900', !active);
            btn.setAttribute('aria-pressed', active ? 'true' : 'false');
          });
        }
        var badge = document.getElementById('hunt-provider-badge');
        if (badge) badge.textContent = v === 'outscraper' ? 'Outscraper' : 'Serper';
        var limitHelp = document.getElementById('hunt-limit-help');
        if (limitHelp) {
          limitHelp.textContent = v === 'outscraper'
            ? 'How many listings to fetch. Values above 20 run as an Outscraper job and are polled until ready.'
            : 'How many listings to fetch. Values above 20 request extra Serper pages automatically.';
        }
        try {
          localStorage.setItem(HUNT_PROVIDER_KEY, v);
        } catch (e) { /* ignore */ }
      }
      window.setHuntProvider = setHuntProvider;
      function bindHuntOptionToggle(el, storageKey) {
        if (!el) return;
        try {
          var stored = localStorage.getItem(storageKey);
          if (stored !== null) {
            el.checked = stored === "1" || stored === "true";
          }
        } catch (e) { /* ignore */ }
        el.addEventListener('change', function () {
          try {
            localStorage.setItem(storageKey, el.checked ? "1" : "0");
          } catch (e) { /* ignore */ }
        });
      }
      window.bindHuntOptionToggle = bindHuntOptionToggle;
      function loadHuntKeywordTags() {
        try {
          var raw = localStorage.getItem(HUNT_KEYWORD_TAGS_KEY);
          if (!raw) return [];
          var parsed = JSON.parse(raw);
          if (!Array.isArray(parsed)) return [];
          var out = [];
          var seen = Object.create(null);
          parsed.forEach(function (item) {
            var text = String(item || '').trim().slice(0, HUNT_KEYWORD_TAG_LEN_MAX);
            if (!text || seen[text]) return;
            seen[text] = true;
            out.push(text);
          });
          return out.slice(0, HUNT_KEYWORD_TAG_MAX);
        } catch (e) {
          return [];
        }
      }
      window.loadHuntKeywordTags = loadHuntKeywordTags;
      function saveHuntKeywordTags(tags) {
        try {
          localStorage.setItem(HUNT_KEYWORD_TAGS_KEY, JSON.stringify(tags.slice(0, HUNT_KEYWORD_TAG_MAX)));
        } catch (e) { /* ignore */ }
      }
      window.saveHuntKeywordTags = saveHuntKeywordTags;
      function refreshHuntKeywordTagSaveButton() {
        var saveBtn = document.getElementById('hunt-keyword-tag-save');
        var input = document.getElementById('hunt-shop-keyword');
        if (!saveBtn || !input) return;
        var text = input.value.trim();
        var tags = loadHuntKeywordTags();
        saveBtn.disabled = !text || tags.indexOf(text) !== -1;
      }
      window.refreshHuntKeywordTagSaveButton = refreshHuntKeywordTagSaveButton;
      function refreshHuntKeywordTagActiveState() {
        var input = document.getElementById('hunt-shop-keyword');
        var current = input ? input.value.trim() : '';
        document.querySelectorAll('.hunt-keyword-tag').forEach(function (chip) {
          var label = chip.getAttribute('data-tag') || '';
          var active = current && label === current;
          chip.classList.toggle('lead-filter-tag--active', active);
          var applyBtn = chip.querySelector('.lead-filter-tag-apply');
          if (applyBtn) applyBtn.setAttribute('aria-pressed', active ? 'true' : 'false');
        });
      }
      window.refreshHuntKeywordTagActiveState = refreshHuntKeywordTagActiveState;
      function renderHuntKeywordTags() {
        var list = document.getElementById('hunt-keyword-tags-list');
        if (!list) return;
        var tags = loadHuntKeywordTags();
        var input = document.getElementById('hunt-shop-keyword');
        var current = input ? input.value.trim() : '';
        list.innerHTML = tags.map(function (tag) {
          var active = current && tag === current;
          return (
            '<span class="lead-filter-tag hunt-keyword-tag' + (active ? ' lead-filter-tag--active' : '') + '" data-tag="' + escapeLeadFilterTagHtml(tag) + '" role="listitem">' +
              '<button type="button" class="lead-filter-tag-apply" aria-pressed="' + (active ? 'true' : 'false') + '" title="Use keyword: ' + escapeLeadFilterTagHtml(tag) + '">' +
                escapeLeadFilterTagHtml(tag) +
              '</button>' +
              '<button type="button" class="lead-filter-tag-remove" aria-label="Remove keyword tag ' + escapeLeadFilterTagHtml(tag) + '" title="Remove tag">×</button>' +
            '</span>'
          );
        }).join('');
        refreshHuntKeywordTagSaveButton();
      }
      window.renderHuntKeywordTags = renderHuntKeywordTags;
      function applyHuntKeywordTag(text) {
        var input = document.getElementById('hunt-shop-keyword');
        if (!input) return;
        input.value = text;
        refreshHuntKeywordTagSaveButton();
        refreshHuntKeywordTagActiveState();
        input.focus();
      }
      window.applyHuntKeywordTag = applyHuntKeywordTag;
      function addHuntKeywordTag(text) {
        var cleaned = String(text || '').trim().slice(0, HUNT_KEYWORD_TAG_LEN_MAX);
        if (!cleaned) return;
        var tags = loadHuntKeywordTags();
        if (tags.indexOf(cleaned) !== -1) return;
        tags.unshift(cleaned);
        saveHuntKeywordTags(tags);
        renderHuntKeywordTags();
      }
      window.addHuntKeywordTag = addHuntKeywordTag;
      function removeHuntKeywordTag(text) {
        var cleaned = String(text || '').trim();
        if (!cleaned) return;
        var tags = loadHuntKeywordTags().filter(function (t) { return t !== cleaned; });
        saveHuntKeywordTags(tags);
        renderHuntKeywordTags();
        refreshHuntKeywordTagActiveState();
      }
      window.removeHuntKeywordTag = removeHuntKeywordTag;
      function loadHuntExcludeKeywords() {
        try {
          var raw = localStorage.getItem(HUNT_EXCLUDE_TAGS_KEY);
          if (!raw) return [];
          var parsed = JSON.parse(raw);
          if (!Array.isArray(parsed)) return [];
          var out = [];
          var seen = Object.create(null);
          parsed.forEach(function (item) {
            var text = String(item || '').trim().slice(0, HUNT_EXCLUDE_TAG_LEN_MAX);
            if (!text || seen[text]) return;
            seen[text] = true;
            out.push(text);
          });
          return out.slice(0, HUNT_EXCLUDE_TAG_MAX);
        } catch (e) {
          return [];
        }
      }
      window.loadHuntExcludeKeywords = loadHuntExcludeKeywords;
      function saveHuntExcludeKeywords(tags) {
        try {
          localStorage.setItem(HUNT_EXCLUDE_TAGS_KEY, JSON.stringify(tags.slice(0, HUNT_EXCLUDE_TAG_MAX)));
        } catch (e) { /* ignore */ }
      }
      window.saveHuntExcludeKeywords = saveHuntExcludeKeywords;
      function refreshHuntExcludeTagSaveButton() {
        var saveBtn = document.getElementById('hunt-exclude-tag-save');
        var input = document.getElementById('hunt-exclude-keyword-input');
        if (!saveBtn || !input) return;
        var text = input.value.trim();
        var tags = loadHuntExcludeKeywords();
        saveBtn.disabled = !text || tags.indexOf(text) !== -1;
      }
      window.refreshHuntExcludeTagSaveButton = refreshHuntExcludeTagSaveButton;
      function renderHuntExcludeTags() {
        var list = document.getElementById('hunt-exclude-tags-list');
        if (!list) return;
        var tags = loadHuntExcludeKeywords();
        list.innerHTML = tags.map(function (tag) {
          return (
            '<span class="lead-filter-tag hunt-exclude-tag" data-tag="' + escapeLeadFilterTagHtml(tag) + '" role="listitem">' +
              '<span class="lead-filter-tag-apply text-rose-700" title="Excluded on hunt: ' + escapeLeadFilterTagHtml(tag) + '">' +
                escapeLeadFilterTagHtml(tag) +
              '</span>' +
              '<button type="button" class="lead-filter-tag-remove" aria-label="Remove exclude tag ' + escapeLeadFilterTagHtml(tag) + '" title="Remove tag">×</button>' +
            '</span>'
          );
        }).join('');
        refreshHuntExcludeTagSaveButton();
      }
      window.renderHuntExcludeTags = renderHuntExcludeTags;
      function addHuntExcludeTag(text) {
        var cleaned = String(text || '').trim().slice(0, HUNT_EXCLUDE_TAG_LEN_MAX);
        if (!cleaned) return;
        var tags = loadHuntExcludeKeywords();
        if (tags.indexOf(cleaned) !== -1) return;
        tags.push(cleaned);
        saveHuntExcludeKeywords(tags);
        renderHuntExcludeTags();
      }
      window.addHuntExcludeTag = addHuntExcludeTag;
      function removeHuntExcludeTag(text) {
        var cleaned = String(text || '').trim();
        if (!cleaned) return;
        var tags = loadHuntExcludeKeywords().filter(function (t) { return t !== cleaned; });
        saveHuntExcludeKeywords(tags);
        renderHuntExcludeTags();
      }
      window.removeHuntExcludeTag = removeHuntExcludeTag;
      async function runHunt() {
        huntStatus.textContent = '';
        huntBtn.disabled = true;
        huntSpinner.classList.remove('hidden');
        const requireWebsiteEl = document.getElementById('hunt-require-website');
        const require_website = !!(requireWebsiteEl && requireWebsiteEl.checked);
        huntBtnLabel.textContent = 'Scraping…';

        const city = document.getElementById('city').value.trim();
        const stateEl = document.getElementById('hunt-state');
        const state = stateEl ? stateEl.value.trim() : '';
        const countryEl = document.getElementById('hunt-country');
        const country = countryEl ? countryEl.value.trim() : '';
        const query = document.getElementById('query').value.trim();
        const shopKeywordEl = document.getElementById('hunt-shop-keyword');
        const shop_keyword = shopKeywordEl ? shopKeywordEl.value.trim() : '';
        const exclude_keywords = loadHuntExcludeKeywords();
        const providerEl = document.getElementById('hunt-provider-value');
        const provider = providerEl && providerEl.value === 'outscraper' ? 'outscraper' : 'serper';
        const limitRaw = huntLimitInput ? huntLimitInput.value : String(dashboardJsConfig.defaultLimit);
        const limit = parseInt(limitRaw, 10) || dashboardJsConfig.defaultLimit;
        const qs = new URLSearchParams({ limit: String(limit) });
        const url = dashboardJsConfig.huntApiPath + (dashboardJsConfig.huntApiPath.indexOf('?') >= 0 ? '&' : '?') + qs.toString();

        try {
          const res = await fetch(url, {
            method: 'POST',
            headers: {
              'Content-Type': 'application/json',
              'X-CSRFToken': getCsrfToken(),
            },
            credentials: 'same-origin',
            body: JSON.stringify({ city, state, country, query, shop_keyword, require_website, exclude_keywords, provider }),
          });
          const data = await res.json().catch(function () { return {}; });

          if (!res.ok) {
            const detail = data.detail || data.message || res.statusText;
            huntStatus.textContent = 'Error: ' + (typeof detail === 'string' ? detail : JSON.stringify(detail));
            huntStatus.classList.add('text-red-600');
            return;
          }

          huntStatus.classList.remove('text-red-600');
          huntStatus.textContent = data.message || ('Created ' + data.created + ', skipped ' + data.skipped_existing + '.');
          if (data.errors && data.errors.length) {
            huntStatus.textContent += ' Notes: ' + data.errors.join(' ');
          }
          if (data.enrich_errors && data.enrich_errors.length) {
            huntStatus.textContent += ' Enrich warnings: ' + data.enrich_errors.length + ' issue(s).';
          }
          activeSearchRecordId = null;
          replaceDashboardUrlForCurrentTab('replace');
          await switchLeadGroupTab(currentLeadGroupTabId, { force: true, skipHistory: true });
          document.body.dispatchEvent(new CustomEvent('apiStatusRefresh'));
        } catch (err) {
          huntStatus.classList.add('text-red-600');
          huntStatus.textContent = 'Network error: ' + err;
        } finally {
          huntBtn.disabled = false;
          huntSpinner.classList.add('hidden');
          huntBtnLabel.textContent = 'Run hunt';
        }
      }
      window.runHunt = runHunt;
})();
