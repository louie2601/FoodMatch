// Manage Submissions: the Review / View details popup. Each table row carries
// its details in data-* attributes; pending rows get the Approve / Reject form.
(function () {
  var modal = document.getElementById('submissionModal');
  if (!modal) return;

  var form = document.getElementById('submissionReviewForm');
  var footer = document.getElementById('submissionModalFooter');
  var statusBadge = document.getElementById('submissionModalStatus');
  var fileLink = document.getElementById('submissionModalFile');
  var notesWrap = document.getElementById('submissionModalNotesWrap');
  var lastTrigger = null;

  var BADGE = {
    pending: 'bg-amber-50 text-amber-800 ring-1 ring-amber-200',
    approved: 'bg-emerald-50 text-emerald-800 ring-1 ring-emerald-200',
    rejected: 'bg-rose-50 text-rose-700 ring-1 ring-rose-200'
  };

  function setText(id, value, fallback) {
    document.getElementById(id).textContent = value || fallback || '—';
  }

  function openModal(row, trigger) {
    var d = row.dataset;
    var pending = d.statusKey === 'pending';
    lastTrigger = trigger;

    statusBadge.className = 'inline-flex items-center rounded-full px-2.5 py-0.5 text-xs font-semibold ' + (BADGE[d.statusKey] || BADGE.pending);
    statusBadge.textContent = d.status || '';
    setText('submissionModalTitle', d.title);
    setText('submissionModalMeta', d.student + ' · Submitted ' + d.submitted + (d.reviewed ? ' · ' + d.status + ' ' + d.reviewed : ''));
    setText('submissionModalAuthors', d.authors);
    setText('submissionModalAdviser', d.adviser);
    setText('submissionModalCategory', d.category);
    setText('submissionModalPublished', d.published);
    setText('submissionModalKeywords', d.keywords);
    setText('submissionModalAbstract', d.abstract, 'No abstract provided.');

    if (d.fileUrl) {
      fileLink.href = d.fileUrl;
      setText('submissionModalFileText', 'Open uploaded file' + (d.docType ? ' (' + d.docType + ')' : ''));
      fileLink.classList.remove('hidden');
      fileLink.classList.add('inline-flex');
    } else {
      fileLink.classList.add('hidden');
      fileLink.classList.remove('inline-flex');
    }

    notesWrap.classList.toggle('hidden', !d.notes);
    setText('submissionModalNotes', d.notes);

    form.classList.toggle('hidden', !pending);
    footer.classList.toggle('hidden', pending);
    if (pending) {
      document.getElementById('submissionReviewId').value = d.id;
      document.getElementById('submissionReviewNotes').value = '';
      form.querySelectorAll('button[type="submit"]').forEach(function (button) { button.disabled = false; });
    }

    modal.classList.remove('hidden');
    modal.classList.add('flex');
    modal.setAttribute('aria-hidden', 'false');
    document.body.classList.add('overflow-hidden');
    (pending ? document.getElementById('submissionReviewNotes') : modal.querySelector('[data-close-submission-modal][aria-label]')).focus();
  }

  function closeModal() {
    modal.classList.add('hidden');
    modal.classList.remove('flex');
    modal.setAttribute('aria-hidden', 'true');
    document.body.classList.remove('overflow-hidden');
    if (lastTrigger) lastTrigger.focus();
  }

  document.querySelectorAll('[data-open-submission]').forEach(function (button) {
    button.addEventListener('click', function () {
      openModal(button.closest('[data-submission-row]'), button);
    });
  });
  modal.querySelectorAll('[data-close-submission-modal]').forEach(function (el) {
    el.addEventListener('click', closeModal);
  });
  document.addEventListener('keydown', function (event) {
    if (event.key === 'Escape' && !modal.classList.contains('hidden')) closeModal();
  });

  // One click = one review: disable the buttons once the form is on its way
  // (after the browser has read which button was pressed).
  form.addEventListener('submit', function () {
    setTimeout(function () {
      form.querySelectorAll('button[type="submit"]').forEach(function (button) { button.disabled = true; });
    }, 0);
  });
})();
