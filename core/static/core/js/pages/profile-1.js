(function () {
  var otpForm = document.querySelector('[data-otp-form]');
  if (otpForm) {
    var codeInput = document.getElementById('id_code');
    var codeError = document.getElementById('id_code_error');
    codeInput.addEventListener('input', function () {
      var digits = codeInput.value.replace(/\D/g, '').slice(0, 6);
      if (digits !== codeInput.value) codeInput.value = digits;
      if (digits.length === 6 || digits.length === 0) codeError.classList.add('hidden');
    });
    otpForm.addEventListener('submit', function (e) {
      if (!/^\d{6}$/.test(codeInput.value)) {
        e.preventDefault();
        codeError.textContent = 'Enter the 6-digit code from your email.';
        codeError.classList.remove('hidden');
        codeInput.focus();
      }
    });
  }

  var verifyForm = document.querySelector('[data-change-verify-form]');
  if (verifyForm) {
    var currentInput = document.getElementById('id_current_password');
    var currentError = document.getElementById('id_current_password_error');
    verifyForm.addEventListener('submit', function (e) {
      if (!currentInput.value) {
        e.preventDefault();
        currentError.textContent = 'Current password is required.';
        currentError.classList.remove('hidden');
        currentInput.focus();
      }
    });
  }

  var resendBtn = document.getElementById('resendCodeBtn');
  if (resendBtn) {
    var label = resendBtn.querySelector('[data-resend-label]');
    var wait = parseInt(resendBtn.getAttribute('data-resend-wait') || '0', 10);
    if (wait > 0) {
      var deadline = Date.now() + wait * 1000;
      resendBtn.disabled = true;
      label.textContent = 'Resend code in ' + wait + 's';
      var timer = setInterval(function () {
        var left = Math.max(0, Math.ceil((deadline - Date.now()) / 1000));
        label.textContent = left > 0 ? 'Resend code in ' + left + 's' : 'Resend code';
        if (left <= 0) {
          clearInterval(timer);
          resendBtn.disabled = false;
        }
      }, 250);
    }
  }
})();
