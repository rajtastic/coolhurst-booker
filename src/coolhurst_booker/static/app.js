const TIME_BUCKETS = {
  morning: { label: "Morning", start: 0, end: 12 },
  afternoon: { label: "Afternoon", start: 12, end: 17 },
  evening: { label: "Evening", start: 17, end: 24 },
};

const state = {
  slots: [],
  personSlots: [],
  summary: [],
  selectedDate: null,
  surfaceFilter: "all",
  timeFilter: "all",
  calendarFilter: "both",
  health: null,
  config: {
    booker_name: "Roshan",
    appointment_url: "",
    coolhurst_book_url: "https://coolhurst.clubsolution.co.uk/newlook/proc_baner.asp",
    scrape_interval_seconds: 300,
    health_warn_after_seconds: 300,
    health_stale_after_seconds: 3600,
    show_public_court_calendar_link: true,
  },
};

const el = {
  dayStrip: document.getElementById("day-strip"),
  dayPanel: document.getElementById("day-panel"),
  loading: document.getElementById("loading"),
  lastUpdatedCourts: document.getElementById("last-updated-courts"),
  lastUpdatedPerson: document.getElementById("last-updated-person"),
  totalSlots: document.getElementById("total-slots"),
  sourceBanner: document.getElementById("source-banner"),
  surfaceFilters: document.getElementById("surface-filters"),
  timeFilters: document.getElementById("time-filters"),
  calendarFilters: document.getElementById("calendar-filters"),
  chipPerson: document.getElementById("chip-person"),
  heroTitle: document.getElementById("hero-title"),
  heroLead: document.getElementById("hero-lead"),
  footerNote: document.getElementById("footer-note"),
  publicCalendarFooter: document.getElementById("public-calendar-footer"),
  publicCalendarLink: document.getElementById("public-calendar-link"),
  bookModal: document.getElementById("book-modal"),
  bookModalSlot: document.getElementById("book-modal-slot"),
  bookModalStatus: document.getElementById("book-modal-status"),
  bookModalHint: document.getElementById("book-modal-hint"),
  bookModalStale: document.getElementById("book-modal-stale"),
  bookModalActions: document.getElementById("book-modal-actions"),
  bookModalVerify: document.getElementById("book-modal-verify"),
  bookModalFallback: document.getElementById("book-modal-fallback"),
  bookAppointmentLink: document.getElementById("book-appointment-link"),
  bookCourtLink: document.getElementById("book-court-link"),
  verifyCourtLink: document.getElementById("verify-court-link"),
  verifyPersonLink: document.getElementById("verify-person-link"),
  switchToBoth: document.getElementById("switch-to-both"),
  bookModalTitle: document.getElementById("book-modal-title"),
};

function parseTime(t) {
  const [h, m] = t.split(":").map(Number);
  return h * 60 + m;
}

function formatTimeRange(start, end) {
  return `${start} – ${end}`;
}

function getSurface(court) {
  const lower = court.toLowerCase();
  if (lower.includes("clay")) return "clay";
  if (lower.includes("astro")) return "astro";
  return "other";
}

function surfaceLabel(surface) {
  if (surface === "clay") return "Clay";
  if (surface === "astro") return "Astro";
  return "Court";
}

function matchesTimeFilter(slot) {
  if (state.timeFilter === "all") return true;
  const bucket = TIME_BUCKETS[state.timeFilter];
  if (!bucket) return true;
  const hour = parseInt(slot.start_time.split(":")[0], 10);
  return hour >= bucket.start && hour < bucket.end;
}

function matchesSurfaceFilter(slot) {
  if (state.surfaceFilter === "all") return true;
  return getSurface(slot.court) === state.surfaceFilter;
}

function sourceAgeSeconds(source) {
  const info = state.health?.scrapers?.[source];
  if (!info) return null;
  if (typeof info.age_seconds === "number") return info.age_seconds;
  return null;
}

