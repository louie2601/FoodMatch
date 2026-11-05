(function () {
  var modal = document.querySelector('[data-deactivate-modal]');
  if (!modal || modal.dataset.bound) return;
  modal.dataset.bound = '1';
  var dialogForm = modal.querySelector('[data-deactivate-modal-form]');
  var reasonInput = modal.querySelector('[data-deactivate-reason]');
  var targetLabel = modal.querySelector('[data-deactivate-target]');
  var pendingForm = null;

  function open(form, name) {
    pendingForm = form;
    targetLabel.textContent = name || 'this account';
    reasonInput.value = '';
    modal.classList.remove('hidden');
    modal.classList.add('flex');
    document.body.style.overflow = 'hidden';
    reasonInput.focus();
  }
  function close() {
    pendingForm = null;
    modal.classList.add('hidden');
    modal.classList.remove('flex');
    document.body.style.overflow = '';
  }

  document.addEventListener('click', function (e) {
    var btn = e.target.closest('[data-needs-deactivation-reason]');
    if (!btn) return;
    e.preventDefault();
    open(btn.closest('form'), btn.getAttribute('data-target-name'));
  });
  modal.querySelectorAll('[data-close-deactivate-modal]').forEach(function (el) { el.addEventListener('click', close); });
  document.addEventListener('keydown', function (e) {
    if (e.key === 'Escape' && !modal.classList.contains('hidden')) close();
  });
  dialogForm.addEventListener('submit', function (e) {
    e.preventDefault();
    var reason = reasonInput.value.trim();
    if (!reason) { reasonInput.focus(); return; }
    if (!pendingForm) return;
    var field = pendingForm.querySelector('input[name="reason"]');
    if (!field) {
      field = document.createElement('input');
      field.type = 'hidden';
      field.name = 'reason';
      pendingForm.appendChild(field);
    }
    field.value = reason;
    var submitBtn = dialogForm.querySelector('button[type="submit"]');
    submitBtn.disabled = true;
    submitBtn.textContent = 'Deactivating…';
    pendingForm.submit();
  });
})();
