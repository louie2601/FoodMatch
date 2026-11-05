(function () {
  var modal = document.querySelector('[data-deactivated-modal]');
  if (!modal) return;
  function close() { modal.remove(); }
  modal.querySelectorAll('[data-close-deactivated]').forEach(function (el) { el.addEventListener('click', close); });
  document.addEventListener('keydown', function (e) { if (e.key === 'Escape') close(); });
  var ok = modal.querySelector('button[data-close-deactivated]');
  if (ok) ok.focus();
})();
