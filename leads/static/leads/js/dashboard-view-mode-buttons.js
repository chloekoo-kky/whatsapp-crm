(function () {
  var grid = document.documentElement.classList.contains('cv-grid');
  document.querySelectorAll('.view-mode-btn').forEach(function (btn) {
    var mode = btn.getAttribute('data-view-mode') || '';
    var active = (mode === 'grid') === grid;
    btn.setAttribute('aria-pressed', active ? 'true' : 'false');
  });
})();
