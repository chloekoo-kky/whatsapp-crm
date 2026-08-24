(function () {
  if (window.__leadsDashboardSkip) return;
      function getCookie(name) {
        var v = null;
        if (document.cookie && document.cookie !== '') {
          var parts = document.cookie.split(';');
          for (var i = 0; i < parts.length; i++) {
            var c = parts[i].trim();
            if (c.substring(0, name.length + 1) === name + '=') {
              v = decodeURIComponent(c.substring(name.length + 1));
              break;
            }
          }
        }
        return v;
      }
      window.getCookie = getCookie;
      function getCsrfToken() {
        var fromCookie = getCookie('csrftoken');
        if (fromCookie) return fromCookie;
        var m = document.querySelector('meta[name="csrf-token"]');
        return m ? (m.getAttribute('content') || '') : '';
      }
      window.getCsrfToken = getCsrfToken;
      function dispatchHtmxTriggerHeader(headerValue) {
        if (!headerValue) return;
        try {
          var events = JSON.parse(headerValue);
          Object.keys(events).forEach(function (name) {
            document.body.dispatchEvent(new CustomEvent(name, { detail: events[name] }));
          });
        } catch (err) {
          console.error(err);
        }
      }
      window.dispatchHtmxTriggerHeader = dispatchHtmxTriggerHeader;
      function escapeHtml(s) {
        if (s == null) return '';
        return String(s)
          .replace(/&/g, '&amp;')
          .replace(/</g, '&lt;')
          .replace(/>/g, '&gt;')
          .replace(/"/g, '&quot;');
      }
      window.escapeHtml = escapeHtml;
      function escapeAttr(s) {
        return escapeHtml(s).replace(/'/g, '&#39;');
      }
      window.escapeAttr = escapeAttr;
})();
