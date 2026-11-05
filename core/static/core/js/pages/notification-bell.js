(function () {
  document.querySelectorAll('[data-notification-menu]').forEach(function (menu) {
    if (menu.dataset.bound) return;
    menu.dataset.bound = '1';
    var toggle = menu.querySelector('[data-notification-toggle]');
    var panel = menu.querySelector('[data-notification-panel]');
    if (!toggle || !panel) return;

    function setOpen(open) {
      panel.classList.toggle('hidden', !open);
      toggle.setAttribute('aria-expanded', open ? 'true' : 'false');
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
