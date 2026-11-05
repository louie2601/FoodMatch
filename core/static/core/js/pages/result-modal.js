(function () {
  var modal = document.querySelector('[data-result-modal]');
  if (!modal) return;
  var primary = modal.querySelector('[data-result-modal-primary]');
  var isError = modal.getAttribute('role') === 'alertdialog';

  function close() {
    modal.remove();
    document.removeEventListener('keydown', onKey);
    if (!isError) return;
    // After an error, take the user to the first problem on the page.
    var problems = document.querySelectorAll('[data-members-error]:not(.hidden), [id$="_error"]:not(.hidden)');
    for (var i = 0; i < problems.length; i++) {
      if (problems[i].textContent.trim() && problems[i].offsetParent !== null) {
        problems[i].scrollIntoView({ behavior: 'smooth', block: 'center' });
        break;
      }
    }
  }

  function onKey(e) {
    if (e.key === 'Escape') {
      close();
    } else if (e.key === 'Enter') {
      e.preventDefault();
      if (primary && primary.tagName === 'A') window.location.href = primary.href;
      else close();
    }
  }

  modal.querySelectorAll('[data-close-result-modal]').forEach(function (el) { el.addEventListener('click', close); });
  document.addEventListener('keydown', onKey);
  if (primary) primary.focus();
})();