function sourceFreshness(source) {
  const age = sourceAgeSeconds(source);
  if (age == null) return "unknown";
  const warn = state.config.health_warn_after_seconds || 300;
  const stale = state.config.health_stale_after_seconds || 3600;
  if (age > stale) return "stale";
  if (age > warn) return "warn";
  return "fresh";
}

function isSourceDegraded(source) {
  const freshness = sourceFreshness(source);
  if (freshness === "stale" || freshness === "unknown") return true;
  if (source === "google" && state.personSlots.length === 0) return true;
  if (source === "coolhurst" && state.slots.length === 0) return true;
  return false;
}

function isSourceAging(source) {
  const freshness = sourceFreshness(source);
  return freshness === "warn" || freshness === "stale" || freshness === "unknown";
}

/** Effective display mode when Calendar filter is Both and one source is unavailable. */
function bothEffectiveMode() {
  const personBad = isSourceDegraded("google");
  const courtsBad = isSourceDegraded("coolhurst");
  if (!personBad && !courtsBad) return "both";
  if (!courtsBad && personBad) return "courts";
  if (!personBad && courtsBad) return "person";
  return "both";
}

function activeDisplayMode() {
  if (state.calendarFilter === "both") return bothEffectiveMode();
  return state.calendarFilter;
}

function matchesCalendarFilter(slot) {
  const mode = activeDisplayMode();
  if (mode === "courts") return true;
  if (mode === "both") return Boolean(slot.person_available);
  return true;
}

function filterCourtSlots(slots) {
  return slots.filter(
    (s) => matchesSurfaceFilter(s) && matchesTimeFilter(s) && matchesCalendarFilter(s)
  );
}

function filterPersonSlots(slots) {
  return slots.filter((s) => matchesTimeFilter(s));
}

function visibleSlotsForDate(date) {
  if (activeDisplayMode() === "person") {
    return filterPersonSlots(state.personSlots.filter((s) => s.date === date));
  }
  return filterCourtSlots(state.slots.filter((s) => s.date === date));
}

function allVisibleSlots() {
  if (activeDisplayMode() === "person") {
    return filterPersonSlots(state.personSlots);
  }
  return filterCourtSlots(state.slots);
}

function filtersActive() {
  return (
    state.surfaceFilter !== "all" ||
    state.timeFilter !== "all" ||
    state.calendarFilter !== "courts"
  );
}

function formatDateLong(dateStr) {
  const d = new Date(dateStr + "T12:00:00");
  return d.toLocaleDateString("en-GB", {
    weekday: "long",
    day: "numeric",
    month: "long",
  });
}

function formatDateShort(dateStr) {
  const d = new Date(dateStr + "T12:00:00");
  return {
    dow: d.toLocaleDateString("en-GB", { weekday: "short" }),
    day: d.getDate(),
    month: d.toLocaleDateString("en-GB", { month: "short" }),
    isWeekend: d.getDay() === 0 || d.getDay() === 6,
    isToday: dateStr === todayStr(),
  };
}

function todayStr() {
  const now = new Date();
  const local = new Date(now.getTime() - now.getTimezoneOffset() * 60000);
  return local.toISOString().slice(0, 10);
}

function groupByTimeOfDay(slots) {
  const groups = { morning: [], afternoon: [], evening: [] };
  for (const slot of slots) {
    const hour = parseInt(slot.start_time.split(":")[0], 10);
    if (hour < 12) groups.morning.push(slot);
    else if (hour < 17) groups.afternoon.push(slot);
    else groups.evening.push(slot);
  }
  for (const key of Object.keys(groups)) {
    groups[key].sort(
      (a, b) =>
        parseTime(a.start_time) - parseTime(b.start_time) ||
        String(a.court || "").localeCompare(String(b.court || ""), undefined, { numeric: true })
    );
  }
  return groups;
}

