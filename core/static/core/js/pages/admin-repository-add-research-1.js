(function (cfg) {
  (function () {
    // ---------------- ADD CATEGORY ----------------
    var categorySelect = document.getElementById('id_category');
    var openAddCategoryBtn = document.getElementById('openAddCategoryBtn');
    var addCategoryRow = document.getElementById('addCategoryRow');
    var newCategoryInput = document.getElementById('newCategoryInput');
    var saveNewCategoryBtn = document.getElementById('saveNewCategoryBtn');
    var cancelNewCategoryBtn = document.getElementById('cancelNewCategoryBtn');
    var newCategoryError = document.getElementById('newCategoryError');

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
        headers: { 'X-CSRFToken': readCsrfCookieForExtract(), 'Content-Type': 'application/x-www-form-urlencoded' },
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
        chip.className = 'mr-1.5 mb-1 inline-flex items-center gap-1.5 rounded-full bg-gradient-to-r from-emerald-50 to-green-50 px-3 py-1.5 text-xs font-bold text-emerald-800 ring-1 ring-emerald-200';
        var label = document.createElement('span');
        label.textContent = kw;
        chip.appendChild(label);
        var removeBtn = document.createElement('button');
        removeBtn.type = 'button';
        removeBtn.className = 'inline-flex h-5 w-5 items-center justify-center rounded-full bg-white/70 text-emerald-600 transition hover:bg-white hover:text-rose-600';
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

    // ---------------- AUTHORS CHIPS (ADD MODAL) ----------------
    var authorsChipsWrap = document.getElementById('authorsChipsWrap');
    var authorEntryInput = document.getElementById('authorEntryInput');
    var addAuthorBtn = document.getElementById('addAuthorBtn');
    var authorsJsonInput = document.getElementById('id_authors_json');
    var authorsEmptyHint = document.getElementById('authorsEmptyHint');
    var authorsArr = [];

    function renderAuthors() {
      if (!authorsChipsWrap) return;
      authorsChipsWrap.innerHTML = '';
      authorsArr.forEach(function (name, idx) {
        var chip = document.createElement('span');
        chip.className = 'mr-1.5 mb-1 inline-flex items-center gap-1.5 rounded-full bg-gradient-to-r from-emerald-50 to-green-50 px-3 py-1.5 text-xs font-bold text-emerald-800 ring-1 ring-emerald-200';
        chip.setAttribute('data-author-idx', String(idx));
        var label = document.createElement('span');
        label.textContent = name;
        chip.appendChild(label);
        var removeBtn = document.createElement('button');
        removeBtn.type = 'button';
        removeBtn.className = 'inline-flex h-5 w-5 items-center justify-center rounded-full bg-white/70 text-emerald-600 transition hover:bg-white hover:text-rose-600';
        removeBtn.setAttribute('data-remove-author', String(idx));
        removeBtn.setAttribute('aria-label', 'Remove ' + name);
        removeBtn.innerHTML = '<svg class="h-3.5 w-3.5" fill="none" stroke="currentColor" stroke-linecap="round" stroke-linejoin="round" stroke-width="2" viewBox="0 0 24 24"><path d="M18 6 6 18"></path><path d="m6 6 12 12"></path></svg>';
        removeBtn.addEventListener('click', function () {
          authorsArr.splice(idx, 1);
          writeAuthorsJson();
          renderAuthors();
        });
        chip.appendChild(removeBtn);
        authorsChipsWrap.appendChild(chip);
      });
      if (authorsEmptyHint) {
        if (authorsArr.length === 0) {
          authorsEmptyHint.classList.remove('hidden');
          authorsEmptyHint.classList.remove('text-slate-500');
          authorsEmptyHint.classList.add('text-amber-600');
        } else {
          authorsEmptyHint.classList.add('hidden');
          authorsEmptyHint.classList.remove('text-amber-600');
          authorsEmptyHint.classList.add('text-slate-500');
        }
      }
    }

    function writeAuthorsJson() {
      if (authorsJsonInput) {
        authorsJsonInput.value = JSON.stringify(authorsArr);
      }
    }

    function addAuthorFromInput() {
      if (!authorEntryInput) return;
      var value = (authorEntryInput.value || '').trim();
      if (!value) return;
      if (window.FieldRules) {
        if (!FieldRules.validate(authorEntryInput)) return;
        value = FieldRules.normalize(value);
      }
      if (authorsArr.indexOf(value) === -1) {
        authorsArr.push(value);
        writeAuthorsJson();
        renderAuthors();
      }
      authorEntryInput.value = '';
      authorEntryInput.focus({ preventScroll: true });
    }

    if (addAuthorBtn) {
      addAuthorBtn.addEventListener('click', addAuthorFromInput);
    }
    if (authorEntryInput) {
      authorEntryInput.addEventListener('keydown', function (e) {
        if (e.key === 'Enter') {
          e.preventDefault();
          addAuthorFromInput();
        } else if (e.key === 'Backspace' && !authorEntryInput.value && authorsArr.length) {
          e.preventDefault();
          authorsArr.pop();
          writeAuthorsJson();
          renderAuthors();
        }
      });
    }
    writeAuthorsJson();
    renderAuthors();

    // ---------------- AUTO-EXTRACT FROM UPLOADED FILE (ADD MODAL) ----------------
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
            if (Array.isArray(data.authors) && data.authors.length && authorsArr.length === 0) {
              data.authors.forEach(function (name) {
                if (authorsArr.indexOf(name) === -1) authorsArr.push(name);
              });
              writeAuthorsJson();
              renderAuthors();
              filledParts.push('Authors');
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

    // ---------------- REQUIRED-FIELD VALIDATION (blocks submit) ----------------
    function toggleClientError(fieldEl, errorEl, isInvalid) {
      if (errorEl) errorEl.classList.toggle('hidden', !isInvalid);
      if (fieldEl) {
        fieldEl.classList.toggle('border-rose-400', isInvalid);
        fieldEl.classList.toggle('ring-4', isInvalid);
        fieldEl.classList.toggle('ring-rose-100', isInvalid);
      }
    }

    function validateAddResearchForm() {
      var firstInvalid = null;
      var checks = [
        { field: documentInput, error: document.getElementById('id_document_client_error'), valid: !!(documentInput && documentInput.files && documentInput.files.length) },
        { field: titleInput, error: document.getElementById('id_title_client_error'), valid: !!(titleInput && titleInput.value.trim()) },
        { field: document.getElementById('id_category'), error: document.getElementById('id_category_client_error'), valid: !!(document.getElementById('id_category') && document.getElementById('id_category').value) },
        { field: authorEntryInput, error: authorsEmptyHint, valid: authorsArr.length > 0, isAuthors: true },
        { field: adviserInput, error: document.getElementById('id_adviser_client_error'), valid: !!(adviserInput && adviserInput.value.trim()) },
        { field: abstractInput, error: document.getElementById('id_abstract_client_error'), valid: !!(abstractInput && abstractInput.value.trim()) },
      ];
      checks.forEach(function (check) {
        if (check.isAuthors) {
          if (!check.valid && !firstInvalid) firstInvalid = authorEntryInput;
          return;
        }
        toggleClientError(check.field, check.error, !check.valid);
        if (!check.valid && !firstInvalid) firstInvalid = check.field;
      });
      // No numbers or special characters (see core/js/field-rules.js). A typed
      // author that wasn't added because of them also blocks saving.
      [titleInput, authorEntryInput, adviserInput, abstractInput].forEach(function (el) {
        if (el && el.value.trim() && window.FieldRules && !FieldRules.validate(el) && !firstInvalid) firstInvalid = el;
      });
      return firstInvalid;
    }

    // (hooked into the existing addForm submit handler below, after the
    // CSRF sync and "persist typed author" steps it already does)

    // ---------------- ADD MODAL ----------------
    var addModal = document.querySelector('[data-add-research-modal]');
    if (addModal) {
      var addBackdrops = document.querySelectorAll('[data-add-research-modal-backdrop]');
      var addCloseButtons = document.querySelectorAll('[data-close-add-research-modal]');
      var addOpenButtons = document.querySelectorAll('[data-open-add-research-modal]');
      var submitAddBtn = document.getElementById('submitAddResearchBtn');
      var addForm = document.getElementById('addResearchForm');

      var hasErrors = cfg.hasErrors === "1";

      function openAddModal() {
        addModal.classList.remove('hidden');
        addModal.classList.add('flex');
        document.body.style.overflow = 'hidden';
        if (authorEntryInput) authorEntryInput.focus({ preventScroll: true });
      }

      function closeAddModal() {
        addModal.classList.add('hidden');
        addModal.classList.remove('flex');
        document.body.style.overflow = '';
      }

      addOpenButtons.forEach(function (btn) {
        btn.addEventListener('click', openAddModal);
      });
      addCloseButtons.forEach(function (btn) {
        btn.addEventListener('click', closeAddModal);
      });
      addBackdrops.forEach(function (bd) {
        bd.addEventListener('click', closeAddModal);
      });

      if (addForm) {
        // Defensive helper: read csrf token from browser cookies
        // (csrftoken cookie is set by Django on GET via ensure_csrf_cookie decorator)
        function readCsrfCookie() {
          try {
            var match = document.cookie.match(new RegExp('(^| )csrftoken=([^;]+)'));
            return match ? decodeURIComponent(match[2]) : '';
          } catch (e) {
            return '';
          }
        }

        addForm.addEventListener('submit', function (e) {
          // Guarantee csrf token presence — ALWAYS sync from cookie before submit (fixes empty value)
          try {
            var tokenFromCookie = readCsrfCookie();
            var tokenField = addForm.querySelector('input[name="csrfmiddlewaretoken"]');
            if (tokenField) {
              if (tokenFromCookie) {
                tokenField.value = tokenFromCookie;
              } else if (!tokenField.value) {
                // If cookie missing, fall back to reading from <meta> if any
                var meta = document.querySelector('meta[name="csrf-token"]');
                if (meta && meta.content) tokenField.value = meta.content;
              }
            } else if (tokenFromCookie) {
              var inp = document.createElement('input');
              inp.type = 'hidden';
              inp.name = 'csrfmiddlewaretoken';
              inp.value = tokenFromCookie;
              addForm.appendChild(inp);
            }
          } catch (err) { /* swallow */ }

          // Persist any currently-typed entry (still in input) to chips
          if (authorEntryInput && authorEntryInput.value && authorEntryInput.value.trim()) {
            addAuthorFromInput();
          }
          var firstInvalid = validateAddResearchForm();
          if (firstInvalid) {
            e.preventDefault();
            if (authorsArr.length === 0 && authorsEmptyHint) {
              authorsEmptyHint.textContent = 'Please add at least one author before submitting.';
            }
            firstInvalid.focus({ preventScroll: false });
            firstInvalid.scrollIntoView({ behavior: 'smooth', block: 'center' });
            return;
          }
          if (submitAddBtn) {
            submitAddBtn.disabled = true;
            submitAddBtn.classList.add('opacity-70', 'cursor-not-allowed');
            submitAddBtn.innerHTML =
              '<svg class="h-5 w-5 animate-spin" fill="none" viewBox="0 0 24 24"><circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"></circle><path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z"></path></svg> Saving…';
          }
        });
      }

      if (hasErrors) {
        openAddModal();
      }
    }

    // ---------------- DETAILS MODAL ----------------
    var detailsModal = document.querySelector('[data-research-details-modal]');
    if (detailsModal) {
      var detailsAvatar = document.getElementById('researchDetailsAvatar');
      var detailsTitle = document.getElementById('researchDetailsTitle');
      var detailsAuthors = document.getElementById('researchDetailsAuthors');
      var detailsIndexed = document.getElementById('researchDetailsIndexed');
      var detailsDocStatus = document.getElementById('researchDetailsDocStatus');
      var detailsDocLinkWrap = document.getElementById('researchDetailsDocLinkWrap');
      var detailsDocLink = document.getElementById('researchDetailsDocLink');
      var detailsDocLinkText = document.getElementById('researchDetailsDocLinkText');
      var detailsAbstract = document.getElementById('researchDetailsAbstract');
      var detailsAuthorsChips = document.getElementById('researchDetailsAuthorsChips');
      var detailsAdviser = document.getElementById('researchDetailsAdviser');
      var detailsPublished = document.getElementById('researchDetailsPublished');
      var detailsPublishedMonth = document.getElementById('researchDetailsPublishedMonth');
      var detailsPublishedYear = document.getElementById('researchDetailsPublishedYear');
      var detailsSchoolYear = document.getElementById('researchDetailsSchoolYear');
      var detailsCreated = document.getElementById('researchDetailsCreated');

      var detailsBackdrops = document.querySelectorAll('[data-research-details-modal-backdrop]');
      var detailsCloseButtons = document.querySelectorAll('[data-close-research-details-modal]');

      function dash(v) {
        return (v && (typeof v === 'string') && v.trim()) ? v : '—';
      }

      function renderChipString(targetEl, raw, placeholderLabel) {
        if (!targetEl) return;
        var str = (raw && typeof raw === 'string' && raw.trim()) ? raw : '';
        if (!str) {
          targetEl.innerHTML = '<span class="inline-flex items-center rounded-full bg-slate-100 px-2.5 py-1 text-xs font-medium text-slate-600 ring-1 ring-slate-200">' + placeholderLabel + '</span>';
          return;
        }
        // split by comma first (database stored comma-joined)
        var pieces = str.split(',').map(function (s) { return s.trim(); }).filter(Boolean);
        if (!pieces.length) {
          targetEl.textContent = str;
          return;
        }
        targetEl.innerHTML = pieces.map(function (p) {
          return '<span class="mr-1.5 mb-1 inline-flex items-center rounded-full bg-slate-100 px-2.5 py-1 text-xs font-medium text-slate-700 ring-1 ring-slate-200">' + p + '</span>';
        }).join('');
      }

      function openDetailsModal(row) {
        var title = row.getAttribute('data-title') || '';
        var authors = row.getAttribute('data-authors') || '';
        var adviser = row.getAttribute('data-adviser') || '';
        var abs = row.getAttribute('data-abstract') || '';
        var pub = row.getAttribute('data-published') || '';
        var pubMonthRaw = row.getAttribute('data-published-month') || '';
        var pubYearRaw = row.getAttribute('data-published-year') || '';
        var cre = row.getAttribute('data-created') || '';
        var hasDoc = row.getAttribute('data-has-document') === '1';
        var docUrl = row.getAttribute('data-doc-url') || '';
        var docName = row.getAttribute('data-doc-name') || '';
        var docType = row.getAttribute('data-doc-type') || '';

        var pubMonth = (pubMonthRaw && String(pubMonthRaw).trim()) ? String(pubMonthRaw).trim() : '';
        var pubYear = '';
        if (pubYearRaw && String(pubYearRaw).trim()) {
          var yNum = parseInt(String(pubYearRaw).trim(), 10);
          if (!Number.isNaN(yNum) && yNum >= 1900 && yNum <= 2199) pubYear = String(yNum);
        }
        var computedSchoolYear = '';
        if (pubYear) {
          var y = parseInt(pubYear, 10);
          var startYear = y;
          var endYear = y + 1;
          if (pubMonth && /^(january|february|march|april|may|june)$/i.test(pubMonth)) {
            startYear = y - 1;
            endYear = y;
          }
          computedSchoolYear = 'SY ' + startYear + ' - ' + endYear;
        }

        if (detailsAvatar) {
          detailsAvatar.textContent = (title || 'R').slice(0, 1).toUpperCase();
        }
        if (detailsTitle) detailsTitle.textContent = dash(title);
        if (detailsAuthors) detailsAuthors.textContent = dash(authors);
        if (detailsAbstract) detailsAbstract.textContent = dash(abs);

        renderChipString(detailsAuthorsChips, authors, 'No authors listed');
        if (detailsAdviser) detailsAdviser.textContent = dash(adviser);

        if (detailsPublished) detailsPublished.textContent = dash(pub);
        if (detailsPublishedMonth) detailsPublishedMonth.textContent = dash(pubMonth);
        if (detailsPublishedYear) detailsPublishedYear.textContent = dash(pubYear);
        if (detailsSchoolYear) detailsSchoolYear.textContent = dash(computedSchoolYear);
        if (detailsCreated) detailsCreated.textContent = dash(cre);

        if (detailsIndexed) {
          detailsIndexed.innerHTML = hasDoc
            ? '<span class="inline-flex items-center rounded-full bg-emerald-50 px-2.5 py-1 text-xs font-bold text-emerald-800 ring-1 ring-emerald-200"><span class="mr-1.5 inline-block h-1.5 w-1.5 rounded-full bg-emerald-500"></span>Full-text similarity</span>'
            : '<span class="inline-flex items-center rounded-full bg-amber-50 px-2.5 py-1 text-xs font-bold text-amber-800 ring-1 ring-amber-200"><span class="mr-1.5 inline-block h-1.5 w-1.5 rounded-full bg-amber-500"></span>Metadata-only</span>';
        }
        if (detailsDocStatus) {
          detailsDocStatus.textContent = hasDoc ? docType || 'Document available' : 'No document attached';
        }
        if (detailsDocLinkWrap) {
          if (hasDoc && docUrl) {
            detailsDocLinkWrap.classList.remove('hidden');
            if (detailsDocLink) {
              detailsDocLink.setAttribute('href', docUrl);
            }
            if (detailsDocLinkText) {
              detailsDocLinkText.textContent = docName ? 'Open ' + docName : 'Open Document';
            }
          } else {
            detailsDocLinkWrap.classList.add('hidden');
          }
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

      document.querySelectorAll('[data-view-research]').forEach(function (btn) {
        btn.addEventListener('click', function (e) {
          var row = e.currentTarget.closest('[data-paper-row]');
          if (row) openDetailsModal(row);
        });
      });
      detailsCloseButtons.forEach(function (btn) {
        btn.addEventListener('click', closeDetailsModal);
      });
      detailsBackdrops.forEach(function (bd) {
        bd.addEventListener('click', closeDetailsModal);
      });
    }

    // ---------------- ESC (global for all modals) ----------------
    document.addEventListener('keydown', function (e) {
      if (e.key === 'Escape') {
        [addModal, detailsModal].forEach(function (m) {
          if (m && !m.classList.contains('hidden')) {
            m.classList.add('hidden');
            m.classList.remove('flex');
            document.body.style.overflow = '';
          }
        });
      }
    });
  })();
})((document.currentScript && document.currentScript.dataset) || {});
