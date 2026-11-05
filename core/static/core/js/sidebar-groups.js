(function () {
  document.querySelectorAll('[data-group-toggle]').forEach(function (btn) {
    btn.addEventListener('click', function () {
      var panel = btn.parentElement.querySelector('[data-group-panel]');
      var chevron = btn.querySelector('[data-group-chevron]');
      if (!panel) return;
      panel.classList.toggle('hidden');
      var nowHidden = panel.classList.contains('hidden');
      if (chevron) chevron.classList.toggle('-rotate-90', nowHidden);
    });
  });
})();
