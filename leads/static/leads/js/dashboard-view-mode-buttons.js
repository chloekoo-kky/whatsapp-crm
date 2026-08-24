(function () {
  var grid = document.documentElement.classList.contains('cv-grid');
  document.querySelectorAll('.view-mode-btn').forEach(function (btn) {
    var mode = btn.getAttribute('data-view-mode') || '';
    var active = (mode === 'grid') === grid;
    btn.setAttribute('aria-pressed', active ? 'true' : 'false');
    btn.classList.toggle('bg-white', active);
    btn.classList.toggle('text-indigo-700', active);
    btn.classList.toggle('shadow-sm', active);
    btn.classList.toggle('ring-1', active);
    btn.classList.toggle('ring-slate-200/80', active);
    btn.classList.toggle('text-slate-600', !active);
  });
})();
