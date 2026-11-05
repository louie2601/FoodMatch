document.addEventListener("DOMContentLoaded", function () {
  const toggleButtons = document.querySelectorAll("[data-password-toggle]");

  toggleButtons.forEach(function (button) {
    const passwordInput = button.parentElement.querySelector("[data-password-input]");

    if (!passwordInput) {
      return;
    }

    button.addEventListener("click", function () {
      const isPassword = passwordInput.getAttribute("type") === "password";
      passwordInput.setAttribute("type", isPassword ? "text" : "password");
    });
  });

  const roleSelector = document.querySelector("[data-role-selector]");
  const studentFieldWrappers = document.querySelectorAll("[data-student-field-wrapper]");
  const studentFields = document.querySelectorAll("[data-student-field]");
  const studentRequiredMarkers = document.querySelectorAll("[data-student-required-marker]");

  function syncRoleFields() {
    if (!roleSelector) {
      return;
    }

    const isStudent = roleSelector.value === "Student";

    studentFieldWrappers.forEach(function (wrapper) {
      wrapper.classList.toggle("hidden", !isStudent);
    });

    studentFields.forEach(function (field) {
      if (isStudent) {
        field.setAttribute("required", "required");
      } else {
        field.removeAttribute("required");
      }
    });

    studentRequiredMarkers.forEach(function (marker) {
      marker.classList.toggle("hidden", !isStudent);
    });
  }

  if (roleSelector) {
    syncRoleFields();
    roleSelector.addEventListener("change", syncRoleFields);
  }

  // ---------------------------------------------------------------------
  // Shared real-time validation helpers (used by the Registration form and
  // the Complete Profile form).
  // ---------------------------------------------------------------------

  const EMAIL_PATTERN = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;
  const USERNAME_PATTERN = /^[A-Z][a-z]+\.[A-Z][a-z]+$/;
  const DOUBLE_SPACE_PATTERN = /\s{2,}/;
  const REPEATED_CHAR_PATTERN = /(.)\1{2,}/i;
  const DIGIT_PATTERN = /\d/;
  const SPECIAL_CHAR_PATTERN = /[^A-Za-zÀ-ÖØ-öø-ÿ\s\d]/;
  const AVAILABILITY_CHECK_URL = "/register/check-availability/";
  const AVAILABILITY_DEBOUNCE_MS = 450;

  function debounce(fn, delay) {
    let timer = null;
    return function () {
      const context = this;
      const args = arguments;
      clearTimeout(timer);
      timer = setTimeout(function () {
        fn.apply(context, args);
      }, delay);
    };
  }

  function showFieldError(input, message) {
    const errorEl = input ? document.getElementById(input.id + "_error") : null;

    if (errorEl) {
      errorEl.textContent = message || "";
      errorEl.classList.toggle("hidden", !message);
      errorEl.classList.add("text-red-600");
      errorEl.classList.remove("text-slate-500");
    }

    if (input) {
      input.style.borderColor = message ? "#fca5a5" : "";
      input.style.boxShadow = message ? "0 0 0 3px rgba(248,113,113,0.15)" : "";
    }

    return !message;
  }

  function showFieldNote(input, message) {
    const errorEl = input ? document.getElementById(input.id + "_error") : null;

    if (errorEl) {
      errorEl.textContent = message || "";
      errorEl.classList.toggle("hidden", !message);
      errorEl.classList.remove("text-red-600");
      errorEl.classList.add("text-slate-500");
    }
  }

  function checkAvailability(field, value, extraQuery) {
    const url = AVAILABILITY_CHECK_URL + "?field=" + encodeURIComponent(field) + "&value=" + encodeURIComponent(value) + (extraQuery || "");
    return fetch(url, { headers: { "X-Requested-With": "XMLHttpRequest" } })
      .then(function (response) {
        return response.ok ? response.json() : null;
      })
      .catch(function () {
        return null;
      });
  }

  function titleCaseName(input) {
    if (!input || !input.value) {
      return;
    }

    const words = input.value.trim().split(/\s+/);
    input.value = words
      .map(function (word) {
        return word.charAt(0).toUpperCase() + word.slice(1).toLowerCase();
      })
      .join(" ");
  }

  function liveCapitalizeAtBoundaries(input, isBoundaryChar) {
    if (!input || !input.value) {
      return;
    }

    const cursorPos = input.selectionStart;
    const original = input.value;
    let result = "";
    let atWordStart = true;

    for (let i = 0; i < original.length; i++) {
      const ch = original[i];
      if (isBoundaryChar(ch)) {
        result += ch;
        atWordStart = true;
      } else {
        result += atWordStart ? ch.toUpperCase() : ch.toLowerCase();
        atWordStart = false;
      }
    }

    if (result !== original) {
      input.value = result;
      if (cursorPos !== null) {
        input.setSelectionRange(cursorPos, cursorPos);
      }
    }
  }

  function liveCapitalizeName(input) {
    liveCapitalizeAtBoundaries(input, function (ch) {
      return /\s/.test(ch);
    });
  }

  function liveCapitalizeUsername(input) {
    liveCapitalizeAtBoundaries(input, function (ch) {
      return /[\s.]/.test(ch);
    });
  }

  function validateSelectField(select, label) {
    if (!select) {
      return true;
    }

    if (!select.value) {
      return showFieldError(select, label + " is required.");
    }
    return showFieldError(select, "");
  }

  function validateNameField(input, label, required) {
    if (!input) {
      return true;
    }

    const value = input.value.trim();

    if (!value) {
      return required ? showFieldError(input, label + " is required.") : showFieldError(input, "");
    }
    if (DOUBLE_SPACE_PATTERN.test(value)) {
      return showFieldError(input, label + " cannot contain double spaces.");
    }
    if (REPEATED_CHAR_PATTERN.test(value)) {
      return showFieldError(input, label + " cannot contain the same letter repeated 3 or more times in a row.");
    }

    const hasDigit = DIGIT_PATTERN.test(value);
    const hasSpecial = SPECIAL_CHAR_PATTERN.test(value);

    if (hasDigit && hasSpecial) {
      return showFieldError(input, label + " cannot contain numbers or special characters.");
    }
    if (hasDigit) {
      return showFieldError(input, label + " cannot contain numbers.");
    }
    if (hasSpecial) {
      return showFieldError(input, label + " cannot contain special characters.");
    }

    return showFieldError(input, "");
  }

  function validatePasswordField(input, minLength) {
    if (!input) {
      return true;
    }

    const value = input.value;
    const requiredLength = minLength || 8;

    if (!value) {
      return showFieldError(input, "Password is required.");
    }
    if (value.length < requiredLength) {
      return showFieldError(input, "Password must be at least " + requiredLength + " characters long.");
    }
    if (/^\d+$/.test(value)) {
      return showFieldError(input, "Password cannot be entirely numeric.");
    }
    return showFieldError(input, "");
  }

  function validateConfirmPasswordField(confirmInput, passwordInput) {
    if (!confirmInput) {
      return true;
    }

    if (!confirmInput.value) {
      return showFieldError(confirmInput, "Please re-enter your password.");
    }
    if (passwordInput && confirmInput.value !== passwordInput.value) {
      return showFieldError(confirmInput, "Passwords do not match.");
    }
    return showFieldError(confirmInput, "");
  }

  // ---------------------------------------------------------------------
  // Group members formset (student accounts are research groups)
  // ---------------------------------------------------------------------

  function initMembersFormset(root) {
    const container = root ? root.querySelector("[data-members-formset]") : null;
    if (!container) {
      return null;
    }

    const max = parseInt(container.getAttribute("data-max") || "5", 10);
    const rowsEl = container.querySelector("[data-member-rows]");
    const template = container.querySelector("template[data-member-template]");
    const addBtn = container.querySelector("[data-member-add]");
    const addLabel = container.querySelector("[data-member-add-label]");
    const totalInput = container.querySelector('input[name$="-TOTAL_FORMS"]');
    const groupError = container.querySelector("[data-members-error]");
    const FIELD_META = {
      first_name: { label: "First name", required: true },
      middle_name: { label: "Middle name", required: false },
      last_name: { label: "Last name", required: true },
    };

    function rows() {
      return Array.prototype.slice.call(rowsEl.querySelectorAll("[data-member-row]"));
    }

    function reindex() {
      rows().forEach(function (row, i) {
        row.querySelectorAll("[name], [id], [for]").forEach(function (el) {
          ["name", "id", "for"].forEach(function (attr) {
            const value = el.getAttribute(attr);
            if (value) {
              el.setAttribute(attr, value.replace(/members-(?:\d+|__prefix__)-/, "members-" + i + "-"));
            }
          });
        });
        const title = row.querySelector("[data-member-title]");
        if (title) {
          title.textContent = "Member " + (i + 1) + (i === 0 ? " \u00b7 Leader" : "");
        }
        const removeBtn = row.querySelector("[data-member-remove]");
        if (removeBtn) {
          removeBtn.classList.toggle("hidden", i === 0);
        }
      });
      const count = rows().length;
      if (totalInput) {
        totalInput.value = String(count);
      }
      if (addBtn) {
        addBtn.disabled = count >= max;
      }
      if (addLabel) {
        addLabel.textContent = count >= max ? "Maximum of " + max + " members" : "Add member";
      }
    }

    function fieldOf(input) {
      const match = /-(first_name|middle_name|last_name)$/.exec(input.name || "");
      return match ? match[1] : null;
    }

    function validateRow(row) {
      let ok = true;
      Object.keys(FIELD_META).forEach(function (field) {
        const input = row.querySelector('input[name$="-' + field + '"]');
        if (input && !validateNameField(input, FIELD_META[field].label, FIELD_META[field].required)) {
          ok = false;
        }
      });
      return ok;
    }

    function validate() {
      let ok = true;
      const seen = {};
      rows().forEach(function (row) {
        titleCaseRow(row);
        if (!validateRow(row)) {
          ok = false;
          return;
        }
        const get = function (field) {
          const input = row.querySelector('input[name$="-' + field + '"]');
          return input ? input.value.trim().toLowerCase() : "";
        };
        const key = get("first_name") + "|" + get("middle_name") + "|" + get("last_name");
        if (seen[key]) {
          const last = row.querySelector('input[name$="-last_name"]');
          showFieldError(last, "This member is already listed.");
          ok = false;
        }
        seen[key] = true;
      });
      if (groupError && ok) {
        groupError.classList.add("hidden");
      }
      return ok;
    }

    function titleCaseRow(row) {
      row.querySelectorAll("input[name]").forEach(function (input) {
        if (fieldOf(input)) {
          titleCaseName(input);
        }
      });
    }

    function focusFirstInvalid() {
      const bad = Array.prototype.slice
        .call(container.querySelectorAll("input[name]"))
        .filter(function (input) {
          return input.style.borderColor;
        })[0];
      if (bad) {
        bad.focus();
      }
    }

    rowsEl.addEventListener("input", function (event) {
      const field = fieldOf(event.target);
      if (field) {
        liveCapitalizeName(event.target);
        validateNameField(event.target, FIELD_META[field].label, FIELD_META[field].required);
      }
    });
    rowsEl.addEventListener("focusout", function (event) {
      const field = fieldOf(event.target);
      if (field) {
        titleCaseName(event.target);
        validateNameField(event.target, FIELD_META[field].label, FIELD_META[field].required);
      }
    });
    rowsEl.addEventListener("click", function (event) {
      const removeBtn = event.target.closest ? event.target.closest("[data-member-remove]") : null;
      if (!removeBtn) {
        return;
      }
      const row = removeBtn.closest("[data-member-row]");
      if (row && rows().length > 1) {
        row.remove();
        reindex();
      }
    });

    if (addBtn && template) {
      addBtn.addEventListener("click", function () {
        if (rows().length >= max) {
          return;
        }
        const holder = document.createElement("div");
        holder.innerHTML = template.innerHTML.replace(/__prefix__/g, String(rows().length));
        const row = holder.firstElementChild;
        rowsEl.appendChild(row);
        reindex();
        const firstInput = row.querySelector("input");
        if (firstInput) {
          firstInput.focus();
        }
      });
    }

    reindex();
    return { validate: validate, focusFirstInvalid: focusFirstInvalid };
  }

  // ---------------------------------------------------------------------
  // Registration form
  // ---------------------------------------------------------------------

  const registerForm = document.querySelector("[data-register-form]");

  if (registerForm) {
    const firstNameInput = document.getElementById("id_first_name");
    const middleNameInput = document.getElementById("id_middle_name");
    const lastNameInput = document.getElementById("id_last_name");
    const programSelect = document.getElementById("id_program");
    const collegeSelect = document.getElementById("id_college");
    const emailInput = document.getElementById("id_email");
    const usernameInput = document.getElementById("id_username");
    const passwordInput = document.getElementById("id_password");
    const confirmPasswordInput = document.getElementById("id_confirm_password");

    const availabilityState = { email: null, username: null };
    const members = initMembersFormset(registerForm);

    function validateEmailField() {
      if (!emailInput) {
        return true;
      }

      const value = emailInput.value.trim();

      if (!value) {
        return showFieldError(emailInput, "Email is required.");
      }
      if (!EMAIL_PATTERN.test(value)) {
        return showFieldError(emailInput, "Enter a valid email address.");
      }
      if (availabilityState.email === false) {
        return showFieldError(emailInput, "This email is already registered.");
      }
      return showFieldError(emailInput, "");
    }

    function validateUsernameField() {
      if (!usernameInput) {
        return true;
      }

      const value = usernameInput.value.trim();

      if (!value) {
        return showFieldError(usernameInput, "Username is required.");
      }
      if (!USERNAME_PATTERN.test(value)) {
        return showFieldError(usernameInput, "Username must be in the format Word.Word, e.g. Juan.Delacruz.");
      }
      if (availabilityState.username === false) {
        return showFieldError(usernameInput, "This username is already taken.");
      }
      return showFieldError(usernameInput, "");
    }

    const debouncedEmailAvailability = debounce(function () {
      const value = emailInput.value.trim();
      if (!value || !EMAIL_PATTERN.test(value)) {
        return;
      }
      showFieldNote(emailInput, "Checking availability...");
      checkAvailability("email", value).then(function (data) {
        if (!emailInput || emailInput.value.trim() !== value) {
          return;
        }
        availabilityState.email = data ? data.available : null;
        validateEmailField();
      });
    }, AVAILABILITY_DEBOUNCE_MS);

    const debouncedUsernameAvailability = debounce(function () {
      const value = usernameInput.value.trim();
      if (!value || !USERNAME_PATTERN.test(value)) {
        return;
      }
      showFieldNote(usernameInput, "Checking availability...");
      checkAvailability("username", value).then(function (data) {
        if (!usernameInput || usernameInput.value.trim() !== value) {
          return;
        }
        availabilityState.username = data ? data.available : null;
        validateUsernameField();
      });
    }, AVAILABILITY_DEBOUNCE_MS);

    if (firstNameInput) {
      firstNameInput.addEventListener("input", function () {
        liveCapitalizeName(firstNameInput);
        validateNameField(firstNameInput, "First name", true);
      });
      firstNameInput.addEventListener("blur", function () {
        titleCaseName(firstNameInput);
        validateNameField(firstNameInput, "First name", true);
      });
    }

    if (middleNameInput) {
      middleNameInput.addEventListener("input", function () {
        liveCapitalizeName(middleNameInput);
        validateNameField(middleNameInput, "Middle name", false);
      });
      middleNameInput.addEventListener("blur", function () {
        titleCaseName(middleNameInput);
        validateNameField(middleNameInput, "Middle name", false);
      });
    }

    if (lastNameInput) {
      lastNameInput.addEventListener("input", function () {
        liveCapitalizeName(lastNameInput);
        validateNameField(lastNameInput, "Last name", true);
      });
      lastNameInput.addEventListener("blur", function () {
        titleCaseName(lastNameInput);
        validateNameField(lastNameInput, "Last name", true);
      });
    }

    if (programSelect) {
      programSelect.addEventListener("change", function () {
        validateSelectField(programSelect, "Program");
      });
    }

    if (collegeSelect) {
      collegeSelect.addEventListener("change", function () {
        validateSelectField(collegeSelect, "College");
      });
    }

    if (emailInput) {
      emailInput.addEventListener("input", function () {
        availabilityState.email = null;
        validateEmailField();
        debouncedEmailAvailability();
      });
    }

    if (usernameInput) {
      usernameInput.addEventListener("input", function () {
        liveCapitalizeUsername(usernameInput);
        availabilityState.username = null;
        validateUsernameField();
        debouncedUsernameAvailability();
      });
    }

    if (passwordInput) {
      passwordInput.addEventListener("input", function () {
        validatePasswordField(passwordInput);
        if (confirmPasswordInput && confirmPasswordInput.value) {
          validateConfirmPasswordField(confirmPasswordInput, passwordInput);
        }
      });
    }

    if (confirmPasswordInput) {
      confirmPasswordInput.addEventListener("input", function () {
        validateConfirmPasswordField(confirmPasswordInput, passwordInput);
      });
    }

    registerForm.addEventListener("submit", function (event) {
      titleCaseName(firstNameInput);
      titleCaseName(middleNameInput);
      titleCaseName(lastNameInput);
      const membersOk = members ? members.validate() : true;

      const firstNameOk = validateNameField(firstNameInput, "First name", true);
      const middleNameOk = validateNameField(middleNameInput, "Middle name", false);
      const lastNameOk = validateNameField(lastNameInput, "Last name", true);
      const programOk = validateSelectField(programSelect, "Program");
      const collegeOk = validateSelectField(collegeSelect, "College");
      const emailOk = validateEmailField();
      const usernameOk = validateUsernameField();
      const passwordOk = validatePasswordField(passwordInput);
      const confirmOk = validateConfirmPasswordField(confirmPasswordInput, passwordInput);

      if (!(membersOk && firstNameOk && middleNameOk && lastNameOk && programOk && collegeOk && emailOk && usernameOk && passwordOk && confirmOk)) {
        event.preventDefault();

        if (members && !membersOk) {
          members.focusFirstInvalid();
          return;
        }

        const invalidInputs = [
          firstNameInput,
          middleNameInput,
          lastNameInput,
          programSelect,
          collegeSelect,
          emailInput,
          usernameInput,
          passwordInput,
          confirmPasswordInput,
        ];
        for (let i = 0; i < invalidInputs.length; i++) {
          if (invalidInputs[i] && invalidInputs[i].style.borderColor) {
            invalidInputs[i].focus();
            break;
          }
        }
      }
    });
  }

  // ---------------------------------------------------------------------
  // Complete Profile form
  // ---------------------------------------------------------------------

  const completeProfileForm = document.querySelector("[data-complete-profile-form]");

  if (completeProfileForm) {
    const firstNameInput = document.getElementById("id_first_name");
    const middleNameInput = document.getElementById("id_middle_name");
    const lastNameInput = document.getElementById("id_last_name");
    const programSelect = document.getElementById("id_program");
    const collegeSelect = document.getElementById("id_college");
    const newPasswordInput = document.getElementById("id_new_password");
    const confirmNewPasswordInput = document.getElementById("id_confirm_new_password");
    const members = initMembersFormset(completeProfileForm);

    if (firstNameInput) {
      firstNameInput.addEventListener("input", function () {
        liveCapitalizeName(firstNameInput);
        validateNameField(firstNameInput, "First name", true);
      });
      firstNameInput.addEventListener("blur", function () {
        titleCaseName(firstNameInput);
        validateNameField(firstNameInput, "First name", true);
      });
    }

    if (middleNameInput) {
      middleNameInput.addEventListener("input", function () {
        liveCapitalizeName(middleNameInput);
        validateNameField(middleNameInput, "Middle name", false);
      });
      middleNameInput.addEventListener("blur", function () {
        titleCaseName(middleNameInput);
        validateNameField(middleNameInput, "Middle name", false);
      });
    }

    if (lastNameInput) {
      lastNameInput.addEventListener("input", function () {
        liveCapitalizeName(lastNameInput);
        validateNameField(lastNameInput, "Last name", true);
      });
      lastNameInput.addEventListener("blur", function () {
        titleCaseName(lastNameInput);
        validateNameField(lastNameInput, "Last name", true);
      });
    }

    if (programSelect) {
      programSelect.addEventListener("change", function () {
        validateSelectField(programSelect, "Program");
      });
    }

    if (collegeSelect) {
      collegeSelect.addEventListener("change", function () {
        validateSelectField(collegeSelect, "College");
      });
    }

    if (newPasswordInput) {
      newPasswordInput.addEventListener("input", function () {
        validatePasswordField(newPasswordInput);
        if (confirmNewPasswordInput && confirmNewPasswordInput.value) {
          validateConfirmPasswordField(confirmNewPasswordInput, newPasswordInput);
        }
      });
    }

    if (confirmNewPasswordInput) {
      confirmNewPasswordInput.addEventListener("input", function () {
        validateConfirmPasswordField(confirmNewPasswordInput, newPasswordInput);
      });
    }

    completeProfileForm.addEventListener("submit", function (event) {
      titleCaseName(firstNameInput);
      titleCaseName(middleNameInput);
      titleCaseName(lastNameInput);
      const membersOk = members ? members.validate() : true;

      const firstNameOk = validateNameField(firstNameInput, "First name", true);
      const middleNameOk = validateNameField(middleNameInput, "Middle name", false);
      const lastNameOk = validateNameField(lastNameInput, "Last name", true);
      const programOk = validateSelectField(programSelect, "Program");
      const collegeOk = validateSelectField(collegeSelect, "College");
      const passwordOk = validatePasswordField(newPasswordInput);
      const confirmOk = validateConfirmPasswordField(confirmNewPasswordInput, newPasswordInput);

      if (!(membersOk && firstNameOk && middleNameOk && lastNameOk && programOk && collegeOk && passwordOk && confirmOk)) {
        event.preventDefault();

        if (members && !membersOk) {
          members.focusFirstInvalid();
          return;
        }

        const invalidInputs = [
          firstNameInput,
          middleNameInput,
          lastNameInput,
          programSelect,
          collegeSelect,
          newPasswordInput,
          confirmNewPasswordInput,
        ];
        for (let i = 0; i < invalidInputs.length; i++) {
          if (invalidInputs[i] && invalidInputs[i].style.borderColor) {
            invalidInputs[i].focus();
            break;
          }
        }
      }
    });
  }

  // ---------------------------------------------------------------------
  // Profile page: personal information form + change password form
  // ---------------------------------------------------------------------

  // ---------------------------------------------------------------------
  // Manage Users: edit-account modal (Admin / Super Admin)
  // ---------------------------------------------------------------------

  const adminEditUserForm = document.querySelector("[data-admin-edit-user-form]");
  if (adminEditUserForm) {
    const editMembers = initMembersFormset(adminEditUserForm);
    adminEditUserForm.addEventListener("submit", function (event) {
      if (editMembers && !editMembers.validate()) {
        event.preventDefault();
        editMembers.focusFirstInvalid();
      }
    });
  }

  const profileForm = document.querySelector("[data-profile-form]");

  if (profileForm) {
    const firstNameInput = document.getElementById("id_first_name");
    const middleNameInput = document.getElementById("id_middle_name");
    const lastNameInput = document.getElementById("id_last_name");
    const emailInput = document.getElementById("id_email");
    const programSelect = document.getElementById("id_program");
    const collegeSelect = document.getElementById("id_college");
    const emailState = { available: null };
    const members = initMembersFormset(profileForm);

    function validateProfileEmail() {
      if (!emailInput) {
        return true;
      }

      const value = emailInput.value.trim();

      if (!value) {
        return showFieldError(emailInput, "Email is required.");
      }
      if (!EMAIL_PATTERN.test(value)) {
        return showFieldError(emailInput, "Enter a valid email address.");
      }
      if (emailState.available === false) {
        return showFieldError(emailInput, "This email is already registered.");
      }
      return showFieldError(emailInput, "");
    }

    const debouncedProfileEmailCheck = debounce(function () {
      const value = emailInput.value.trim();
      if (!value || !EMAIL_PATTERN.test(value)) {
        return;
      }
      showFieldNote(emailInput, "Checking availability...");
      checkAvailability("email", value, "&exclude_self=1").then(function (data) {
        if (emailInput.value.trim() !== value) {
          return;
        }
        emailState.available = data ? data.available : null;
        validateProfileEmail();
      });
    }, AVAILABILITY_DEBOUNCE_MS);

    [
      [firstNameInput, "First name", true],
      [middleNameInput, "Middle name", false],
      [lastNameInput, "Last name", true],
    ].forEach(function (entry) {
      const input = entry[0];
      if (!input) {
        return;
      }
      input.addEventListener("input", function () {
        liveCapitalizeName(input);
        validateNameField(input, entry[1], entry[2]);
      });
      input.addEventListener("blur", function () {
        titleCaseName(input);
        validateNameField(input, entry[1], entry[2]);
      });
    });

    if (programSelect) {
      programSelect.addEventListener("change", function () {
        validateSelectField(programSelect, "Program");
      });
    }

    if (collegeSelect) {
      collegeSelect.addEventListener("change", function () {
        validateSelectField(collegeSelect, "College");
      });
    }

    if (emailInput) {
      emailInput.addEventListener("input", function () {
        emailState.available = null;
        validateProfileEmail();
        debouncedProfileEmailCheck();
      });
    }

    const emailConfirmRow = document.getElementById("emailChangeConfirm");
    const currentPasswordInput = document.getElementById("id_current_password");
    const originalEmail = (profileForm.getAttribute("data-original-email") || "").trim().toLowerCase();

    function emailWasChanged() {
      return !!emailInput && emailInput.value.trim().toLowerCase() !== originalEmail;
    }

    function syncEmailConfirmRow() {
      if (!emailConfirmRow) {
        return;
      }
      const changed = emailWasChanged();
      emailConfirmRow.classList.toggle("hidden", !changed);
      if (!changed && currentPasswordInput) {
        currentPasswordInput.value = "";
        showFieldError(currentPasswordInput, "");
      }
    }

    if (emailInput) {
      emailInput.addEventListener("input", syncEmailConfirmRow);
    }
    if (currentPasswordInput) {
      currentPasswordInput.addEventListener("input", function () {
        if (currentPasswordInput.value) {
          showFieldError(currentPasswordInput, "");
        }
      });
    }

    profileForm.addEventListener("submit", function (event) {
      titleCaseName(firstNameInput);
      titleCaseName(middleNameInput);
      titleCaseName(lastNameInput);

      const results = [
        members ? members.validate() : true,
        validateNameField(firstNameInput, "First name", true),
        validateNameField(middleNameInput, "Middle name", false),
        validateNameField(lastNameInput, "Last name", true),
        validateProfileEmail(),
        validateSelectField(programSelect, "Program"),
        validateSelectField(collegeSelect, "College"),
        !emailWasChanged() || (currentPasswordInput && currentPasswordInput.value) ||
          showFieldError(currentPasswordInput, "Enter your current password to change your email."),
      ];

      if (results.indexOf(false) !== -1) {
        event.preventDefault();

        const inputs = [firstNameInput, middleNameInput, lastNameInput, emailInput, currentPasswordInput, programSelect, collegeSelect];
        for (let i = 0; i < inputs.length; i++) {
          if (inputs[i] && inputs[i].style.borderColor) {
            inputs[i].focus();
            break;
          }
        }
      }
    });
  }

  // ---------------------------------------------------------------------
  // Forgot Password: mandatory new password step
  // ---------------------------------------------------------------------

  const resetPasswordForm = document.querySelector("[data-reset-password-form]");

  if (resetPasswordForm) {
    const newPasswordInput = document.getElementById("id_new_password");
    const confirmNewPasswordInput = document.getElementById("id_confirm_new_password");

    if (newPasswordInput) {
      newPasswordInput.addEventListener("input", function () {
        validatePasswordField(newPasswordInput);
        if (confirmNewPasswordInput && confirmNewPasswordInput.value) {
          validateConfirmPasswordField(confirmNewPasswordInput, newPasswordInput);
        }
      });
    }

    if (confirmNewPasswordInput) {
      confirmNewPasswordInput.addEventListener("input", function () {
        validateConfirmPasswordField(confirmNewPasswordInput, newPasswordInput);
      });
    }

    resetPasswordForm.addEventListener("submit", function (event) {
      const passwordOk = validatePasswordField(newPasswordInput);
      const confirmOk = validateConfirmPasswordField(confirmNewPasswordInput, newPasswordInput);

      if (!(passwordOk && confirmOk)) {
        event.preventDefault();
        const invalid = [newPasswordInput, confirmNewPasswordInput].filter(function (input) {
          return input && input.style.borderColor;
        })[0];
        if (invalid) {
          invalid.focus();
        }
      }
    });
  }
});
