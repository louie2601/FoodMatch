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

  document.querySelectorAll('[data-module-form]').forEach(function (form) {
    var boxes = form.querySelectorAll('input[name="modules"]');
    var repo = form.querySelector('[data-module="research_repository"]');
    var addResearch = form.querySelector('[data-module="add_research"]');
    if (repo && addResearch) {
      addResearch.addEventListener('change', function () {
        if (addResearch.checked) repo.checked = true;
      });
      repo.addEventListener('change', function () {
        if (!repo.checked) addResearch.checked = false;
      });
    }
    form.querySelector('[data-select-all]').addEventListener('click', function () {
      boxes.forEach(function (box) { box.checked = true; });
    });
    form.querySelector('[data-clear-all]').addEventListener('click', function () {
      boxes.forEach(function (box) { box.checked = false; });
    });
  });
})();