function courtLabel(slot) {
  if (!slot.court) return { courtName: "Available", detail: "" };
  const courtNum = slot.court.match(/^(\d+)/)?.[1] || "";
  const courtName = courtNum ? `Court ${courtNum}` : slot.court;
  const detail = slot.court.replace(/^\d+\s*-\s*/, "");
  return { courtName, detail };
}

function stripDates() {
  const today = todayStr();
  if (activeDisplayMode() === "person") {
    return [...new Set(state.personSlots.map((s) => s.date))]
      .filter((d) => d >= today)
      .sort();
  }
  return state.summary.map((s) => s.date).filter((d) => d >= today).sort();
}

function countForDate(date) {
  if (activeDisplayMode() === "person") {
    return filterPersonSlots(state.personSlots.filter((s) => s.date === date)).length;
  }
  if (activeDisplayMode() === "both" || filtersActive()) {
    return filterCourtSlots(state.slots.filter((s) => s.date === date)).length;
  }
  const summary = state.summary.find((s) => s.date === date);
  return summary?.slot_count ?? 0;
}

function ensureSelectedDate() {
  const dates = stripDates();
  if (!dates.length) {
    state.selectedDate = null;
    return;
  }

  const today = todayStr();
  const currentCount = state.selectedDate ? countForDate(state.selectedDate) : 0;
  const selectedMissing = !state.selectedDate || !dates.includes(state.selectedDate);

  if (selectedMissing || currentCount === 0) {
    const withMatches = dates.find((d) => d >= today && countForDate(d) > 0);
    state.selectedDate =
      withMatches || dates.find((d) => countForDate(d) > 0) || dates.find((d) => d >= today) || dates[0];
  }
}

