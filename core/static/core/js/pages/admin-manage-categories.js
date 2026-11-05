(function () {
  function wireModal(modalSelector, openSelector, backdropSelector, closeSelector) {
    var modal = document.querySelector(modalSelector);
    if (!modal) return null;
    var openBtns = openSelector ? document.querySelectorAll(openSelector) : [];
    var backdrops = document.querySelectorAll(backdropSelector);
    var closeBtns = document.querySelectorAll(closeSelector);

    function open() {
      modal.classList.remove('hidden');
      modal.classList.add('flex');
      document.body.style.overflow = 'hidden';
      var firstField = modal.querySelector('input, select, button');
      if (firstField) firstField.focus({ preventScroll: true });
    }
    function close() {
      modal.classList.add('hidden');
      modal.classList.remove('flex');
      document.body.style.overflow = '';
    }
    openBtns.forEach(function (btn) { btn.addEventListener('click', open); });
    backdrops.forEach(function (bd) { bd.addEventListener('click', close); });
    closeBtns.forEach(function (btn) { btn.addEventListener('click', close); });
    document.addEventListener('keydown', function (e) {
      if (e.key === 'Escape' && !modal.classList.contains('hidden')) close();
    });
    return { open: open, close: close };
  }

  wireModal('[data-add-category-modal]', '[data-open-add-category-modal]', '[data-add-category-modal-backdrop]', '[data-close-add-category-modal]');
  wireModal('[data-add-subcategory-modal]', '[data-open-add-subcategory-modal]', '[data-add-subcategory-modal-backdrop]', '[data-close-add-subcategory-modal]');
  var deleteModalCtl = wireModal('[data-delete-category-modal]', null, '[data-delete-category-modal-backdrop]', '[data-close-delete-category-modal]');

  var deleteTargetNameEl = document.getElementById('deleteCategoryTargetName');
  var deleteDescEl = document.getElementById('deleteCategoryDesc');
  var confirmDeleteBtn = document.getElementById('confirmDeleteCategoryBtn');
  var pendingDeleteForm = null;

  document.querySelectorAll('[data-trigger-delete-category]').forEach(function (btn) {
    btn.addEventListener('click', function () {
      var form = btn.closest('[data-delete-category-form]');
      if (!form) return;
      pendingDeleteForm = form;
      var name = form.getAttribute('data-category-name') || 'this entry';
      var childCount = parseInt(form.getAttribute('data-child-count') || '0', 10);
      if (deleteTargetNameEl) deleteTargetNameEl.textContent = name;
      if (deleteDescEl) {
        deleteDescEl.textContent = childCount > 0
          ? 'This will also delete its ' + childCount + ' subcategories. This cannot be undone.'
          : 'This cannot be undone.';
      }
      if (deleteModalCtl) deleteModalCtl.open();
    });
  });

  if (confirmDeleteBtn) {
    confirmDeleteBtn.addEventListener('click', function () {
      if (pendingDeleteForm) pendingDeleteForm.submit();
    });
  }
})();

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
