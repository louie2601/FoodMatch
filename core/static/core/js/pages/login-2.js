(function () {
  var notice = document.getElementById('loginLockNotice');
  var form = document.getElementById('loginForm');
  if (!notice || !form) return;

  var seconds = parseInt(notice.getAttribute('data-lock-seconds') || '0', 10);
  if (!(seconds > 0)) return;

  var countdown = document.getElementById('loginLockCountdown');
  var plural = document.getElementById('loginLockPlural');
  var submit = document.getElementById('loginSubmit');
  var label = submit ? submit.querySelector('[data-login-label]') : null;
  var controls = form.querySelectorAll('input:not([type="hidden"]), button[type="submit"]');
  var deadline = Date.now() + seconds * 1000;
  var timer = null;

  function setDisabled(disabled) {
    controls.forEach(function (el) { el.disabled = disabled; });
  }

  function tick() {
    var left = Math.max(0, Math.ceil((deadline - Date.now()) / 1000));
    if (countdown) countdown.textContent = left;
    if (plural) plural.textContent = left === 1 ? '' : 's';
    if (label) label.textContent = left > 0 ? 'Try again in ' + left + 's' : 'Login';
    if (left <= 0) {
      clearInterval(timer);
      notice.classList.add('hidden');
      setDisabled(false);
      var usernameInput = document.getElementById('id_username');
      if (usernameInput) usernameInput.focus();
    }
  }

  setDisabled(true);
  tick();
  timer = setInterval(tick, 250);
})();
