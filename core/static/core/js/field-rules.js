// Character rules for the typed research fields (Submit Research / Add Research).
// Same rules as core/text_rules.py: no numbers or special characters, only the
// marks each field needs. Any input with data-field-rule="<rule>" gets them:
// disallowed keys are ignored while typing, and pasted text is flagged.
(function () {
  var RULES = {
    category: { marks: '-', digits: false },
    keyword: { marks: '-', digits: false },
    name: { marks: '-.,', digits: false },
    title: { marks: '-.,()', digits: false },
    abstract: { marks: '-.,()%', digits: true },
  };
  var LETTER = /\p{L}/u;
  var DIGIT = /\p{Nd}/u;
  var SPACE = /\s/;
  var DASHES = /[‐-―−]/g;
  var INVALID_CLASSES = ['border-rose-400', 'ring-4', 'ring-rose-100'];

  function normalize(value) {
    return String(value || '').normalize('NFC').replace(DASHES, '-');
  }

  function allowedDescription(rule) {
    var spec = RULES[rule];
    return (spec.digits ? 'letters, numbers, spaces' : 'letters, spaces') + ', and ' + spec.marks.split('').join(' ');
  }

  function badChars(value, rule) {
    var spec = RULES[rule];
    var found = [];
    if (!spec) return found;
    Array.from(normalize(value)).forEach(function (ch) {
      var ok = LETTER.test(ch) || SPACE.test(ch) || spec.marks.indexOf(ch) !== -1 || (spec.digits && DIGIT.test(ch));
      if (!ok && found.indexOf(ch) === -1) found.push(ch);
    });
    return found;
  }

  function labelOf(el) {
    return el.getAttribute('data-field-label') || 'This field';
  }

  function messageEl(el) {
    var targetId = el.getAttribute('data-field-rule-error');
    if (targetId) return document.getElementById(targetId);
    if (!el._fieldRuleMsg) {
      var p = document.createElement('p');
      p.className = 'mt-1 hidden text-sm text-rose-600';
      p.setAttribute('aria-live', 'polite');
      el.insertAdjacentElement('afterend', p);
      el._fieldRuleMsg = p;
    }
    return el._fieldRuleMsg;
  }

  function show(el, text) {
    var msg = messageEl(el);
    if (msg) {
      msg.textContent = text;
      msg.classList.toggle('hidden', !text);
    }
    INVALID_CLASSES.forEach(function (cls) { el.classList.toggle(cls, !!text); });
    if (text) el.setAttribute('aria-invalid', 'true');
    else el.removeAttribute('aria-invalid');
  }

  // Shows (or clears) the message for the field's current value; true when fine.
  function validate(el) {
    if (!el) return true;
    var rule = el.getAttribute('data-field-rule');
    var found = badChars(el.value, rule);
    show(el, found.length
      ? labelOf(el) + ' can only use ' + allowedDescription(rule) + '. Please remove: ' + found.slice(0, 10).join(' ')
      : '');
    return found.length === 0;
  }

  function attach(el) {
    if (!el || el._fieldRuleAttached) return;
    el._fieldRuleAttached = true;
    var rule = el.getAttribute('data-field-rule');
    var hideTimer = null;
    el.addEventListener('beforeinput', function (e) {
      // Typed characters that aren't allowed are simply not entered.
      if (e.inputType !== 'insertText' || !e.data) return;
      if (!badChars(e.data, rule).length) return;
      e.preventDefault();
      show(el, labelOf(el) + ' can only use ' + allowedDescription(rule) + '.');
      clearTimeout(hideTimer);
      hideTimer = setTimeout(function () { validate(el); }, 2500);
    });
    el.addEventListener('input', function () {
      clearTimeout(hideTimer);
      validate(el);
    });
  }

  function attachAll(root) {
    (root || document).querySelectorAll('[data-field-rule]').forEach(attach);
  }

  window.FieldRules = { badChars: badChars, validate: validate, attach: attach, attachAll: attachAll, normalize: normalize };
  attachAll(document);
})();
