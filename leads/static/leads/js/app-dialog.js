(function () {
  if (window.appConfirm) return;

  var queue = [];
  var active = null;
  var bound = false;

  function nodes() {
    return {
      dialog: document.getElementById('app-confirm-dialog'),
      titleEl: document.getElementById('app-confirm-title'),
      messageEl: document.getElementById('app-confirm-message'),
      cancelBtn: document.getElementById('app-confirm-cancel'),
      okBtn: document.getElementById('app-confirm-ok'),
      okDangerBtn: document.getElementById('app-confirm-ok-danger'),
    };
  }

  function normalize(messageOrOpts, extra) {
    var opts = typeof messageOrOpts === 'string'
      ? { message: messageOrOpts }
      : (messageOrOpts && typeof messageOrOpts === 'object' ? messageOrOpts : {});
    if (extra && typeof extra === 'object') {
      Object.keys(extra).forEach(function (k) {
        if (opts[k] == null) opts[k] = extra[k];
      });
    }
    opts.message = opts.message == null ? '' : String(opts.message);
    return opts;
  }

  function looksDanger(opts, elt) {
    if (opts.danger) return true;
    if (elt && elt.hasAttribute && elt.hasAttribute('data-confirm-danger') && elt.getAttribute('data-confirm-danger') !== '0') {
      return true;
    }
    return /delete|permanently|cannot be undone/i.test(opts.message || '');
  }

  function bindOnce(n) {
    if (bound || !n.dialog) return;
    bound = true;
    n.cancelBtn.addEventListener('click', function () {
      settle(false);
    });
    n.okBtn.addEventListener('click', function () {
      settle(true);
    });
    n.okDangerBtn.addEventListener('click', function () {
      settle(true);
    });
    n.dialog.addEventListener('cancel', function (e) {
      e.preventDefault();
      settle(active && active.kind === 'alert' ? true : false);
    });
    n.dialog.addEventListener('click', function (e) {
      if (e.target === n.dialog) settle(active && active.kind === 'alert' ? true : false);
    });
  }

  function settle(result) {
    if (!active) return;
    var job = active;
    active = null;
    var n = nodes();
    if (n.dialog && n.dialog.open) {
      try { n.dialog.close(); } catch (err) { /* ignore */ }
    }
    job.resolve(job.kind === 'alert' ? undefined : !!result);
    pump();
  }

  function render(job) {
    var n = nodes();
    bindOnce(n);
    if (!n.dialog) {
      job.resolve(job.kind === 'confirm' ? false : undefined);
      pump();
      return;
    }
    var opts = job.opts;
    var danger = looksDanger(opts, opts.elt);
    var title = (opts.title || '').trim();
    if (title) {
      n.titleEl.textContent = title;
      n.titleEl.classList.remove('hidden');
    } else {
      n.titleEl.textContent = job.kind === 'confirm' ? 'Please confirm' : 'Notice';
      n.titleEl.classList.remove('hidden');
    }
    n.messageEl.textContent = opts.message;
    n.messageEl.classList.toggle('mt-1', !!n.titleEl.textContent);

    var isAlert = job.kind === 'alert';
    n.cancelBtn.classList.toggle('hidden', isAlert);
    n.cancelBtn.textContent = opts.cancelLabel || 'Cancel';

    var okLabel = opts.confirmLabel || (isAlert ? 'OK' : (danger ? 'Delete' : 'Confirm'));
    n.okBtn.textContent = okLabel;
    n.okDangerBtn.textContent = okLabel;
    n.okBtn.classList.toggle('hidden', !isAlert && danger);
    n.okDangerBtn.classList.toggle('hidden', isAlert || !danger);

    n.dialog.showModal();
    var focusBtn = isAlert ? n.okBtn : (danger ? n.cancelBtn : n.okBtn);
    window.setTimeout(function () {
      if (focusBtn && !focusBtn.classList.contains('hidden')) focusBtn.focus();
    }, 0);
  }

  function pump() {
    if (active || !queue.length) return;
    active = queue.shift();
    render(active);
  }

  function enqueue(kind, opts) {
    return new Promise(function (resolve) {
      queue.push({ kind: kind, opts: opts, resolve: resolve });
      pump();
    });
  }

  window.appConfirm = function (messageOrOpts, extra) {
    return enqueue('confirm', normalize(messageOrOpts, extra));
  };

  window.appAlert = function (messageOrOpts, extra) {
    return enqueue('alert', normalize(messageOrOpts, extra));
  };

  document.addEventListener(
    'htmx:confirm',
    function (evt) {
      var question = evt.detail && evt.detail.question;
      if (!question) return;
      evt.preventDefault();
      var elt = evt.detail.elt;
      var issue = evt.detail.issueRequest;
      var danger = looksDanger({ message: question, danger: false }, elt)
        || /cancel this scheduled/i.test(question);
      var title = 'Please confirm';
      var confirmLabel = 'Confirm';
      if (/permanently delete/i.test(question)) {
        title = 'Delete lead?';
        confirmLabel = 'Delete';
      } else if (/delete this/i.test(question)) {
        title = 'Please confirm';
        confirmLabel = 'Delete';
      } else if (/cancel this scheduled/i.test(question)) {
        title = 'Cancel batch?';
        confirmLabel = 'Cancel batch';
      }
      window.appConfirm({
        title: title,
        message: question,
        confirmLabel: confirmLabel,
        danger: danger,
        elt: elt,
      }).then(function (ok) {
        if (ok && typeof issue === 'function') issue(true);
      });
    },
    true
  );

  document.addEventListener(
    'submit',
    function (e) {
      var form = e.target;
      if (!form || form.nodeName !== 'FORM') return;
      var msg = form.getAttribute('data-app-confirm');
      if (!msg) return;
      if (form.getAttribute('data-app-confirm-ok') === '1') {
        form.removeAttribute('data-app-confirm-ok');
        return;
      }
      e.preventDefault();
      e.stopPropagation();
      window.appConfirm({
        title: form.getAttribute('data-app-confirm-title') || 'Please confirm',
        message: msg,
        confirmLabel: form.getAttribute('data-app-confirm-ok-label') || 'Delete',
        danger: form.getAttribute('data-app-confirm-danger') !== '0',
      }).then(function (ok) {
        if (!ok) return;
        form.setAttribute('data-app-confirm-ok', '1');
        if (typeof form.requestSubmit === 'function') form.requestSubmit();
        else form.submit();
      });
    },
    true
  );
})();
