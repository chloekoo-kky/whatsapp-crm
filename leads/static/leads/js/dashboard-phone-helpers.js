/* Phone helpers on window: same-origin as server normalize_manual_phone; avoids ReferenceError if main bundle scope is wrong. */
    (function (w) {
      function phoneDigitsOnly(s) {
        return String(s || '').replace(/\D/g, '');
      }
      w.normalizeManualPhoneFromLocal = function (localRaw) {
        var s = String(localRaw || '').trim();
        if (!s) return '';
        var d = phoneDigitsOnly(s);
        if (!d) return '';
        if (d.indexOf('00') === 0) d = d.slice(2);
        if (d.indexOf('6060') === 0 && d.length >= 11) d = '60' + d.slice(4);
        if (d.indexOf('60') === 0 && d.length >= 10) return '+' + d.slice(0, 15);
        if (d.charAt(0) === '0' && d.length >= 9) return '+60' + d.slice(1, 15);
        if (d.length >= 8 && d.length <= 10) return '+60' + d.slice(0, 15);
        if (d.length >= 11) return '+' + d.slice(0, 15);
        return '+60' + d.slice(0, 15);
      };
      w.phoneStoredToLocalField = function (stored) {
        if (!stored || !String(stored).trim()) return '';
        var d = phoneDigitsOnly(stored);
        if (!d) return '';
        if (d.indexOf('00') === 0) d = d.slice(2);
        if (d.indexOf('60') === 0 && d.length > 2) return d.slice(2);
        if (d.charAt(0) === '0' && d.length >= 9) return d.slice(1);
        return d;
      };
      function whatsappDigitsFromOpenLink(a) {
        var digits = phoneDigitsOnly(a.getAttribute('data-wa-digits') || '');
        if (digits) return digits;
        var href = a.getAttribute('href') || '';
        var m = href.match(/phone=(\d+)/) || href.match(/wa\.me\/(\d+)/);
        return m ? m[1] : '';
      }
      function whatsappBusinessOpenHref(digits) {
        var ua = navigator.userAgent || '';
        if (/Android/i.test(ua)) {
          return 'intent://send?phone=' + digits
            + '#Intent;scheme=whatsapp;package=com.whatsapp.w4b;S.browser_fallback_url='
            + encodeURIComponent('https://wa.me/' + digits)
            + ';end';
        }
        if (/iPhone|iPad|iPod/i.test(ua)) {
          return 'whatsapp-business://send?phone=' + digits;
        }
        return 'whatsapp://send?phone=' + digits;
      }
      w.whatsappBusinessOpenHref = whatsappBusinessOpenHref;
      document.addEventListener('click', function (e) {
        var a = e.target.closest && e.target.closest('a.wa-me-open-btn');
        if (!a) return;
        var digits = whatsappDigitsFromOpenLink(a);
        if (!digits) return;
        e.preventDefault();
        e.stopPropagation();
        var ua = navigator.userAgent || '';
        if (/iPhone|iPad|iPod/i.test(ua)) {
          var started = Date.now();
          window.location.href = 'whatsapp-business://send?phone=' + digits;
          window.setTimeout(function () {
            if (document.hidden || document.webkitHidden) return;
            if (Date.now() - started < 1600) {
              window.location.href = 'whatsapp://send?phone=' + digits;
            }
          }, 700);
          return;
        }
        window.location.href = whatsappBusinessOpenHref(digits);
      }, true);
    })(window);
