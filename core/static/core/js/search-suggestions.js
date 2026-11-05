// Search-bar suggestions (typeahead) for the repository search: the student
// dashboard and the Admin / Super Admin Research Repository. Needs an input
// #q inside a <form>, a #dashboard-search-suggestions-box under it, and the
// suggestion list in #dashboard-search-suggestions-data (json_script).
(function () {
  var searchInput = document.getElementById('q');
  var suggestionsBox = document.getElementById('dashboard-search-suggestions-box');
  var searchForm = searchInput ? searchInput.closest('form') : null;
  var suggestionDataEl = document.getElementById('dashboard-search-suggestions-data');
  var suggestionData = suggestionDataEl ? JSON.parse(suggestionDataEl.textContent) : [];
  if (!searchInput || !suggestionsBox || !searchForm) return;

  function escapeHtml(value) {
    return value
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;')
      .replace(/'/g, '&#39;');
  }

  function hideSuggestions() {
    suggestionsBox.classList.add('hidden');
    suggestionsBox.innerHTML = '';
  }

  function applySuggestion(value) {
    searchInput.value = value;
    hideSuggestions();
    searchForm.submit();
  }

  function renderSuggestions(query) {
    var normalizedQuery = query.trim().toLowerCase();
    if (!normalizedQuery) {
      hideSuggestions();
      return;
    }
    var matches = suggestionData
      .filter(function (item) { return item.toLowerCase().indexOf(normalizedQuery) !== -1; })
      .slice(0, 6);

    if (!matches.length) {
      hideSuggestions();
      return;
    }

    suggestionsBox.innerHTML = matches
      .map(function (item) {
        return '<button type="button" class="dashboard-suggestion-item flex w-full items-center justify-between border-b border-slate-100 px-4 py-3 text-left text-sm text-slate-700 transition hover:bg-emerald-50 hover:text-emerald-700 last:border-b-0" data-value="' + escapeHtml(item) + '"><span>' + escapeHtml(item) + '</span><span class="text-xs font-semibold uppercase tracking-[0.14em] text-slate-400">Suggestion</span></button>';
      })
      .join('');
    suggestionsBox.classList.remove('hidden');

    suggestionsBox.querySelectorAll('.dashboard-suggestion-item').forEach(function (button) {
      button.addEventListener('click', function () { applySuggestion(button.dataset.value); });
    });
  }

  searchInput.addEventListener('input', function (event) {
    renderSuggestions(event.target.value);
  });

  searchInput.addEventListener('focus', function () {
    if (searchInput.value.trim()) renderSuggestions(searchInput.value);
  });

  document.addEventListener('click', function (event) {
    if (!suggestionsBox.contains(event.target) && event.target !== searchInput) {
      hideSuggestions();
    }
  });

  searchForm.addEventListener('submit', hideSuggestions);
})();
