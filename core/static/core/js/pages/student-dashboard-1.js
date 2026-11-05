(function () {
  var detailsModal = document.getElementById('repoResultDetailsModal');
  if (detailsModal) {
    var detailsAvatar = document.getElementById('repoResultDetailsAvatar');
    var detailsTitle = document.getElementById('repoResultDetailsTitle');
    var detailsAuthors = document.getElementById('repoResultDetailsAuthors');
    var detailsIndexed = document.getElementById('repoResultDetailsIndexed');
    var detailsDocStatus = document.getElementById('repoResultDetailsDocStatus');
    var detailsMine = document.getElementById('repoResultDetailsMine');
    var detailsFileWrap = document.getElementById('repoResultDetailsFileWrap');
    var detailsFileLink = document.getElementById('repoResultDetailsFileLink');
    var detailsFileLinkText = document.getElementById('repoResultDetailsFileLinkText');
    var detailsAbstract = document.getElementById('repoResultDetailsAbstract');
    var detailsAuthorsChips = document.getElementById('repoResultDetailsAuthorsChips');
    var detailsAdviser = document.getElementById('repoResultDetailsAdviser');
    var detailsKeywords = document.getElementById('repoResultDetailsKeywords');
    var detailsCategory = document.getElementById('repoResultDetailsCategory');
    var detailsPublished = document.getElementById('repoResultDetailsPublished');
    var detailsPublishedMonth = document.getElementById('repoResultDetailsPublishedMonth');
    var detailsPublishedYear = document.getElementById('repoResultDetailsPublishedYear');
    var detailsSchoolYear = document.getElementById('repoResultDetailsSchoolYear');
    var detailsAdded = document.getElementById('repoResultDetailsAdded');

    function dash(value) {
      var trimmed = (value || '').trim();
      return trimmed || '—';
    }

    function renderChipString(targetEl, raw, placeholderLabel) {
      var str = (raw || '').trim();
      if (!str) {
        targetEl.innerHTML = '<span class="inline-flex items-center rounded-full bg-slate-100 px-2.5 py-1 text-xs font-medium text-slate-600 ring-1 ring-slate-200">' + placeholderLabel + '</span>';
        return;
      }
      var pieces = str.split(',').map(function (s) { return s.trim(); }).filter(Boolean);
      if (!pieces.length) {
        targetEl.textContent = str;
        return;
      }
      targetEl.innerHTML = pieces.map(function (p) {
        return '<span class="mr-1.5 mb-1 inline-flex items-center rounded-full bg-slate-100 px-2.5 py-1 text-xs font-medium text-slate-700 ring-1 ring-slate-200">' + p + '</span>';
      }).join('');
    }

    function openDetailsModal(card) {
      var title = card.dataset.title || '';
      var authors = card.dataset.authors || '';
      var pubMonth = (card.dataset.publishedMonth || '').trim();
      var pubYearRaw = (card.dataset.publishedYear || '').trim();
      var pubYear = '';
      if (pubYearRaw) {
        var yNum = parseInt(pubYearRaw, 10);
        if (!Number.isNaN(yNum) && yNum >= 1900 && yNum <= 2199) pubYear = String(yNum);
      }
      var schoolYear = '';
      if (pubYear) {
        var y = parseInt(pubYear, 10);
        var startYear = y, endYear = y + 1;
        if (pubMonth && /^(january|february|march|april|may|june)$/i.test(pubMonth)) {
          startYear = y - 1; endYear = y;
        }
        schoolYear = 'SY ' + startYear + ' - ' + endYear;
      }
      var hasDoc = card.dataset.hasDocument === '1';
      var isMine = card.dataset.isMine === '1';
      var docUrl = isMine ? (card.dataset.documentUrl || '').trim() : '';
      var docType = card.dataset.docType || '';

      if (detailsAvatar) detailsAvatar.textContent = (title || 'R').slice(0, 1).toUpperCase();
      detailsTitle.textContent = dash(title);
      detailsAuthors.textContent = dash(authors);
      renderChipString(detailsAuthorsChips, authors, 'No authors listed');
      detailsAdviser.textContent = dash(card.dataset.adviser);
      detailsAbstract.textContent = (card.dataset.abstract || '').trim() || 'No abstract available.';
      detailsKeywords.textContent = dash(card.dataset.keywords);
      detailsCategory.textContent = dash(card.dataset.category);
      detailsPublished.textContent = dash(card.dataset.published);
      detailsPublishedMonth.textContent = dash(pubMonth);
      detailsPublishedYear.textContent = dash(pubYear);
      detailsSchoolYear.textContent = dash(schoolYear);
      detailsAdded.textContent = dash(card.dataset.added);
      detailsMine.classList.toggle('hidden', !isMine);

      detailsIndexed.innerHTML = hasDoc
        ? '<span class="inline-flex items-center rounded-full bg-emerald-50 px-2.5 py-1 text-xs font-bold text-emerald-800 ring-1 ring-emerald-200"><span class="mr-1.5 inline-block h-1.5 w-1.5 rounded-full bg-emerald-500"></span>Full-text similarity</span>'
        : '<span class="inline-flex items-center rounded-full bg-amber-50 px-2.5 py-1 text-xs font-bold text-amber-800 ring-1 ring-amber-200"><span class="mr-1.5 inline-block h-1.5 w-1.5 rounded-full bg-amber-500"></span>Metadata-only</span>';
      detailsDocStatus.textContent = hasDoc ? (docType || 'Document available') : 'No document attached';

      // metadata-only: this link only ever appears when docUrl is non-empty,
      // which only happens for the viewer's own entry (see data-document-url
      // on the card / views.py) -- never for another student's file.
      if (docUrl) {
        detailsFileLink.setAttribute('href', docUrl);
        detailsFileLinkText.textContent = docType ? 'Open ' + docType : 'Open Document';
        detailsFileWrap.classList.remove('hidden');
      } else {
        detailsFileLink.setAttribute('href', '#');
        detailsFileWrap.classList.add('hidden');
      }

      detailsModal.classList.remove('hidden');
      detailsModal.classList.add('flex');
      document.body.style.overflow = 'hidden';
    }

    function closeDetailsModal() {
      detailsModal.classList.add('hidden');
      detailsModal.classList.remove('flex');
      document.body.style.overflow = '';
    }

    document.querySelectorAll('[data-view-details-btn]').forEach(function (btn) {
      btn.addEventListener('click', function () {
        var card = btn.closest('[data-result-card]');
        if (card) openDetailsModal(card);
      });
    });

    detailsModal.querySelectorAll('[data-close-repo-details-modal]').forEach(function (el) {
      el.addEventListener('click', closeDetailsModal);
    });

    document.addEventListener('keydown', function (e) {
      if (e.key === 'Escape' && !detailsModal.classList.contains('hidden')) {
        closeDetailsModal();
      }
    });
  }
})();
