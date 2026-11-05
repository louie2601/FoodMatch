(function (cfg) {
  (function () {
    var modal = document.querySelector('[data-user-modal]');
    if (modal) {
      var openBtn = document.querySelector('[data-open-create-modal]');
      var backdrops = document.querySelectorAll('[data-modal-backdrop]');
      var closeButtons = document.querySelectorAll('[data-close-create-modal]');
      var hasErrors = cfg.hasErrors === "1";

      function openModal() {
        modal.classList.remove('hidden');
        modal.classList.add('flex');
        document.body.style.overflow = 'hidden';
        var firstField = modal.querySelector('input, select, button');
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
    }

    (function () {
      var createUserForm = document.querySelector('[data-create-user-form]');
      if (!createUserForm) return;

      var usernameInput = document.getElementById('id_username');
      if (!usernameInput) return;

      var USERNAME_PATTERN = /^[A-Z][a-z]+\.[A-Z][a-z]+$/;
      var AVAILABILITY_CHECK_URL = '/register/check-availability/';
      var AVAILABILITY_DEBOUNCE_MS = 450;
      var availabilityState = { username: null };
      var debounceTimer = null;

      function showFieldError(input, message) {
        var errorEl = document.getElementById(input.id + '_error');
        if (errorEl) {
          errorEl.textContent = message || '';
          errorEl.classList.toggle('hidden', !message);
          errorEl.classList.add('text-red-600');
          errorEl.classList.remove('text-slate-500');
        }
        input.style.borderColor = message ? '#fca5a5' : '';
        input.style.boxShadow = message ? '0 0 0 3px rgba(248,113,113,0.15)' : '';
        return !message;
      }

      function showFieldNote(input, message) {
        var errorEl = document.getElementById(input.id + '_error');
        if (errorEl) {
          errorEl.textContent = message || '';
          errorEl.classList.toggle('hidden', !message);
          errorEl.classList.remove('text-red-600');
          errorEl.classList.add('text-slate-500');
        }
      }

      function liveCapitalizeUsername(input) {
        if (!input || !input.value) return;
        var cursorPos = input.selectionStart;
        var original = input.value;
        var result = '';
        var atWordStart = true;
        for (var i = 0; i < original.length; i++) {
          var ch = original[i];
          if (/[\s.]/.test(ch)) {
            result += ch;
            atWordStart = true;
          } else {
            result += atWordStart ? ch.toUpperCase() : ch.toLowerCase();
            atWordStart = false;
          }
        }
        if (result !== original) {
          input.value = result;
          if (cursorPos !== null) input.setSelectionRange(cursorPos, cursorPos);
        }
      }

      function checkAvailability(field, value) {
        var url = AVAILABILITY_CHECK_URL + '?field=' + encodeURIComponent(field) + '&value=' + encodeURIComponent(value);
        return fetch(url, { headers: { 'X-Requested-With': 'XMLHttpRequest' } })
          .then(function (response) { return response.ok ? response.json() : null; })
          .catch(function () { return null; });
      }

      function validateUsernameField() {
        var value = usernameInput.value.trim();
        if (!value) {
          return showFieldError(usernameInput, 'Username is required.');
        }
        if (!USERNAME_PATTERN.test(value)) {
          return showFieldError(usernameInput, 'Username must be in the format Word.Word, e.g. Juan.Delacruz.');
        }
        if (availabilityState.username === false) {
          return showFieldError(usernameInput, 'This username is already taken.');
        }
        return showFieldError(usernameInput, '');
      }

      function queueAvailabilityCheck() {
        clearTimeout(debounceTimer);
        debounceTimer = setTimeout(function () {
          var value = usernameInput.value.trim();
          if (!value || !USERNAME_PATTERN.test(value)) return;
          showFieldNote(usernameInput, 'Checking availability...');
          checkAvailability('username', value).then(function (data) {
            if (usernameInput.value.trim() !== value) return;
            availabilityState.username = data ? data.available : null;
            validateUsernameField();
          });
        }, AVAILABILITY_DEBOUNCE_MS);
      }

      usernameInput.addEventListener('input', function () {
        liveCapitalizeUsername(usernameInput);
        availabilityState.username = null;
        validateUsernameField();
        queueAvailabilityCheck();
      });

      createUserForm.addEventListener('submit', function (event) {
        if (!validateUsernameField()) {
          event.preventDefault();
          usernameInput.focus();
        }
      });
    })();

    var searchInput = document.getElementById('userSearchInput');
    var searchClearBtn = document.getElementById('userSearchClear');
    var roleFiltersWrap = document.getElementById('userRoleFilters');
    var statusFiltersWrap = document.getElementById('userStatusFilters');
    var onboardingFiltersWrap = document.getElementById('userOnboardingFilters');
    var dateFromInput = document.getElementById('userDateFrom');
    var dateToInput = document.getElementById('userDateTo');
    var resetBtn = document.getElementById('userFiltersReset');
    var resetFromEmptyBtn = document.getElementById('userFiltersResetFromEmpty');
    var filtersToggle = document.getElementById('userFiltersToggle');
    var filtersPanel = document.getElementById('userFiltersPanel');
    var filteredCount = document.getElementById('usersFilteredCount');
    var filteredCountValue = document.getElementById('usersFilteredCountValue');
    var emptyState = document.getElementById('userTableEmptyState');
    var rows = Array.prototype.slice.call(document.querySelectorAll('[data-user-row]'));

    var PAGE_SIZE = 10;
    var paginationBar = document.getElementById('userPagination');
    var paginationSummary = document.getElementById('userPaginationSummary');
    var paginationPageLabel = document.getElementById('userPaginationPageLabel');
    var paginationPrevBtn = document.getElementById('userPaginationPrev');
    var paginationNextBtn = document.getElementById('userPaginationNext');

    var state = {
      query: '',
      role: roleFiltersWrap ? 'all' : 'student',
      status: 'all',
      onboarding: 'all',
      dateFrom: '',
      dateTo: '',
      page: 1,
    };

    function setActiveChip(container, activeValue, attrName) {
      var chips = container.querySelectorAll('button');
      chips.forEach(function (chip) {
        var val = chip.getAttribute(attrName);
        if (val === activeValue) {
          chip.classList.remove('bg-white');
          chip.classList.add('bg-slate-100', 'ring-2', 'ring-slate-200');
        } else {
          chip.classList.add('bg-white');
          chip.classList.remove('bg-slate-100', 'ring-2', 'ring-slate-200');
        }
      });
    }

    function matchesSearch(row, query) {
      if (!query) return true;
      var q = query.trim().toLowerCase();
      var username = row.getAttribute('data-username') || '';
      var name = row.getAttribute('data-name') || '';
      var email = row.getAttribute('data-email') || '';
      return username.indexOf(q) !== -1 || name.indexOf(q) !== -1 || email.indexOf(q) !== -1;
    }

    function matchesDateRange(row, dateFrom, dateTo) {
      if (!dateFrom && !dateTo) return true;
      var joined = row.getAttribute('data-date-joined') || '';
      if (!joined) return false;
      if (dateFrom && joined < dateFrom) return false;
      if (dateTo && joined > dateTo) return false;
      return true;
    }

    function applyFilters() {
      var matchedRows = rows.filter(function (row) {
        var roleOk = !roleFiltersWrap || state.role === 'all' || row.getAttribute('data-role') === state.role;
        var statusOk = state.status === 'all' || row.getAttribute('data-status') === state.status;
        var onboardOk = !onboardingFiltersWrap || state.onboarding === 'all' || row.getAttribute('data-onboarding') === state.onboarding;
        var searchOk = matchesSearch(row, state.query);
        var dateOk = matchesDateRange(row, state.dateFrom, state.dateTo);
        return roleOk && statusOk && onboardOk && searchOk && dateOk;
      });

      var totalPages = Math.max(1, Math.ceil(matchedRows.length / PAGE_SIZE));
      if (state.page > totalPages) state.page = totalPages;
      if (state.page < 1) state.page = 1;

      var startIdx = (state.page - 1) * PAGE_SIZE;
      var endIdx = startIdx + PAGE_SIZE;

      rows.forEach(function (row) {
        row.classList.add('hidden');
      });
      matchedRows.slice(startIdx, endIdx).forEach(function (row) {
        row.classList.remove('hidden');
      });

      var visibleCount = matchedRows.length;

      if (filteredCount && filteredCountValue) {
        var filtersTouched = (
          visibleCount < rows.length ||
          state.query ||
          (roleFiltersWrap && state.role !== 'all') ||
          state.status !== 'all' ||
          (onboardingFiltersWrap && state.onboarding !== 'all') ||
          state.dateFrom ||
          state.dateTo
        );
        if (filtersTouched) {
          filteredCount.classList.remove('hidden');
          filteredCountValue.textContent = String(visibleCount);
        } else {
          filteredCount.classList.add('hidden');
        }
      }

      if (emptyState) {
        if (rows.length === 0) {
          emptyState.classList.add('hidden');
        } else if (visibleCount === 0) {
          emptyState.classList.remove('hidden');
          var wrap = document.getElementById('userTableWrap');
          if (wrap) wrap.classList.add('hidden');
        } else {
          emptyState.classList.add('hidden');
          var wrap2 = document.getElementById('userTableWrap');
          if (wrap2) wrap2.classList.remove('hidden');
        }
      }

      if (paginationBar) {
        if (visibleCount > PAGE_SIZE) {
          paginationBar.classList.remove('hidden');
          paginationBar.classList.add('flex');
          if (paginationSummary) {
            var rangeStart = visibleCount === 0 ? 0 : startIdx + 1;
            var rangeEnd = Math.min(endIdx, visibleCount);
            paginationSummary.textContent = 'Showing ' + rangeStart + '–' + rangeEnd + ' of ' + visibleCount;
          }
          if (paginationPageLabel) {
            paginationPageLabel.textContent = 'Page ' + state.page + ' of ' + totalPages;
          }
          if (paginationPrevBtn) paginationPrevBtn.disabled = state.page <= 1;
          if (paginationNextBtn) paginationNextBtn.disabled = state.page >= totalPages;
        } else {
          paginationBar.classList.add('hidden');
          paginationBar.classList.remove('flex');
        }
      }
    }

    function resetAllFilters() {
      state = { query: '', role: roleFiltersWrap ? 'all' : 'student', status: 'all', onboarding: 'all', dateFrom: '', dateTo: '', page: 1 };
      if (searchInput) searchInput.value = '';
      if (searchClearBtn) searchClearBtn.classList.add('hidden');
      if (roleFiltersWrap) roleFiltersWrap.value = 'all';
      if (statusFiltersWrap) statusFiltersWrap.value = 'all';
      if (onboardingFiltersWrap) setActiveChip(onboardingFiltersWrap, 'all', 'data-user-onboarding-filter');
      if (dateFromInput) dateFromInput.value = '';
      if (dateToInput) dateToInput.value = '';
      applyFilters();
    }

    if (searchInput) {
      var debounceTimer;
      searchInput.addEventListener('input', function () {
        var value = searchInput.value;
        if (searchClearBtn) {
          if (value) searchClearBtn.classList.remove('hidden');
          else searchClearBtn.classList.add('hidden');
        }
        clearTimeout(debounceTimer);
        debounceTimer = setTimeout(function () {
          state.query = value;
          state.page = 1;
          applyFilters();
        }, 120);
      });
    }

    if (searchClearBtn) {
      searchClearBtn.addEventListener('click', function () {
        searchInput.value = '';
        state.query = '';
        state.page = 1;
        searchClearBtn.classList.add('hidden');
        searchInput.focus({ preventScroll: true });
        applyFilters();
      });
    }

    if (dateFromInput) {
      dateFromInput.addEventListener('change', function () {
        state.dateFrom = dateFromInput.value;
        state.page = 1;
        applyFilters();
      });
    }

    if (dateToInput) {
      dateToInput.addEventListener('change', function () {
        state.dateTo = dateToInput.value;
        state.page = 1;
        applyFilters();
      });
    }

    if (roleFiltersWrap) {
      roleFiltersWrap.addEventListener('change', function () {
        state.role = roleFiltersWrap.value;
        state.page = 1;
        applyFilters();
      });
    }

    if (statusFiltersWrap) {
      statusFiltersWrap.addEventListener('change', function () {
        state.status = statusFiltersWrap.value;
        state.page = 1;
        applyFilters();
      });
    }

    if (onboardingFiltersWrap) {
      onboardingFiltersWrap.addEventListener('click', function (e) {
        var target = e.target.closest('button[data-user-onboarding-filter]');
        if (!target) return;
        state.onboarding = target.getAttribute('data-user-onboarding-filter');
        state.page = 1;
        setActiveChip(onboardingFiltersWrap, state.onboarding, 'data-user-onboarding-filter');
        applyFilters();
      });
    }

    if (resetBtn) resetBtn.addEventListener('click', resetAllFilters);
    if (resetFromEmptyBtn) resetFromEmptyBtn.addEventListener('click', resetAllFilters);

    if (filtersToggle && filtersPanel) {
      filtersToggle.addEventListener('click', function () {
        var expanded = filtersToggle.getAttribute('aria-expanded') === 'true';
        filtersToggle.setAttribute('aria-expanded', String(!expanded));
        if (expanded) {
          filtersPanel.classList.add('hidden');
        } else {
          filtersPanel.classList.remove('hidden');
        }
      });
    }

    if (paginationPrevBtn) {
      paginationPrevBtn.addEventListener('click', function () {
        state.page -= 1;
        applyFilters();
        if (paginationBar) paginationBar.scrollIntoView({ block: 'nearest' });
      });
    }

    if (paginationNextBtn) {
      paginationNextBtn.addEventListener('click', function () {
        state.page += 1;
        applyFilters();
        if (paginationBar) paginationBar.scrollIntoView({ block: 'nearest' });
      });
    }

    var profileModal = document.querySelector('[data-profile-modal]');
    if (profileModal) {
      var profileBackdrops = document.querySelectorAll('[data-profile-modal-backdrop]');
      var profileCloseButtons = document.querySelectorAll('[data-close-profile-modal]');

      var avatarEl = document.getElementById('profileAvatarWrap');
      var fullNameEl = document.getElementById('profileFullName');
      var roleBadgeEl = document.getElementById('profileRoleBadge');
      var statusBadgeEl = document.getElementById('profileStatusBadge');
      var usernameEl = document.getElementById('profileUsername');
      var emailEl = document.getElementById('profileEmail');
      var firstNameEl = document.getElementById('profileFirstName');
      var middleNameEl = document.getElementById('profileMiddleName');
      var lastNameEl = document.getElementById('profileLastName');
      var studentCardEl = document.getElementById('studentProfileCard');
      var programEl = document.getElementById('profileProgram');
      var collegeEl = document.getElementById('profileCollege');
      var onboardingEl = document.getElementById('profileOnboarding');
      var dateJoinedEl = document.getElementById('profileDateJoined');
      var lastLoginEl = document.getElementById('profileLastLogin');

      function dashOr(val) {
        var v = String(val == null ? '' : val).trim();
        return v ? v : '\u2014';
      }

      function roleMeta(roleCategory, roleLabel) {
        switch (roleCategory) {
          case 'super_admin':
            return {
              icon: '\uD83D\uDEE1\uFE0F',
              classes: 'bg-gradient-to-r from-emerald-100 via-green-100 to-pink-100 text-emerald-900 ring-green-200',
              avatar: 'from-emerald-100 to-green-200 text-emerald-900',
            };
          case 'admin':
            return {
              icon: '\uD83D\uDC68\u200D\uD83D\uDCBC',
              classes: 'bg-gradient-to-r from-emerald-50 to-teal-100 text-emerald-900 ring-emerald-200',
              avatar: 'from-emerald-100 to-teal-200 text-emerald-900',
            };
          case 'student':
            return {
              icon: '\uD83C\uDF93',
              classes: 'bg-gradient-to-r from-amber-50 to-orange-100 text-amber-900 ring-amber-200',
              avatar: 'from-amber-100 to-orange-200 text-amber-900',
            };
          default:
            return {
              icon: '',
              classes: 'bg-slate-100 text-slate-800 ring-slate-200',
              avatar: 'from-slate-100 to-slate-200 text-slate-800',
            };
        }
      }

      function statusMeta(isActive) {
        return isActive
          ? { classes: 'bg-emerald-50 text-emerald-800 ring-emerald-200', label: 'Active', dot: 'bg-emerald-500' }
          : { classes: 'bg-slate-100 text-slate-700 ring-slate-200', label: 'Inactive', dot: 'bg-slate-500' };
      }

      function onboardingMeta(isComplete) {
        return isComplete
          ? { classes: 'bg-emerald-50 text-emerald-800 ring-emerald-200', label: '\u2705 Completed' }
          : { classes: 'bg-amber-50 text-amber-800 ring-amber-200', label: '\u26A0\uFE0F Pending' };
      }

      function populateProfileFromRow(row) {
        function attr(name) { return row.getAttribute(name) || ''; }

        var username = attr('data-profile-username');
        var email = attr('data-profile-email');
        var firstName = attr('data-profile-first-name');
        var middleName = attr('data-profile-middle-name');
        var lastName = attr('data-profile-last-name');
        var displayName = attr('data-profile-display-name');
        var roleCategory = attr('data-profile-role-category');
        var roleLabel = attr('data-profile-role-label');
        var isActive = attr('data-profile-is-active') === 'true';
        var profileComplete = attr('data-profile-profile-complete') === 'true';
        var program = attr('data-profile-program');
        var college = attr('data-profile-college');
        var dateJoined = attr('data-profile-date-joined');
        var lastLogin = attr('data-profile-last-login');

        var headerName = displayName.trim() || username || 'Unnamed User';
        var fullText = (firstName + ' ' + (middleName ? middleName + ' ' : '') + lastName).trim() || displayName;

        if (avatarEl) {
          var letter = (username || 'U').slice(0, 1).toUpperCase();
          var roleAv = roleMeta(roleCategory, roleLabel).avatar;
          avatarEl.textContent = letter;
          avatarEl.className = 'flex h-14 w-14 shrink-0 items-center justify-center rounded-2xl border-4 border-white shadow-md text-2xl font-black bg-gradient-to-br ' + roleAv;
        }

        if (fullNameEl) fullNameEl.textContent = headerName;

        if (roleBadgeEl) {
          var rm = roleMeta(roleCategory, roleLabel);
          roleBadgeEl.className = 'inline-flex items-center rounded-full px-3 py-1 text-xs font-bold ring-1 ' + rm.classes;
          roleBadgeEl.textContent = (rm.icon ? rm.icon + ' ' : '') + (roleLabel || 'User');
        }

        if (statusBadgeEl) {
          var sm = statusMeta(isActive);
          statusBadgeEl.className = 'inline-flex items-center rounded-full px-2.5 py-1 text-xs font-semibold ring-1 ' + sm.classes;
          statusBadgeEl.innerHTML = '<span class="mr-1.5 inline-block h-1.5 w-1.5 rounded-full ' + sm.dot + '"></span>' + sm.label;
        }

        if (usernameEl) usernameEl.textContent = dashOr(username);
        if (emailEl) {
          var cleanEmail = email.trim();
          emailEl.textContent = dashOr(cleanEmail);
          if (cleanEmail) {
            emailEl.setAttribute('href', 'mailto:' + cleanEmail);
          } else {
            emailEl.removeAttribute('href');
          }
        }

        if (firstNameEl) firstNameEl.textContent = dashOr(firstName);
        var membersCard = document.getElementById('groupMembersCard');
        if (membersCard) {
          var memberNames = attr('data-profile-members').split(' | ').filter(Boolean);
          var groupNameText = attr('data-profile-group-name');
          var groupNameEl = document.getElementById('profileGroupName');
          var listEl = document.getElementById('profileMembersList');
          listEl.innerHTML = '';
          memberNames.forEach(function (n, i) {
            var li = document.createElement('li');
            li.textContent = (i + 1) + '. ' + n + (i === 0 ? ' (leader)' : '');
            listEl.appendChild(li);
          });
          groupNameEl.textContent = groupNameText;
          groupNameEl.classList.toggle('hidden', !groupNameText);
          membersCard.classList.toggle('hidden', memberNames.length === 0);
        }
        if (middleNameEl) middleNameEl.textContent = dashOr(middleName);
        if (lastNameEl) lastNameEl.textContent = dashOr(lastName || '');

        if (studentCardEl) {
          if (roleCategory === 'student' && (program || college)) {
            studentCardEl.classList.remove('hidden');
            if (programEl) programEl.textContent = dashOr(program);
            if (collegeEl) collegeEl.textContent = dashOr(college);
          } else {
            studentCardEl.classList.add('hidden');
          }
        }

        if (onboardingEl) {
          var ob = onboardingMeta(profileComplete);
          onboardingEl.className = 'inline-flex items-center rounded-full px-2.5 py-1 text-xs font-semibold ring-1 ' + ob.classes;
          onboardingEl.textContent = ob.label;
        }

        if (dateJoinedEl) dateJoinedEl.textContent = dashOr(dateJoined);
        if (lastLoginEl) lastLoginEl.textContent = dashOr(lastLogin);
      }

      function openProfileModal(row) {
        populateProfileFromRow(row);
        profileModal.classList.remove('hidden');
        profileModal.classList.add('flex');
        document.body.style.overflow = 'hidden';
        var firstFocus = profileModal.querySelector('button');
        if (firstFocus) firstFocus.focus({ preventScroll: true });
      }

      function closeProfileModal() {
        profileModal.classList.add('hidden');
        profileModal.classList.remove('flex');
        document.body.style.overflow = '';
      }

      var viewProfileBtns = document.querySelectorAll('[data-trigger-view-profile]');
      viewProfileBtns.forEach(function (btn) {
        btn.addEventListener('click', function () {
          var row = btn.closest('[data-user-row]');
          if (row) openProfileModal(row);
        });
      });

      profileCloseButtons.forEach(function (btn) {
        btn.addEventListener('click', closeProfileModal);
      });

      profileBackdrops.forEach(function (bd) {
        bd.addEventListener('click', closeProfileModal);
      });

      document.addEventListener('keydown', function (e) {
        if (e.key === 'Escape' && !profileModal.classList.contains('hidden')) {
          closeProfileModal();
        }
      });
    }

    var requestDeleteModal = document.querySelector('[data-request-delete-modal]');
    if (requestDeleteModal) {
      var reqDeleteBackdrops = document.querySelectorAll('[data-request-delete-modal-backdrop]');
      var reqDeleteCloseButtons = document.querySelectorAll('[data-close-request-delete-modal]');
      var confirmReqDeleteBtn = document.getElementById('confirmRequestDeleteBtn');
      var reqDeleteTargetNameEl = document.getElementById('requestDeleteTargetName');
      var pendingRequestDeleteForm = null;

      var reqDeleteReasonEl = document.getElementById('requestDeleteReason');
      var reqDeleteReasonErr = document.getElementById('requestDeleteReasonError');

      function openRequestDeleteModal(form, name) {
        pendingRequestDeleteForm = form;
        if (reqDeleteReasonEl) reqDeleteReasonEl.value = '';
        if (reqDeleteReasonErr) reqDeleteReasonErr.classList.add('hidden');
        if (reqDeleteTargetNameEl) {
          reqDeleteTargetNameEl.textContent = name || 'this account';
        }
        requestDeleteModal.classList.remove('hidden');
        requestDeleteModal.classList.add('flex');
        document.body.style.overflow = 'hidden';
        if (reqDeleteReasonEl) reqDeleteReasonEl.focus({ preventScroll: true });
      }

      function closeRequestDeleteModal() {
        pendingRequestDeleteForm = null;
        requestDeleteModal.classList.add('hidden');
        requestDeleteModal.classList.remove('flex');
        document.body.style.overflow = '';
      }

      var reqDeleteTriggerBtns = document.querySelectorAll('[data-trigger-request-delete]');
      reqDeleteTriggerBtns.forEach(function (btn) {
        btn.addEventListener('click', function (e) {
          var form = btn.closest('form');
          var name = btn.getAttribute('data-target-name') || '';
          openRequestDeleteModal(form, name);
        });
      });

      reqDeleteCloseButtons.forEach(function (btn) {
        btn.addEventListener('click', closeRequestDeleteModal);
      });

      reqDeleteBackdrops.forEach(function (bd) {
        bd.addEventListener('click', closeRequestDeleteModal);
      });

      document.addEventListener('keydown', function (e) {
        if (e.key === 'Escape' && !requestDeleteModal.classList.contains('hidden')) {
          closeRequestDeleteModal();
        }
      });

      if (confirmReqDeleteBtn) {
        confirmReqDeleteBtn.addEventListener('click', function () {
          if (pendingRequestDeleteForm) {
            var reasonText = reqDeleteReasonEl ? reqDeleteReasonEl.value.trim() : '';
            if (!reasonText) {
              if (reqDeleteReasonErr) reqDeleteReasonErr.classList.remove('hidden');
              if (reqDeleteReasonEl) reqDeleteReasonEl.focus();
              return;
            }
            var reasonField = pendingRequestDeleteForm.querySelector('input[name="reason"]');
            if (!reasonField) {
              reasonField = document.createElement('input');
              reasonField.type = 'hidden';
              reasonField.name = 'reason';
              pendingRequestDeleteForm.appendChild(reasonField);
            }
            reasonField.value = reasonText;
            confirmReqDeleteBtn.disabled = true;
            confirmReqDeleteBtn.classList.add('opacity-70', 'cursor-not-allowed');
            confirmReqDeleteBtn.innerHTML = '<svg class="h-5 w-5 animate-spin" fill="none" stroke="currentColor" viewBox="0 0 24 24"><circle cx="12" cy="12" r="10" stroke-width="3" class="opacity-25"></circle><path d="M4 12a8 8 0 018-8" stroke-width="3" class="opacity-75" stroke-linecap="round"></path></svg> Submitting...';
            pendingRequestDeleteForm.submit();
          }
        });
      }
    }

    applyFilters();
  })();
})((document.currentScript && document.currentScript.dataset) || {});