function escapeAttr(value) {
  return String(value)
    .replace(/&/g, "&amp;")
    .replace(/"/g, "&quot;")
    .replace(/</g, "&lt;");
}

function escapeHtml(value) {
  return String(value)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;");
}

function intervalsOverlap(aStart, aEnd, bStart, bEnd) {
  return parseTime(aStart) < parseTime(bEnd) && parseTime(aEnd) > parseTime(bStart);
}

function personFreeAt(date, start, end) {
  return state.personSlots.some(
    (p) => p.date === date && intervalsOverlap(start, end, p.start_time, p.end_time)
  );
}

function courtsFreeAt(date, start, end) {
  return state.slots.filter(
    (c) => c.date === date && intervalsOverlap(start, end, c.start_time, c.end_time)
  );
}

function availabilityForSlot(slot) {
  const mode = slot.mode || activeDisplayMode();
  if (mode === "both") {
    return { person: true, court: true, matchingCourts: slot.court ? [slot] : [] };
  }
  if (mode === "courts") {
    const person =
      slot.person_available === true || slot.person_available === "true"
        ? true
        : personFreeAt(slot.date, slot.start_time, slot.end_time);
    return {
      person,
      court: true,
      matchingCourts: slot.court ? [slot] : courtsFreeAt(slot.date, slot.start_time, slot.end_time),
    };
  }
  const matchingCourts = courtsFreeAt(slot.date, slot.start_time, slot.end_time);
  return {
    person: true,
    court: matchingCourts.length > 0,
    matchingCourts,
  };
}

function statusItem(label, ok) {
  return `<li class="modal__status-item modal__status-item--${ok ? "ok" : "no"}">
    <span class="modal__status-mark" aria-hidden="true">${ok ? "✓" : "×"}</span>
    <span>${escapeHtml(label)}</span>
  </li>`;
}

function selectCalendarFilter(filter) {
  state.calendarFilter = filter;
  el.calendarFilters.querySelectorAll(".chip").forEach((c) => {
    c.classList.toggle("chip--active", c.dataset.calendar === filter);
  });
  closeBookModal();
  refreshViews();
}

function slotStaleClass(forCourts, forPerson) {
  const courtsAging = forCourts && isSourceAging("coolhurst");
  const personAging = forPerson && isSourceAging("google");
  if (
    (courtsAging && sourceFreshness("coolhurst") === "stale") ||
    (personAging && sourceFreshness("google") === "stale")
  ) {
    return "slot-card--stale";
  }
  if (courtsAging || personAging) return "slot-card--warn";
  return "";
}

function renderCourtSlotCard(slot) {
  const surface = getSurface(slot.court);
  const { courtName, detail } = courtLabel(slot);
  const mode = activeDisplayMode();
  const clickable = mode === "both" || mode === "courts";
  const staleClass = slotStaleClass(true, mode === "both");
  const attrs = clickable
    ? `role="button" tabindex="0" data-mode="${mode}" data-slot-date="${slot.date}" data-slot-start="${slot.start_time}" data-slot-end="${slot.end_time}" data-slot-court="${escapeAttr(slot.court)}" data-person-available="${slot.person_available ? "true" : "false"}" class="slot-card slot-card--clickable ${staleClass}"`
    : `class="slot-card ${staleClass}"`;

  const staleNote =
    staleClass === "slot-card--stale"
      ? `<span class="slot-card__stale">May be outdated</span>`
      : staleClass === "slot-card--warn"
        ? `<span class="slot-card__stale slot-card__stale--warn">Check freshness</span>`
        : "";

  return `
    <article ${attrs}>
      <div class="slot-card__time">${formatTimeRange(slot.start_time, slot.end_time)}</div>
      <div class="slot-card__court">${courtName}${detail ? ` · ${detail}` : ""}</div>
      <span class="surface-badge surface-badge--${surface}">${surfaceLabel(surface)}</span>
      ${staleNote}
    </article>
  `;
}

function renderPersonSlotCard(slot) {
  const name = state.config.booker_name;
  const staleClass = slotStaleClass(false, true);
  const staleNote =
    staleClass === "slot-card--stale"
      ? `<span class="slot-card__stale">May be outdated</span>`
      : staleClass === "slot-card--warn"
        ? `<span class="slot-card__stale slot-card__stale--warn">Check freshness</span>`
        : "";
  return `
    <article role="button" tabindex="0" data-mode="person" data-slot-date="${slot.date}" data-slot-start="${slot.start_time}" data-slot-end="${slot.end_time}" class="slot-card slot-card--clickable ${staleClass}">
      <div class="slot-card__time">${formatTimeRange(slot.start_time, slot.end_time)}</div>
      <div class="slot-card__court">${escapeHtml(name)} free</div>
      <span class="surface-badge surface-badge--astro">Calendar</span>
      ${staleNote}
    </article>
  `;
}

function bindSlotClicks() {
  el.dayPanel.querySelectorAll(".slot-card--clickable").forEach((card) => {
    const open = () =>
      openBookModal({
        mode: card.dataset.mode,
        date: card.dataset.slotDate,
        start_time: card.dataset.slotStart,
        end_time: card.dataset.slotEnd,
        court: card.dataset.slotCourt || "",
        person_available: card.dataset.personAvailable === "true",
      });
    card.addEventListener("click", open);
    card.addEventListener("keydown", (e) => {
      if (e.key === "Enter" || e.key === " ") {
        e.preventDefault();
        open();
      }
    });
  });
}

function updateSourceBanner() {
  const name = state.config.booker_name || "Roshan";
  const personBad = isSourceDegraded("google");
  const courtsBad = isSourceDegraded("coolhurst");
  const filter = state.calendarFilter;
  let message = "";

  if (filter === "both") {
    if (!personBad && !courtsBad) {
      message = "";
    } else if (!courtsBad && personBad) {
      message = `Showing courts only — ${name}'s calendar is empty or out of date.`;
    } else if (!personBad && courtsBad) {
      message = `Showing ${name}'s availability only — Coolhurst courts data is empty or out of date.`;
    } else {
      message = "Both calendars are empty or out of date. Verify on the source sites before booking.";
    }
  } else if (filter === "courts" && courtsBad) {
    message = "Coolhurst courts data is empty or out of date.";
  } else if (filter === "person" && personBad) {
    message = `${name}'s calendar is empty or out of date.`;
  }

  if (!message) {
    el.sourceBanner.classList.add("hidden");
    el.sourceBanner.innerHTML = "";
    return;
  }

  const coolhurstUrl = state.config.coolhurst_book_url;
  const appointmentUrl = state.config.appointment_url;
  const showPublic = state.config.show_public_court_calendar_link;
  const links = [];
  if ((courtsBad || filter === "courts") && showPublic && coolhurstUrl) {
    links.push(
      `<a href="${escapeAttr(coolhurstUrl)}" target="_blank" rel="noopener">Check Coolhurst court calendar</a>`
    );
  }
  if ((personBad || filter === "person") && appointmentUrl) {
    links.push(
      `<a href="${escapeAttr(appointmentUrl)}" target="_blank" rel="noopener">Check ${escapeHtml(name)}'s availability</a>`
    );
  }

  el.sourceBanner.classList.remove("hidden");
  el.sourceBanner.innerHTML = `<p>${escapeHtml(message)}</p>${
    links.length ? `<p class="source-banner__links">${links.join(" · ")}</p>` : ""
  }`;
}

function renderDayPanel() {
  const date = state.selectedDate;
  const displayMode = activeDisplayMode();
  if (!date) {
    const showPublic = state.config.show_public_court_calendar_link;
    const coolhurstUrl = state.config.coolhurst_book_url;
    el.dayPanel.innerHTML = `
      <div class="empty-state">
        <div class="empty-icon">🎾</div>
        <h3>No slots to show</h3>
        <p>Wait for the next scrape, or switch Calendar filters.</p>
        ${
          showPublic && coolhurstUrl
            ? `<p><a href="${escapeAttr(coolhurstUrl)}" target="_blank" rel="noopener">Check Coolhurst court calendar</a></p>`
            : ""
        }
      </div>
    `;
    return;
  }

  const daySlots = visibleSlotsForDate(date);
  const groups = groupByTimeOfDay(daySlots);
  const short = formatDateShort(date);
  const name = state.config.booker_name;
  const renderCard = displayMode === "person" ? renderPersonSlotCard : renderCourtSlotCard;

  let sections = "";
  for (const [key, bucket] of Object.entries(TIME_BUCKETS)) {
    const items = groups[key];
    if (!items.length) continue;
    if (state.timeFilter !== "all" && state.timeFilter !== key) continue;

    sections += `
      <div class="time-section">
        <h3 class="time-section__title">${bucket.label}</h3>
        <div class="slot-grid">
          ${items.map(renderCard).join("")}
        </div>
      </div>
    `;
  }

  let subtitle;
  if (daySlots.length === 0) {
    subtitle = "No slots match your filters";
  } else if (displayMode === "both") {
    subtitle = `${daySlots.length} slot${daySlots.length === 1 ? "" : "s"} free for you and ${name}`;
  } else if (displayMode === "person") {
    subtitle = `${daySlots.length} open window${daySlots.length === 1 ? "" : "s"} on ${name}'s calendar`;
  } else {
    subtitle = `${daySlots.length} court${daySlots.length === 1 ? "" : "s"} available`;
  }

  if (!sections) {
    el.dayPanel.innerHTML = `
      <div class="day-header">
        <h2>${formatDateLong(date)}</h2>
        <p>${subtitle}</p>
      </div>
      <div class="empty-state">
        <div class="empty-icon">🎾</div>
        <h3>No slots to show</h3>
        <p>Try another day or loosen your filters — availability changes throughout the day.</p>
      </div>
    `;
    return;
  }

  let hint = "tap a court to check if it's free for both of you";
  if (displayMode === "both") {
    hint = `tap a time to book with ${name} and reserve a court`;
  } else if (displayMode === "person") {
    hint = `tap a time to see if a court is free then`;
  }

  el.dayPanel.innerHTML = `
    <div class="day-header">
      <h2>${formatDateLong(date)}${short.isToday ? ' <span style="font-size:0.65em;font-weight:500;color:var(--green-mid)">· Today</span>' : ""}</h2>
      <p>${subtitle} — ${hint}</p>
    </div>
    ${sections}
  `;

  bindSlotClicks();
}

function openBookModal(slot) {
  const name = state.config.booker_name;
  const mode = slot.mode || activeDisplayMode();
  const avail = availabilityForSlot(slot);
  const bothFree = avail.person && avail.court;
  const { courtName, detail } = courtLabel(slot);

  let courtBit = "";
  if (slot.court) {
    courtBit = ` · ${courtName}${detail ? ` · ${detail}` : ""}`;
  } else if (avail.matchingCourts.length === 1) {
    const match = courtLabel(avail.matchingCourts[0]);
    courtBit = ` · ${match.courtName}${match.detail ? ` · ${match.detail}` : ""}`;
  } else if (avail.matchingCourts.length > 1) {
    courtBit = ` · ${avail.matchingCourts.length} overlapping courts`;
  }

  el.bookModalTitle.textContent = bothFree ? "Book this slot" : "Not free for both";
  el.bookModalSlot.textContent = `${formatDateLong(slot.date)} · ${formatTimeRange(
    slot.start_time,
    slot.end_time
  )}${courtBit}`;

  el.bookModalStatus.innerHTML = [
    statusItem(
      avail.person ? `${name} is available` : `${name} is not available`,
      avail.person
    ),
    statusItem(
      avail.court
        ? avail.matchingCourts.length > 1
          ? `${avail.matchingCourts.length} courts are available`
          : "A court is available"
        : "No court is available",
      avail.court
    ),
  ].join("");

  el.bookAppointmentLink.textContent = `Book with ${name}`;
  el.bookAppointmentLink.href = state.config.appointment_url || "#";
  el.bookCourtLink.href = state.config.coolhurst_book_url || "#";

  const courtsAging = isSourceAging("coolhurst");
  const personAging = isSourceAging("google");
  const staleNotes = [];
  if (courtsAging) {
    const label =
      sourceFreshness("coolhurst") === "stale" ? "out of date" : "may be aging";
    staleNotes.push(`Coolhurst courts data is ${label}.`);
  }
  if (personAging) {
    const label = sourceFreshness("google") === "stale" ? "out of date" : "may be aging";
    staleNotes.push(`${name}'s calendar is ${label}.`);
  }

  if (staleNotes.length) {
    el.bookModalStale.classList.remove("hidden");
    el.bookModalStale.classList.toggle(
      "modal__stale--stale",
      sourceFreshness("coolhurst") === "stale" || sourceFreshness("google") === "stale"
    );
    el.bookModalStale.classList.toggle(
      "modal__stale--warn",
      !(sourceFreshness("coolhurst") === "stale" || sourceFreshness("google") === "stale")
    );
    el.bookModalStale.textContent = `${staleNotes.join(" ")} Confirm on the source site before booking.`;
  } else {
    el.bookModalStale.classList.add("hidden");
    el.bookModalStale.textContent = "";
  }

  const showVerifyCourt =
    courtsAging && state.config.show_public_court_calendar_link && state.config.coolhurst_book_url;
  const showVerifyPerson = personAging && state.config.appointment_url;

  el.verifyCourtLink.href = state.config.coolhurst_book_url || "#";
  el.verifyPersonLink.href = state.config.appointment_url || "#";
  el.verifyPersonLink.textContent = `Check ${name}'s availability`;
  el.verifyCourtLink.classList.toggle("hidden", !showVerifyCourt);
  el.verifyPersonLink.classList.toggle("hidden", !showVerifyPerson);
  el.bookModalVerify.classList.toggle("hidden", !showVerifyCourt && !showVerifyPerson);

  if (bothFree) {
    el.bookModalHint.textContent = `Reserve the court at Coolhurst, then book time with ${name} on the appointment page.`;
    el.bookModalActions.classList.remove("hidden");
    el.bookCourtLink.classList.remove("hidden");
    el.bookAppointmentLink.classList.remove("hidden");
    el.bookModalFallback.classList.add("hidden");
  } else {
    el.bookModalHint.textContent = `This time isn't free for both of you. Switch to Both to find slots where ${name} and a court are available together.`;
    el.bookModalActions.classList.add("hidden");
    el.bookModalFallback.classList.remove("hidden");
  }

  el.bookModal.classList.remove("hidden");
}

function closeBookModal() {
  el.bookModal.classList.add("hidden");
}

function renderDayStrip() {
  ensureSelectedDate();
  const dates = stripDates();
  if (!dates.length) {
    el.dayStrip.innerHTML = "";
    return;
  }

  el.dayStrip.innerHTML = dates
    .map((date) => {
      const short = formatDateShort(date);
      const displayCount = countForDate(date);

      const classes = [
        "day-btn",
        date === state.selectedDate ? "day-btn--active" : "",
        short.isToday ? "day-btn--today" : "",
        short.isWeekend ? "day-btn--weekend" : "",
      ]
        .filter(Boolean)
        .join(" ");

      return `
        <button type="button" class="${classes}" data-date="${date}" aria-pressed="${date === state.selectedDate}">
          <span class="day-btn__dow">${short.dow}</span>
          <span class="day-btn__date">${short.day}</span>
          <span class="day-btn__month">${short.month}</span>
          <span class="day-btn__count ${displayCount === 0 ? "day-btn__count--zero" : ""}">${displayCount}</span>
        </button>
      `;
    })
    .join("");

  el.dayStrip.querySelectorAll(".day-btn").forEach((btn) => {
    btn.addEventListener("click", () => {
      state.selectedDate = btn.dataset.date;
      renderDayStrip();
      renderDayPanel();
      btn.scrollIntoView({ behavior: "smooth", inline: "center", block: "nearest" });
    });
  });
}

function formatRelative(date) {
  const seconds = Math.floor((Date.now() - date.getTime()) / 1000);
  if (seconds < 60) return "just now";
  if (seconds < 3600) return `${Math.floor(seconds / 60)} min ago`;
  if (seconds < 86400) return `${Math.floor(seconds / 3600)} hr ago`;
  return date.toLocaleString("en-GB", {
    day: "numeric",
    month: "short",
    hour: "2-digit",
    minute: "2-digit",
  });
}

function setFreshnessPill(node, label, source) {
  const info = state.health?.scrapers?.[source];
  const freshness = sourceFreshness(source);
  node.classList.remove("meta-pill--warn", "meta-pill--stale", "meta-pill--unknown");

  if (!info?.last_success_at) {
    node.textContent = `${label}: waiting…`;
    node.classList.add("meta-pill--unknown");
    return;
  }

  const when = new Date(info.last_success_at);
  const ago = formatRelative(when);
  node.textContent = `${label}: ${ago}`;
  if (freshness === "stale") node.classList.add("meta-pill--stale");
  else if (freshness === "warn") node.classList.add("meta-pill--warn");
  else if (freshness === "unknown") node.classList.add("meta-pill--unknown");
}

function updateMeta() {
  const name = state.config.booker_name || "Roshan";
  setFreshnessPill(el.lastUpdatedCourts, "Courts", "coolhurst");
  setFreshnessPill(el.lastUpdatedPerson, name, "google");

  const total = allVisibleSlots().length;
  const label = filtersActive()
    ? `${total} matching slots`
    : `${state.slots.length} slots in next 2 weeks`;
  el.totalSlots.textContent = label;
}

function applyConfig() {
  const name = state.config.booker_name || "Roshan";
  document.title = `Play Tennis with ${name} · Coolhurst`;
  el.heroTitle.textContent = `Book tennis with ${name}`;
  el.heroLead.textContent = `Outdoor courts at Coolhurst that line up with ${name}'s appointment availability over the next two weeks. Use Calendar · Both for times that work for both of you.`;
  el.chipPerson.textContent = name;
  const mins = state.config.scrape_interval_seconds || 300;
  const label =
    mins >= 60 ? `${Math.round(mins / 60)} minute${mins === 60 ? "" : "s"}` : `${mins} seconds`;
  el.footerNote.innerHTML = `Availability updates every ${label} · <a href="/docs">API</a>`;

  const showPublic = state.config.show_public_court_calendar_link;
  const coolhurstUrl = state.config.coolhurst_book_url;
  if (showPublic && coolhurstUrl) {
    el.publicCalendarFooter.classList.remove("hidden");
    el.publicCalendarLink.href = coolhurstUrl;
  } else {
    el.publicCalendarFooter.classList.add("hidden");
  }
}

function refreshViews() {
  updateSourceBanner();
  renderDayStrip();
  renderDayPanel();
  updateMeta();
}

function setupFilters() {
  el.surfaceFilters.addEventListener("click", (e) => {
    const btn = e.target.closest(".chip");
    if (!btn) return;
    state.surfaceFilter = btn.dataset.surface;
    el.surfaceFilters.querySelectorAll(".chip").forEach((c) => c.classList.toggle("chip--active", c === btn));
    refreshViews();
  });

  el.timeFilters.addEventListener("click", (e) => {
    const btn = e.target.closest(".chip");
    if (!btn) return;
    state.timeFilter = btn.dataset.time;
    el.timeFilters.querySelectorAll(".chip").forEach((c) => c.classList.toggle("chip--active", c === btn));
    refreshViews();
  });

  el.calendarFilters.addEventListener("click", (e) => {
    const btn = e.target.closest(".chip");
    if (!btn) return;
    state.calendarFilter = btn.dataset.calendar;
    el.calendarFilters.querySelectorAll(".chip").forEach((c) => c.classList.toggle("chip--active", c === btn));
    refreshViews();
  });
}

function setupModal() {
  el.bookModal.querySelectorAll("[data-close-modal]").forEach((node) => {
    node.addEventListener("click", closeBookModal);
  });
  el.switchToBoth.addEventListener("click", () => selectCalendarFilter("both"));
  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape") closeBookModal();
  });
}

