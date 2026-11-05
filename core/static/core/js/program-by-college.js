(function () {
  function init() {
    var dataEl = document.getElementById('programCollegeMap');
    if (!dataEl) return;
    var map;
    try { map = JSON.parse(dataEl.textContent); } catch (e) { return; }
    if (!map || typeof map !== 'object') return;

    document.querySelectorAll('select[name="college"]').forEach(function (collegeSelect) {
      var form = collegeSelect.form;
      var programSelect = form && form.querySelector('select[name="program"]');
      if (!programSelect || programSelect.dataset.followsCollege) return;
      programSelect.dataset.followsCollege = '1';
      var placeholder = programSelect.options.length ? programSelect.options[0].textContent : 'Select Program';

      function render() {
        var college = collegeSelect.value;
        var current = programSelect.value;
        var names = college ? (map[college] || []).concat(map[''] || []) : [];
        programSelect.innerHTML = '';
        var first = document.createElement('option');
        first.value = '';
        first.textContent = college ? placeholder : 'Select a college first';
        programSelect.appendChild(first);
        names.forEach(function (name) {
          var option = document.createElement('option');
          option.value = name;
          option.textContent = name;
          if (name === current) option.selected = true;
          programSelect.appendChild(option);
        });
      }

      collegeSelect.addEventListener('change', render);
      render();
    });
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
})();
