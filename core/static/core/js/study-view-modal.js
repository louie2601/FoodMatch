window.addEventListener("DOMContentLoaded", function () {
  const modal = document.getElementById("studyViewModal");
  const panel = document.getElementById("studyViewModalPanel");
  if (!modal || !panel) return;
  const uploadLabel = modal.getAttribute("data-upload-label") || "Your file";

  const FIELDS = [
    { key: "authors",             label: "Authors / Researchers",  dataAttr: "authors",                  span: 2, always: true },
    { key: "submitter",           label: "Submitted By (Uploader)",dataAttr: "submitter-name",           span: 1, always: false },
    { key: "adviser",             label: "Adviser",                dataAttr: "adviser",                  span: 1, always: false },
    { key: "program",             label: "Program / Course",       dataAttr: "submitter-program",        span: 1, always: false },
    { key: "college",             label: "College / Department",   dataAttr: "submitter-college",        span: 1, always: false },
    { key: "login_as",            label: "Researcher Role",        dataAttr: "submitter-login-as",       span: 1, always: false, formatter: v => v ? v.charAt(0).toUpperCase() + v.slice(1) : "" },
    { key: "status",              label: "Submission Status",      dataAttr: "status",                   span: 1, always: false, formatter: v => v ? v.charAt(0).toUpperCase() + v.slice(1) : "" },
    { key: "submitted_at",        label: "Submitted",              dataAttr: "submitted-at",             span: 1, always: false, formatter: formatDateIso },
    { key: "reviewed_at",         label: "Approved / Reviewed",    dataAttr: "reviewed-at",              span: 1, always: false, formatter: formatDateIso },
    { key: "published_month",     label: "Published Month",        dataAttr: "published-month",          span: 1, always: false },
    { key: "published_year",      label: "Published Year",         dataAttr: "published-year",           span: 1, always: false },
    { key: "school_year",         label: "School Year",            dataAttr: "__school_year__",          span: 1, always: false },
    { key: "email",               label: "Researcher Email",       dataAttr: "submitter-email",          span: 2, always: false },
    { key: "keywords",            label: "Keywords",               dataAttr: "keywords",                 span: 2, always: false },
  ];

  const LEVEL_META = {
    low:      { banner: "bg-emerald-50 text-emerald-700 ring-emerald-100",   labelChip: "bg-emerald-100 text-emerald-700",   levelChip: "bg-emerald-50 text-emerald-700 ring-emerald-200",   levelText: "● Low match" },
    moderate: { banner: "bg-amber-50 text-amber-700 ring-amber-100",      labelChip: "bg-amber-100 text-amber-800",      levelChip: "bg-amber-50 text-amber-700 ring-amber-200",      levelText: "● Moderate match" },
    high:     { banner: "bg-rose-50 text-rose-700 ring-rose-100",          labelChip: "bg-rose-100 text-rose-700",          levelChip: "bg-rose-50 text-rose-700 ring-rose-200",          levelText: "● High match" },
  };

  const els = {
    title:       document.getElementById("studyViewModalTitle"),
    authors:     document.getElementById("studyViewModalAuthors"),
    scorePct:    document.getElementById("studyViewModalScorePct"),
    scoreLabel:  document.getElementById("studyViewModalScoreLabel"),
    levelPill:   document.getElementById("studyViewModalLevelPill"),
    scoreBanner: document.getElementById("studyViewScoreBanner"),
    abstract:    document.getElementById("studyViewModalAbstract"),
    infoGrid:    document.getElementById("studyInfoGrid"),
    basisGrid:   document.getElementById("studyViewBasisGrid"),
    metadataOnlyNote: document.getElementById("studyViewMetadataOnlyNote"),
    matchDetails: document.getElementById("studyViewMatchDetails"),
  };

  const BASIS_FIELDS = [
    { key: "ingredients", label: "Ingredients", hint: "Materials & procedure" },
    { key: "general",     label: "Rest of Paper", hint: "" },
    { key: "title",       label: "Title",       hint: "" },
    { key: "abstract",    label: "Abstract",    hint: "" },
  ];

  function toNum(value) {
    const n = value && !Number.isNaN(parseFloat(value)) ? parseFloat(value) : 0;
    return n;
  }

  // The number in the big text is the RAW match strength for that piece alone
  // (0-100%) — it is not capped by its weight. The weight badge is how much
  // that piece counts toward the total for THIS match; it can differ from the
  // nominal 30/30/20/20 split when a piece has no data to compare (e.g. a
  // repository entry with no uploaded document redistributes its 60% onto
  // Title/Abstract) — "Contributes" is raw score × that weight.
  function buildBasisCell(field, rawValue, weightValue) {
    const pct = toNum(rawValue);
    const weight = toNum(weightValue);
    const contributes = Math.round((pct * weight) / 100 * 10) / 10;
    return `
      <div class="rounded-2xl border border-slate-100 bg-slate-50/50 px-3 py-2.5 text-center">
        <p class="text-[10px] font-bold uppercase tracking-[0.12em] text-slate-500">${escapeHtml(field.label)}</p>
        <p class="mt-1 text-lg font-black text-slate-900">${pct}%</p>
        <p class="text-[9px] font-semibold text-slate-400">weight ${weight}% &rarr; ${contributes} pts</p>
        ${field.hint ? `<p class="text-[9px] text-slate-400">${escapeHtml(field.hint)}</p>` : ""}
      </div>`;
  }

  // The AI language model's meaning score decides the Overall score; the
  // weighted TF-IDF score only counts when it shows a near-exact copy (80%+).
  function buildMeaningCell(rawValue, tfidfValue) {
    const has = rawValue !== "" && rawValue != null;
    const tfidf = tfidfValue !== "" && tfidfValue != null ? toNum(tfidfValue) : null;
    return `
      <div class="col-span-2 rounded-2xl border border-emerald-100 bg-emerald-50/60 px-3 py-2.5 text-center sm:col-span-4">
        <p class="text-[10px] font-bold uppercase tracking-[0.12em] text-emerald-700">Meaning · AI model (Sentence-BERT)</p>
        <p class="mt-1 text-lg font-black text-slate-900">${has ? toNum(rawValue) + "%" : "—"}</p>
        <p class="text-[9px] font-semibold text-slate-500">${has
          ? "share of your passages with the same meaning as this study · this decides the Overall score"
          : "not used for this study (no document on file, or the AI model is off) · TF-IDF decides"}</p>
        ${tfidf != null ? `<p class="mt-1 text-[9px] font-semibold text-slate-500">Weighted TF-IDF: ${tfidf}%${has ? " · counts toward Overall only at 80%+ (a near-exact copy)" : ""}</p>` : ""}
      </div>`;
  }

  // "What Matched": one card per part with the shared key terms and, when the
  // server found one, the closest passage pair. Segments come pre-split by the
  // server as {t: text, m: shared-word?}; every piece is escaped here.
  function renderSegments(segments) {
    return (segments || []).map(function (seg) {
      const text = escapeHtml(seg.t);
      return seg.m ? `<mark class="rounded bg-amber-100 px-0.5 text-amber-900">${text}</mark>` : text;
    }).join("");
  }

  function buildPassage(label, segments) {
    return `
      <div class="rounded-xl bg-white px-3 py-2.5 ring-1 ring-slate-100">
        <p class="text-[10px] font-bold uppercase tracking-[0.14em] text-slate-400">${escapeHtml(label)}</p>
        <p class="mt-1 text-[13px] leading-6 text-slate-700">${renderSegments(segments)}</p>
      </div>`;
  }

  function buildMatchCard(section, scoreValue) {
    const score = toNum(scoreValue);
    let body = "";
    if (!section.available) {
      body = `<p class="mt-1.5 text-xs italic text-slate-500">${escapeHtml(section.note)}</p>`;
    } else {
      if (section.terms && section.terms.length) {
        body += `<div class="mt-2 flex flex-wrap gap-1.5">` + section.terms.map(function (term) {
          return `<span class="rounded-full bg-emerald-50 px-2.5 py-0.5 text-xs font-semibold text-emerald-800 ring-1 ring-emerald-100">${escapeHtml(term)}</span>`;
        }).join("") + `</div>`;
      } else if (section.note) {
        body += `<p class="mt-1.5 text-xs italic text-slate-500">${escapeHtml(section.note)}</p>`;
      }
      if (section.yours && section.yours.length) {
        const passageLabel = section.key === "title" ? "" : (section.passage_score != null ? `Closest passages · ${section.passage_score}% alike` : "");
        body += `
          ${passageLabel ? `<p class="mt-3 text-[10px] font-bold uppercase tracking-[0.14em] text-slate-500">${escapeHtml(passageLabel)}</p>` : ""}
          <div class="mt-2 grid gap-2 sm:grid-cols-2">
            ${buildPassage(uploadLabel, section.yours)}
            ${buildPassage("Matched study", section.theirs)}
          </div>`;
      } else if (section.key !== "title" && section.terms && section.terms.length) {
        body += `<p class="mt-2 text-xs text-slate-500">No single passage is close enough to show side by side.</p>`;
      }
    }
    return `
      <div class="rounded-2xl border border-slate-100 bg-slate-50/50 px-4 py-3">
        <div class="flex items-center justify-between gap-3">
          <p class="text-xs font-bold uppercase tracking-[0.12em] text-slate-700">${escapeHtml(section.label)}</p>
          <span class="text-sm font-black text-slate-900">${score}%</span>
        </div>
        ${body}
      </div>`;
  }

  function renderMatchDetails(article) {
    if (!els.matchDetails) return;
    let sections = [];
    try {
      sections = JSON.parse(article.getAttribute("data-match-details") || "[]");
    } catch (e) {
      sections = [];
    }
    if (!Array.isArray(sections) || !sections.length) {
      els.matchDetails.innerHTML = '<p class="text-xs italic text-slate-500">No match details for this study.</p>';
      return;
    }
    els.matchDetails.innerHTML = sections.map(function (section) {
      return buildMatchCard(section, readData(article, section.key + "-score"));
    }).join("");
  }

  let lastTrigger = null;

  // Dates and times always show in Philippine time, whatever clock the
  // viewer's computer is set to.
  const SITE_TIME_ZONE = "Asia/Manila";

  function formatDateIso(iso) {
    if (!iso) return "";
    try {
      const d = new Date(iso);
      if (Number.isNaN(d.getTime())) return "";
      // A plain date ("2025-01-15") has no time, so don't invent one.
      const opts = /^\d{4}-\d{2}-\d{2}$/.test(String(iso).trim())
        ? { month: "short", day: "numeric", year: "numeric", timeZone: "UTC" }
        : { month: "short", day: "numeric", year: "numeric", hour: "numeric", minute: "2-digit", timeZone: SITE_TIME_ZONE };
      return d.toLocaleDateString(undefined, opts);
    } catch (e) {
      return "";
    }
  }

  function escapeHtml(str) {
    return String(str == null ? "" : str)
      .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;").replace(/'/g, "&#039;");
  }

  function readData(article, name) {
    const v = article.getAttribute("data-" + name);
    return v == null ? "" : String(v).trim();
  }

  function buildInfoCell(field, rawValue) {
    const label = field.label;
    const span = field.span === 2 ? "sm:col-span-2" : "";
    const displayVal = rawValue && String(rawValue).trim() ? rawValue : "—";
    return `
      <div class="info-cell rounded-2xl border border-slate-100 bg-slate-50/50 px-4 py-3 sm:px-5 sm:py-3.5 ${span}">
        <p class="text-[10.5px] font-bold uppercase tracking-[0.16em] text-slate-500">${escapeHtml(label)}</p>
        <p class="mt-1 text-sm font-bold leading-snug text-slate-900 sm:text-[15px]">${escapeHtml(displayVal)}</p>
      </div>`;
  }

  function populateFromArticle(article) {
    const get = (name) => readData(article, name);
    const title = get("title");
    const authorsRaw = get("authors");
    const submitterRaw = get("submitter-name");
    if (els.title)   els.title.textContent   = title;
    if (els.authors) {
      if (authorsRaw && authorsRaw.trim()) {
        els.authors.textContent = "by " + authorsRaw;
      } else if (submitterRaw && submitterRaw.trim()) {
        els.authors.textContent = "Submitted by " + submitterRaw + " (authors not specified)";
      } else {
        els.authors.textContent = "";
      }
    }

    const level = get("similarity-level") || "low";
    const meta  = LEVEL_META[level] || LEVEL_META.low;

    if (els.scoreBanner) {
      els.scoreBanner.className = "mb-5 flex items-center justify-between gap-4 rounded-2xl px-5 py-4 ring-1 " + meta.banner;
    }
    if (els.scorePct)    els.scorePct.textContent   = get("score-percent") + "%";
    if (els.scoreLabel) {
      els.scoreLabel.textContent = get("similarity-label");
      els.scoreLabel.className   = "inline-flex rounded-full px-2.5 py-1 text-[10px] font-semibold uppercase tracking-[0.12em] ring-1 ring-black/5 " + meta.labelChip;
    }
    if (els.levelPill) {
      els.levelPill.textContent = meta.levelText;
      els.levelPill.className   = "inline-flex flex-none items-center gap-1.5 rounded-full px-3.5 py-2 text-[11px] font-bold uppercase tracking-wider ring-1 " + meta.levelChip;
    }

    if (els.basisGrid) {
      els.basisGrid.innerHTML = BASIS_FIELDS.map(function (field) {
        return buildBasisCell(field, get(field.key + "-score"), get(field.key + "-weight"));
      }).join("") + buildMeaningCell(get("meaning-score"), get("tfidf-score"));
    }
    if (els.metadataOnlyNote) {
      els.metadataOnlyNote.classList.toggle("hidden", get("metadata-only") !== "true");
    }
    renderMatchDetails(article);

    const abstractRaw = get("abstract");
    if (els.abstract) {
      if (abstractRaw) {
        els.abstract.innerHTML = escapeHtml(abstractRaw).replace(/\n/g, "<br>");
      } else {
        els.abstract.innerHTML = '<span class="italic text-slate-500">No abstract on record for this study.</span>';
      }
    }

    const html = FIELDS.map(function (field) {
      let val = "";
      if (field.dataAttr === "__school_year__") {
        const yRaw = get("published-year");
        const mRaw = (get("published-month") || "").trim();
        if (yRaw) {
          const y = parseInt(String(yRaw).trim(), 10);
          if (!Number.isNaN(y) && y >= 1900 && y <= 2199) {
            let start = y;
            let end = y + 1;
            if (mRaw && /^(january|february|march|april|may|june)$/i.test(mRaw)) {
              start = y - 1;
              end = y;
            }
            val = "SY " + start + " - " + end;
          }
        }
      } else {
        val = get(field.dataAttr);
        if (typeof field.formatter === "function") {
          val = field.formatter(val);
        }
      }
      const hasValue = !!(val && String(val).trim());
      if (!field.always && !hasValue) return "";
      return buildInfoCell(field, val || "");
    }).join("");

    if (els.infoGrid) els.infoGrid.innerHTML = html;
  }

  function openModal(triggerEl) {
    lastTrigger = triggerEl;
    const article = triggerEl && triggerEl.closest ? triggerEl.closest("[data-study-id]") : null;
    if (!article) return;
    populateFromArticle(article);
    modal.classList.remove("hidden");
    modal.classList.add("flex");
    modal.setAttribute("aria-hidden", "false");
    document.body.style.overflow = "hidden";
    const firstFocusable = panel.querySelector("button, [href], input, select, textarea, [tabindex]:not([tabindex='-1'])");
    if (firstFocusable) {
      try { firstFocusable.focus(); } catch (e) {}
    }
  }

  function closeModal() {
    modal.classList.add("hidden");
    modal.classList.remove("flex");
    modal.setAttribute("aria-hidden", "true");
    document.body.style.overflow = "";
    if (lastTrigger && typeof lastTrigger.focus === "function") {
      try { lastTrigger.focus(); } catch (e) {}
    }
    lastTrigger = null;
  }

  window.openStudyViewModal  = openModal;
  window.closeStudyViewModal = closeModal;

  document.addEventListener("click", function (e) {
    const btnOpen  = e.target.closest("[data-trigger-study-view]");
    const btnClose = e.target.closest("[data-close-study-view]");
    if (btnOpen) {
      e.preventDefault();
      openModal(btnOpen);
      return;
    }
    if (btnClose) {
      e.preventDefault();
      closeModal();
      return;
    }
    if (e.target === modal) {
      closeModal();
    }
  });

  document.addEventListener("keydown", function (e) {
    if (e.key === "Escape" && !modal.classList.contains("hidden")) {
      closeModal();
    }
  });
});