async function loadData() {
  try {
    const [slotsRes, personRes, summaryRes, healthRes, configRes] = await Promise.all([
      fetch("/slots"),
      fetch("/person-slots"),
      fetch("/slots/summary"),
      fetch("/health"),
      fetch("/config"),
    ]);

    if (!slotsRes.ok || !summaryRes.ok) throw new Error("Failed to load availability");

    const slotsData = await slotsRes.json();
    const summaryData = await summaryRes.json();
    const healthData = await healthRes.json();
    if (configRes.ok) {
      state.config = { ...state.config, ...(await configRes.json()) };
      applyConfig();
    }

    state.slots = slotsData.slots || [];
    const fromSlots = slotsData.person_slots || [];
    const fromEndpoint = personRes.ok ? (await personRes.json()).slots || [] : [];
    state.personSlots = fromEndpoint.length ? fromEndpoint : fromSlots;
    state.summary = summaryData.summary || [];
    state.health = healthData;

    el.loading.classList.add("hidden");
    refreshViews();
  } catch (err) {
    el.loading.classList.add("hidden");
    const coolhurstUrl = state.config.coolhurst_book_url;
    const showPublic = state.config.show_public_court_calendar_link;
    el.dayPanel.innerHTML = `
      <div class="error-state">
        <h3>Couldn't load courts</h3>
        <p>${escapeHtml(err.message)}. The scraper may still be running — try refreshing in a few minutes.</p>
        ${
          showPublic && coolhurstUrl
            ? `<p><a href="${escapeAttr(coolhurstUrl)}" target="_blank" rel="noopener">Check Coolhurst court calendar</a></p>`
            : ""
        }
      </div>
    `;
  }
}

setupFilters();
setupModal();
applyConfig();
loadData();
setInterval(loadData, 300_000);
