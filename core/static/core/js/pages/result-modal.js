(function () {
  var modal = document.querySelector('[data-result-modal]');
  if (!modal) return;
  function close() { modal.remove(); document.removeEventListener('keydown', onKey); }
  function onKey(e) { if (e.key === 'Escape' || e.key === 'Enter') close(); }
  modal.querySelectorAll('[data-close-result-modal]').forEach(function (el) { el.addEventListener('click', close); });
  document.addEventListener('keydown', onKey);
  var ok = modal.querySelector('button[data-close-result-modal]');
  if (ok) ok.focus();
})();
