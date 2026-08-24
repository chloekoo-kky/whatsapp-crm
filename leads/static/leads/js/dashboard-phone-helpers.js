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
    })(window);
