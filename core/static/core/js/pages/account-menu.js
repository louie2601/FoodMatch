(function () {
  document.querySelectorAll('[data-account-menu]').forEach(function (menu) {
    var toggle = menu.querySelector('[data-account-menu-toggle]');
    var panel = menu.querySelector('[data-account-menu-panel]');
    var chevron = menu.querySelector('[data-account-menu-chevron]');
    if (!toggle || !panel) return;

    function setOpen(open) {
      panel.classList.toggle('hidden', !open);
      toggle.setAttribute('aria-expanded', open ? 'true' : 'false');
      if (chevron) chevron.classList.toggle('rotate-180', open);
    }

    toggle.addEventListener('click', function (e) {
      e.stopPropagation();
      setOpen(panel.classList.contains('hidden'));
    });
    document.addEventListener('click', function (e) {
      if (!menu.contains(e.target)) setOpen(false);
    });
    document.addEventListener('keydown', function (e) {
      if (e.key === 'Escape') setOpen(false);
    });
  });
})();
