(function () {
  var modal = document.querySelector('[data-delete-confirm-modal]');
  if (!modal) return;

  var stepForms = {
    1: modal.querySelector('[data-delete-confirm-step="1"]'),
    2: modal.querySelector('[data-delete-confirm-step="2"]')
  };
  var chips = {
    1: modal.querySelector('[data-delete-confirm-stepchip="1"]'),
    2: modal.querySelector('[data-delete-confirm-stepchip="2"]')
  };
  var reasonInput = modal.querySelector('[data-delete-confirm-reason]');
  var reasonError = modal.querySelector('[data-delete-confirm-reason-error]');
  var reasonLabel = modal.querySelector('[data-delete-confirm-reason-label]');
  var passwordInput = modal.querySelector('[data-delete-confirm-password]');
  var passwordError = modal.querySelector('[data-delete-confirm-password-error]');
  var submitBtn = modal.querySelector('[data-delete-confirm-submit]');
  var targetEl = modal.querySelector('[data-delete-confirm-target]');
  var verbEl = modal.querySelector('[data-delete-confirm-verb]');
  var eyebrowEl = modal.querySelector('[data-delete-confirm-eyebrow]');
  var descEl = modal.querySelector('[data-delete-confirm-desc]');
  var stepsEl = modal.querySelector('[data-delete-confirm-steps]');
  var backBtn = modal.querySelector('[data-delete-confirm-back]');
  var requestBox = modal.querySelector('[data-delete-confirm-request-box]');
  var requestReasonEl = modal.querySelector('[data-delete-confirm-request-reason]');
  var requestedByEl = modal.querySelector('[data-delete-confirm-requested-by]');
  var targetForm = null;
  var busyLabel = 'Deleting...';
  var needsReason = true;

  var DELETE_DESC = 'This cannot be undone. The account and its profile are removed permanently.';
  var DANGER_BTN = 'inline-flex items-center justify-center rounded-xl bg-gradient-to-r from-rose-600 via-red-600 to-orange-600 px-5 py-2.5 text-sm font-semibold text-white shadow-md shadow-rose-200 transition hover:-translate-y-0.5';
  var NEUTRAL_BTN = 'inline-flex items-center justify-center rounded-xl bg-slate-900 px-5 py-2.5 text-sm font-semibold text-white shadow-sm transition hover:bg-slate-800';
  var MODES = {
    delete: { eyebrow: 'Permanently Delete Account', verb: 'Delete', desc: DELETE_DESC, label: 'Reason for deleting this account ', placeholder: 'e.g. Duplicate account created by mistake.', submit: 'Delete permanently', busy: 'Deleting...', btn: DANGER_BTN },
    approve: { eyebrow: 'Approve Deletion Request', verb: 'Approve deletion of', desc: DELETE_DESC, passwordOnly: true, submit: 'Approve and delete', busy: 'Deleting...', btn: DANGER_BTN },
    reject: { eyebrow: 'Reject Deletion Request', verb: 'Reject deletion of', desc: 'The account is kept. The Admin who asked is notified.', passwordOnly: true, submit: 'Reject request', busy: 'Rejecting...', btn: NEUTRAL_BTN }
  };

  var CHIP_ON = 'inline-flex items-center gap-1.5 rounded-full bg-rose-50 px-2.5 py-1 text-rose-700 ring-1 ring-rose-100';
  var CHIP_OFF = 'inline-flex items-center gap-1.5 rounded-full bg-slate-50 px-2.5 py-1 text-slate-500 ring-1 ring-slate-200';
  var DOT_ON = 'flex h-4 w-4 items-center justify-center rounded-full bg-rose-600 text-[10px] text-white';
  var DOT_OFF = 'flex h-4 w-4 items-center justify-center rounded-full bg-slate-300 text-[10px] text-white';

  function showStep(step) {
    [1, 2].forEach(function (n) {
      stepForms[n].classList.toggle('hidden', n !== step);
      chips[n].className = n <= step ? CHIP_ON : CHIP_OFF;
      chips[n].firstElementChild.className = n <= step ? DOT_ON : DOT_OFF;
    });
    (step === 1 ? reasonInput : passwordInput).focus({ preventScroll: true });
  }

  function open(form, targetName, mode, requestReason, requestedBy) {
    targetForm = form;
    var m = MODES[mode] || MODES.delete;
    needsReason = !m.passwordOnly;
    targetEl.textContent = targetName || 'this account';
    verbEl.textContent = m.verb;
    eyebrowEl.textContent = m.eyebrow;
    descEl.textContent = m.desc;
    if (needsReason) {
      reasonLabel.firstChild.textContent = m.label;
      reasonInput.placeholder = m.placeholder;
    }
    stepsEl.classList.toggle('hidden', !needsReason);
    backBtn.classList.toggle('invisible', !needsReason);
    requestBox.classList.toggle('hidden', needsReason || !requestReason);
    requestReasonEl.textContent = requestReason || '';
    requestedByEl.textContent = requestedBy || 'the Admin';
    reasonInput.value = '';
    passwordInput.value = '';
    reasonError.classList.add('hidden');
    passwordError.classList.add('hidden');
    submitBtn.disabled = false;
    submitBtn.className = m.btn;
    submitBtn.textContent = m.submit;
    busyLabel = m.busy;
    modal.classList.remove('hidden');
    modal.classList.add('flex');
    document.body.style.overflow = 'hidden';
    showStep(needsReason ? 1 : 2);
  }

  function close() {
    targetForm = null;
    passwordInput.value = '';
    modal.classList.add('hidden');
    modal.classList.remove('flex');
    document.body.style.overflow = '';
  }

  function setHidden(form, name, value) {
    var input = form.querySelector('input[name="' + name + '"]');
    if (!input) {
      input = document.createElement('input');
      input.type = 'hidden';
      input.name = name;
      form.appendChild(input);
    }
    input.value = value;
  }

  document.addEventListener('click', function (e) {
    var trigger = e.target.closest('[data-delete-confirm]');
    if (trigger) {
      e.preventDefault();
      var selector = trigger.getAttribute('data-delete-confirm-form');
      var form = selector ? document.querySelector(selector) : trigger.closest('form');
      var name = trigger.getAttribute('data-target-name') || (form && form.getAttribute('data-user-name')) || '';
      if (form) {
        open(form, name, trigger.getAttribute('data-mode'),
          trigger.getAttribute('data-request-reason'), trigger.getAttribute('data-requested-by'));
      }
      return;
    }
    if (e.target.closest('[data-delete-confirm-close]') && !modal.classList.contains('hidden')) {
      close();
    }
  });

  modal.querySelector('[data-delete-confirm-back]').addEventListener('click', function () { showStep(1); });

  stepForms[1].addEventListener('submit', function (e) {
    e.preventDefault();
    var ok = reasonInput.value.trim().length > 0;
    reasonError.classList.toggle('hidden', ok);
    if (ok) showStep(2);
    else reasonInput.focus();
  });

  stepForms[2].addEventListener('submit', function (e) {
    e.preventDefault();
    if (!targetForm) return;
    var ok = passwordInput.value.length > 0;
    passwordError.classList.toggle('hidden', ok);
    if (!ok) { passwordInput.focus(); return; }
    if (needsReason) setHidden(targetForm, 'deletion_reason', reasonInput.value.trim());
    setHidden(targetForm, 'confirm_password', passwordInput.value);
    submitBtn.disabled = true;
    submitBtn.textContent = busyLabel;
    targetForm.submit();
  });

  document.addEventListener('keydown', function (e) {
    if (e.key === 'Escape' && !modal.classList.contains('hidden')) close();
  });
})();
