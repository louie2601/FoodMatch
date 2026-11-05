(function (cfg) {
  (function () {
    var modal = document.querySelector('[data-submit-research-modal]');
    if (!modal) return;

    // ---------------- ADD CATEGORY ----------------
    var categorySelect = document.getElementById('id_category');
    var openAddCategoryBtn = document.getElementById('openAddCategoryBtn');
    var addCategoryRow = document.getElementById('addCategoryRow');
    var newCategoryInput = document.getElementById('newCategoryInput');
    var saveNewCategoryBtn = document.getElementById('saveNewCategoryBtn');
    var cancelNewCategoryBtn = document.getElementById('cancelNewCategoryBtn');
    var newCategoryError = document.getElementById('newCategoryError');

    function readCsrfCookie() {
      var match = document.cookie.match(new RegExp('(^| )csrftoken=([^;]+)'));
      return match ? decodeURIComponent(match[2]) : '';
    }

    if (openAddCategoryBtn && addCategoryRow) {
      openAddCategoryBtn.addEventListener('click', function () {
        addCategoryRow.classList.remove('hidden');
        addCategoryRow.classList.add('flex');
        if (newCategoryInput) newCategoryInput.focus({ preventScroll: true });
      });
    }
    if (cancelNewCategoryBtn && addCategoryRow) {
      cancelNewCategoryBtn.addEventListener('click', function () {
        addCategoryRow.classList.add('hidden');
        addCategoryRow.classList.remove('flex');
        if (newCategoryInput) newCategoryInput.value = '';
        if (newCategoryError) newCategoryError.classList.add('hidden');
      });
    }

    function saveNewCategory() {
      if (!newCategoryInput) return;
      var name = (newCategoryInput.value || '').trim();
      if (newCategoryError) newCategoryError.classList.add('hidden');
      if (!name) return;
      if (window.FieldRules && !FieldRules.validate(newCategoryInput)) return;
      fetch(cfg.addCategoryUrl, {
        method: 'POST',
        headers: { 'X-CSRFToken': readCsrfCookie(), 'Content-Type': 'application/x-www-form-urlencoded' },
        credentials: 'same-origin',
        body: 'name=' + encodeURIComponent(name),
      })
        .then(function (res) { return res.json().then(function (data) { return { ok: res.ok, data: data }; }); })
        .then(function (result) {
          if (!result.ok) {
            if (newCategoryError) {
              newCategoryError.textContent = (result.data && result.data.error) || 'Could not add this category.';
              newCategoryError.classList.remove('hidden');
            }
            return;
          }
          if (categorySelect) {
            var existingOption = null;
            for (var i = 0; i < categorySelect.options.length; i++) {
              if (categorySelect.options[i].value === String(result.data.id)) { existingOption = categorySelect.options[i]; break; }
            }
            if (!existingOption) {
              var opt = document.createElement('option');
              opt.value = String(result.data.id);
              opt.textContent = result.data.name;
              categorySelect.appendChild(opt);
            }
            categorySelect.value = String(result.data.id);
          }
          newCategoryInput.value = '';
          if (addCategoryRow) {
            addCategoryRow.classList.add('hidden');
            addCategoryRow.classList.remove('flex');
          }
        })
        .catch(function () {
          if (newCategoryError) {
            newCategoryError.textContent = 'Could not add this category. Please try again.';
            newCategoryError.classList.remove('hidden');
          }
        });
    }

    if (saveNewCategoryBtn) saveNewCategoryBtn.addEventListener('click', saveNewCategory);
    if (newCategoryInput) {
      newCategoryInput.addEventListener('keydown', function (e) {
        if (e.key === 'Enter') { e.preventDefault(); saveNewCategory(); }
      });
    }

    // ---------------- KEYWORDS CHIPS (auto-generated from Title) ----------------
    var keywordsChipsWrap = document.getElementById('keywordsChipsWrap');
    var keywordEntryInput = document.getElementById('keywordEntryInput');
    var addKeywordBtn = document.getElementById('addKeywordBtn');
    var keywordsInput = document.getElementById('id_keywords');
    var keywordsArr = [];
    if (keywordsInput && keywordsInput.value) {
      keywordsArr = keywordsInput.value.split(',').map(function (s) { return s.trim(); }).filter(Boolean);
    }

    var KEYWORD_STOPWORDS = ['the', 'of', 'and', 'a', 'an', 'in', 'on', 'for', 'with', 'as', 'to', 'from',
      'by', 'is', 'are', 'at', 'using', 'its', 'their', 'this', 'that', 'into', 'towards', 'toward'];

    function deriveKeywordsFromTitle(title) {
      if (!title) return [];
      // Keywords are letters and "-" only, so numbers and symbols split words.
      var words = title.toLowerCase().split(/[^\p{L}-]+/u)
        .map(function (w) { return w.replace(/^-+|-+$/g, ''); })
        .filter(Boolean);
      var seen = {};
      var derived = [];
      words.forEach(function (w) {
        if (w.length < 3 || KEYWORD_STOPWORDS.indexOf(w) !== -1 || seen[w]) return;
        seen[w] = true;
        derived.push(w);
      });
      return derived.slice(0, 8);
    }

    function writeKeywordsInput() {
      if (keywordsInput) keywordsInput.value = keywordsArr.join(', ');
    }

    function renderKeywords() {
      if (!keywordsChipsWrap) return;
      keywordsChipsWrap.innerHTML = '';
      keywordsArr.forEach(function (kw, idx) {
        var chip = document.createElement('span');
        chip.className = 'mr-1.5 mb-1 inline-flex items-center gap-1.5 rounded-full bg-gradient-to-r from-sky-50 to-blue-50 px-3 py-1.5 text-xs font-bold text-sky-800 ring-1 ring-sky-200';
        var label = document.createElement('span');
        label.textContent = kw;
        chip.appendChild(label);
        var removeBtn = document.createElement('button');
        removeBtn.type = 'button';
        removeBtn.className = 'inline-flex h-5 w-5 items-center justify-center rounded-full bg-white/70 text-sky-600 transition hover:bg-white hover:text-rose-600';
        removeBtn.setAttribute('aria-label', 'Remove ' + kw);
        removeBtn.innerHTML = '<svg class="h-3.5 w-3.5" fill="none" stroke="currentColor" stroke-linecap="round" stroke-linejoin="round" stroke-width="2" viewBox="0 0 24 24"><path d="M18 6 6 18"></path><path d="m6 6 12 12"></path></svg>';
        removeBtn.addEventListener('click', function () {
          keywordsArr.splice(idx, 1);
          writeKeywordsInput();
          renderKeywords();
        });
        chip.appendChild(removeBtn);
        keywordsChipsWrap.appendChild(chip);
      });
    }

    function addKeywordFromInput() {
      if (!keywordEntryInput) return;
      var value = (keywordEntryInput.value || '').trim().toLowerCase();
      if (!value) return;
      if (window.FieldRules) {
        if (!FieldRules.validate(keywordEntryInput)) return;
        value = FieldRules.normalize(value);
      }
      if (keywordsArr.indexOf(value) === -1) {
        keywordsArr.push(value);
        writeKeywordsInput();
        renderKeywords();
      }
      keywordEntryInput.value = '';
      keywordEntryInput.focus({ preventScroll: true });
    }

    if (addKeywordBtn) addKeywordBtn.addEventListener('click', addKeywordFromInput);
    if (keywordEntryInput) {
      keywordEntryInput.addEventListener('keydown', function (e) {
        if (e.key === 'Enter') {
          e.preventDefault();
          addKeywordFromInput();
        } else if (e.key === 'Backspace' && !keywordEntryInput.value && keywordsArr.length) {
          e.preventDefault();
          keywordsArr.pop();
          writeKeywordsInput();
          renderKeywords();
        }
      });
    }
    writeKeywordsInput();
    renderKeywords();

    // ---------------- AUTO-EXTRACT FROM UPLOADED FILE ----------------
    var documentInput = document.getElementById('id_document');
    var extractStatusBanner = document.getElementById('extractStatusBanner');
    var extractStatusText = document.getElementById('extractStatusText');
    var titleInput = document.getElementById('id_title');
    var adviserInput = document.getElementById('id_adviser');
    var abstractInput = document.getElementById('id_abstract');
    var publishedMonthSelect = document.getElementById('id_published_month');
    var publishedYearInput = document.getElementById('id_published_year');

    if (titleInput) {
      titleInput.addEventListener('blur', function () {
        if (keywordsArr.length === 0 && titleInput.value.trim()) {
          deriveKeywordsFromTitle(titleInput.value.trim()).forEach(function (kw) {
            if (keywordsArr.indexOf(kw) === -1) keywordsArr.push(kw);
          });
          writeKeywordsInput();
          renderKeywords();
        }
      });
    }

    function readCsrfCookieForExtract() {
      var match = document.cookie.match(new RegExp('(^| )csrftoken=([^;]+)'));
      return match ? decodeURIComponent(match[2]) : '';
    }

    function setExtractStatus(kind, message) {
      if (!extractStatusBanner || !extractStatusText) return;
      extractStatusBanner.classList.remove(
        'hidden', 'border-slate-200', 'bg-slate-50', 'text-slate-700',
        'border-emerald-200', 'bg-emerald-50', 'text-emerald-900',
        'border-rose-200', 'bg-rose-50', 'text-rose-700'
      );
      if (kind === 'loading') {
        extractStatusBanner.classList.add('border-slate-200', 'bg-slate-50', 'text-slate-700');
      } else if (kind === 'success') {
        extractStatusBanner.classList.add('border-emerald-200', 'bg-emerald-50', 'text-emerald-900');
      } else {
        extractStatusBanner.classList.add('border-rose-200', 'bg-rose-50', 'text-rose-700');
      }
      extractStatusText.textContent = message;
    }

    if (documentInput) {
      documentInput.addEventListener('change', function () {
        var file = documentInput.files && documentInput.files[0];
        if (!file) return;
        setExtractStatus('loading', 'Analyzing your file…');
        var fd = new FormData();
        fd.append('document', file);
        fetch(cfg.extractUrl, {
          method: 'POST',
          body: fd,
          headers: { 'X-CSRFToken': readCsrfCookieForExtract() },
          credentials: 'same-origin',
        })
          .then(function (res) {
            return res.json().then(function (data) { return { ok: res.ok, data: data }; });
          })
          .then(function (result) {
            if (!result.ok) {
              setExtractStatus('error', (result.data && result.data.error) || 'Could not analyze this file. Please fill in the fields manually.');
              return;
            }
            var data = result.data;
            var filledParts = [];
            if (data.title && titleInput && !titleInput.value.trim()) {
              titleInput.value = data.title;
              filledParts.push('Title');
            }
            if (data.abstract && abstractInput && !abstractInput.value.trim()) {
              abstractInput.value = data.abstract;
              filledParts.push('Abstract');
            }
            if (data.adviser && adviserInput && !adviserInput.value.trim()) {
              adviserInput.value = data.adviser;
              filledParts.push('Adviser');
            }
            if (data.published_month && publishedMonthSelect && !publishedMonthSelect.value) {
              publishedMonthSelect.value = data.published_month;
              filledParts.push('Published Month');
            }
            if (data.published_year && publishedYearInput && !publishedYearInput.value) {
              publishedYearInput.value = data.published_year;
              filledParts.push('Published Year');
            }
            if (data.title && keywordsArr.length === 0) {
              deriveKeywordsFromTitle(data.title).forEach(function (kw) {
                if (keywordsArr.indexOf(kw) === -1) keywordsArr.push(kw);
              });
              writeKeywordsInput();
              renderKeywords();
              if (keywordsArr.length) filledParts.push('Keywords');
            }
            if (filledParts.length) {
              [titleInput, adviserInput, abstractInput].forEach(function (el) {
                if (el && el.value && window.FieldRules) FieldRules.validate(el);
              });
              var tidied = (data.tidied || []).filter(function (part) { return filledParts.indexOf(part) !== -1; });
              setExtractStatus('success', 'Auto-filled from your file: ' + filledParts.join(', ') + '. Please review before saving.' +
                (tidied.length ? ' Numbers and symbols that aren\'t allowed were left out of: ' + tidied.join(', ') + '.' : ''));
            } else {
              setExtractStatus('error', 'Could not confidently read the details from this file. Please fill in the fields manually.');
            }
          })
          .catch(function () {
            setExtractStatus('error', 'Could not analyze this file. Please fill in the fields manually.');
          });
      });
    }

    // ---------------- REQUIRED-FIELD VALIDATION (blocks Submit) ----------------
    var submitResearchForm = document.getElementById('submitResearchForm');
    var submitResearchBtn = document.getElementById('submitResearchBtn');

    function toggleClientError(fieldEl, errorEl, isInvalid) {
      if (errorEl) errorEl.classList.toggle('hidden', !isInvalid);
      if (fieldEl) {
        fieldEl.classList.toggle('border-rose-400', isInvalid);
        fieldEl.classList.toggle('ring-4', isInvalid);
        fieldEl.classList.toggle('ring-rose-100', isInvalid);
      }
    }

    function validateSubmitResearchForm() {
      var firstInvalid = null;
      var checks = [
        { field: documentInput, error: document.getElementById('id_document_client_error'), valid: !!(documentInput && documentInput.files && documentInput.files.length) },
        { field: titleInput, error: document.getElementById('id_title_client_error'), valid: !!(titleInput && titleInput.value.trim()) },
        { field: document.getElementById('id_category'), error: document.getElementById('id_category_client_error'), valid: !!(document.getElementById('id_category') && document.getElementById('id_category').value) },
        { field: adviserInput, error: document.getElementById('id_adviser_client_error'), valid: !!(adviserInput && adviserInput.value.trim()) },
        { field: abstractInput, error: document.getElementById('id_abstract_client_error'), valid: !!(abstractInput && abstractInput.value.trim()) },
      ];
      checks.forEach(function (check) {
        toggleClientError(check.field, check.error, !check.valid);
        if (!check.valid && !firstInvalid) firstInvalid = check.field;
      });
      // No numbers or special characters (see core/js/field-rules.js).
      [titleInput, adviserInput, abstractInput].forEach(function (el) {
        if (el && el.value.trim() && window.FieldRules && !FieldRules.validate(el) && !firstInvalid) firstInvalid = el;
      });
      return firstInvalid;
    }

    if (submitResearchForm) {
      submitResearchForm.addEventListener('submit', function (e) {
        var firstInvalid = validateSubmitResearchForm();
        if (firstInvalid) {
          e.preventDefault();
          firstInvalid.focus({ preventScroll: false });
          firstInvalid.scrollIntoView({ behavior: 'smooth', block: 'center' });
        }
      });
    }

    // ---------------- MODAL ----------------
    var openBtn = document.querySelector('[data-open-submit-modal]');
    var backdrops = document.querySelectorAll('[data-submit-modal-backdrop]');
    var closeButtons = document.querySelectorAll('[data-close-submit-modal]');
    var hasErrors = cfg.hasErrors === "1";

    function openModal() {
      modal.classList.remove('hidden');
      modal.classList.add('flex');
      document.body.style.overflow = 'hidden';
      var firstField = modal.querySelector('input, select, textarea, button');
      if (firstField) firstField.focus({ preventScroll: true });
    }

    function closeModal() {
      modal.classList.add('hidden');
      modal.classList.remove('flex');
      document.body.style.overflow = '';
    }

    if (openBtn) {
      openBtn.addEventListener('click', openModal);
    }

    closeButtons.forEach(function (btn) {
      btn.addEventListener('click', closeModal);
    });

    backdrops.forEach(function (bd) {
      bd.addEventListener('click', closeModal);
    });

    document.addEventListener('keydown', function (e) {
      if (e.key === 'Escape' && !modal.classList.contains('hidden')) {
        closeModal();
      }
    });

    if (hasErrors) {
      openModal();
    }
  })();
})((document.currentScript && document.currentScript.dataset) || {});
