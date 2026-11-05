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

  var summary = document.querySelector('[data-form-error-summary]');
  if (summary) summary.scrollIntoView({ block: 'center' });

  // Catch bad images before submitting: a server round-trip would make the
  // browser forget the chosen files.
  var MAX_BYTES = 5 * 1024 * 1024;
  document.querySelectorAll('input[type="file"][accept]').forEach(function (input) {
    var box = document.createElement('div');
    box.className = 'mt-3 hidden';
    input.insertAdjacentElement('afterend', box);
    var urls = [];

    input.addEventListener('change', function () {
      urls.forEach(function (u) { URL.revokeObjectURL(u); });
      urls = [];
      box.innerHTML = '';
      input.setCustomValidity('');
      var files = Array.prototype.slice.call(input.files || []);
      if (!files.length) { box.classList.add('hidden'); return; }

      var problems = [];
      files.forEach(function (file) {
        if (!/\.(jpe?g|png|webp)$/i.test(file.name)) problems.push(file.name + ': only JPG, PNG, or WebP images are allowed.');
        else if (file.size > MAX_BYTES) problems.push(file.name + ': larger than 5 MB.');
      });

      box.classList.remove('hidden');
      if (problems.length) {
        input.setCustomValidity(problems.join(' '));
        input.reportValidity();
        problems.forEach(function (text) {
          var p = document.createElement('p');
          p.className = 'text-xs font-semibold text-rose-600';
          p.textContent = text;
          box.appendChild(p);
        });
        return;
      }

      var grid = document.createElement('div');
      grid.className = 'flex flex-wrap gap-2';
      files.forEach(function (file) {
        var img = document.createElement('img');
        var url = URL.createObjectURL(file);
        urls.push(url);
        img.src = url;
        img.alt = file.name;
        img.className = 'h-16 w-24 rounded-lg object-cover ring-2 ring-emerald-200';
        img.onerror = function () {
          var text = file.name + " can't be read as an image. If it's an iPhone (HEIC) photo, save it as JPG first.";
          input.setCustomValidity(text);
          img.className = 'hidden';
          note.className = 'mt-2 text-xs font-semibold text-rose-600';
          note.textContent = text;
        };
        grid.appendChild(img);
      });
      var note = document.createElement('p');
      note.className = 'mt-2 text-xs font-semibold text-emerald-700';
      note.textContent = files.length === 1 ? files[0].name + ' — ready to save' : files.length + ' images ready to save';
      box.appendChild(grid);
      box.appendChild(note);
    });
  });
})();

document.querySelectorAll('form[data-confirm]').forEach(function (form) {
  form.addEventListener('submit', function (e) {
    if (!window.confirm(form.getAttribute('data-confirm'))) e.preventDefault();
  });
});
