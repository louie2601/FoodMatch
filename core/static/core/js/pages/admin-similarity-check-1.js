(function () {
  // Same as the student Similarity Check: the full-screen "Analyzing your file…"
  // card (templates/core/_analyzing_overlay.html) plus a disabled button.
  var overlay = document.getElementById('analyzingOverlay');
  var simForm = document.getElementById('adminSimilarityForm');
  var submitBtn = document.getElementById('submitSimilarityBtn');
  var label = submitBtn ? submitBtn.querySelector('[data-check-similarity-label]') : null;
  if (simForm && submitBtn) {
    simForm.addEventListener('submit', function () {
      if (overlay) {
        overlay.classList.remove('hidden');
        overlay.classList.add('flex');
      }
      submitBtn.disabled = true;
      if (label) label.textContent = 'Analyzing...';
    });
  }
})();
