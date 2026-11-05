(function (cfg) {
  (function () {
    document.body.style.overflow = 'hidden';
    document.addEventListener('keydown', function (e) {
      if (e.key === 'Escape' && document.querySelector('[data-edit-user-modal]')) {
        window.location.href = cfg.manageUsersUrl;
      }
    });
    var firstError = document.querySelector('[data-edit-user-modal] [data-field-error] input, [data-edit-user-modal] [data-field-error] select');
    var first = firstError || document.querySelector('[data-edit-user-modal] input:not([type="hidden"])');
    if (first) first.focus();
  })();
})((document.currentScript && document.currentScript.dataset) || {});
