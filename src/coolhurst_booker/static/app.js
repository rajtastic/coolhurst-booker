const TIME_BUCKETS = {
  morning: { label: "Morning", start: 0, end: 12 },
  afternoon: { label: "Afternoon", start: 12, end: 17 },
  evening: { label: "Evening", start: 17, end: 24 },
};

const state = {
  slots: [],
  summary: [],
  selectedDate: null,
  surfaceFilter: "all",
  timeFilter: "all",
  lastScrape: null,
};

const el = {
  dayStrip: document.getElementById("day-strip"),
  dayPanel: document.getElementById("day-panel"),
  loading: document.getElementById("loading"),
  lastUpdated: document.getElementById("last-updated"),
  totalSlots: document.getElementById("total-slots"),
  surfaceFilters: document.getElementById("surface-filters"),
  timeFilters: document.getElementById("time-filters"),
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

function filterSlots(slots) {
  return slots.filter((s) => matchesSurfaceFilter(s) && matchesTimeFilter(s));
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
  return now.toISOString().slice(0, 10);
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
        a.court.localeCompare(b.court, undefined, { numeric: true })
    );
  }
  return groups;
}

function renderSlotCard(slot) {
  const surface = getSurface(slot.court);
  const courtNum = slot.court.match(/^(\d+)/)?.[1] || "";
  const courtName = courtNum ? `Court ${courtNum}` : slot.court;
  const detail = slot.court.replace(/^\d+\s*-\s*/, "");

  return `
    <article class="slot-card">
      <div class="slot-card__time">${formatTimeRange(slot.start_time, slot.end_time)}</div>
      <div class="slot-card__court">${courtName}${detail ? ` · ${detail}` : ""}</div>
      <span class="surface-badge surface-badge--${surface}">${surfaceLabel(surface)}</span>
    </article>
  `;
}

function renderDayPanel() {
  const date = state.selectedDate;
  if (!date) return;

  const daySlots = filterSlots(state.slots.filter((s) => s.date === date));
  const groups = groupByTimeOfDay(daySlots);
  const short = formatDateShort(date);

  let sections = "";
  for (const [key, bucket] of Object.entries(TIME_BUCKETS)) {
    const items = groups[key];
    if (!items.length) continue;
  if (state.timeFilter !== "all" && state.timeFilter !== key) continue;

    sections += `
      <div class="time-section">
        <h3 class="time-section__title">${bucket.label}</h3>
        <div class="slot-grid">
          ${items.map(renderSlotCard).join("")}
        </div>
      </div>
    `;
  }

  const subtitle =
    daySlots.length === 0
      ? "No courts match your filters"
      : `${daySlots.length} court${daySlots.length === 1 ? "" : "s"} available`;

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

  el.dayPanel.innerHTML = `
    <div class="day-header">
      <h2>${formatDateLong(date)}${short.isToday ? ' <span style="font-size:0.65em;font-weight:500;color:var(--green-mid)">· Today</span>' : ""}</h2>
      <p>${subtitle} — tap a time and we'll sort the rest</p>
    </div>
    ${sections}
  `;
}

function renderDayStrip() {
  const dates = state.summary.map((s) => s.date).sort();
  if (!dates.length) {
    el.dayStrip.innerHTML = "";
    return;
  }

  if (!state.selectedDate || !dates.includes(state.selectedDate)) {
    state.selectedDate = dates.find((d) => d >= todayStr()) || dates[0];
  }

  el.dayStrip.innerHTML = dates
    .map((date) => {
      const short = formatDateShort(date);
      const summary = state.summary.find((s) => s.date === date);
      const count = summary?.slot_count ?? 0;
      const filteredCount = filterSlots(state.slots.filter((s) => s.date === date)).length;
      const displayCount =
        state.surfaceFilter !== "all" || state.timeFilter !== "all"
          ? filteredCount
          : count;

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

function updateMeta() {
  if (state.lastScrape?.finished_at) {
    const when = new Date(state.lastScrape.finished_at);
    const ago = formatRelative(when);
    el.lastUpdated.textContent = `Updated ${ago}`;
  } else {
    el.lastUpdated.textContent = "Waiting for first scrape…";
  }

  const total = filterSlots(state.slots).length;
  const label =
    state.surfaceFilter !== "all" || state.timeFilter !== "all"
      ? `${total} matching slots`
      : `${state.slots.length} slots in next 2 weeks`;
  el.totalSlots.textContent = label;
}

function formatRelative(date) {
  const seconds = Math.floor((Date.now() - date.getTime()) / 1000);
  if (seconds < 60) return "just now";
  if (seconds < 3600) return `${Math.floor(seconds / 60)} min ago`;
  if (seconds < 86400) return `${Math.floor(seconds / 3600)} hr ago`;
  return date.toLocaleString("en-GB", { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" });
}

function setupFilters() {
  el.surfaceFilters.addEventListener("click", (e) => {
    const btn = e.target.closest(".chip");
    if (!btn) return;
    state.surfaceFilter = btn.dataset.surface;
    el.surfaceFilters.querySelectorAll(".chip").forEach((c) => c.classList.toggle("chip--active", c === btn));
    renderDayStrip();
    renderDayPanel();
    updateMeta();
  });

  el.timeFilters.addEventListener("click", (e) => {
    const btn = e.target.closest(".chip");
    if (!btn) return;
    state.timeFilter = btn.dataset.time;
    el.timeFilters.querySelectorAll(".chip").forEach((c) => c.classList.toggle("chip--active", c === btn));
    renderDayStrip();
    renderDayPanel();
    updateMeta();
  });
}

async function loadData() {
  try {
    const [slotsRes, summaryRes, healthRes] = await Promise.all([
      fetch("/slots"),
      fetch("/slots/summary"),
      fetch("/health"),
    ]);

    if (!slotsRes.ok || !summaryRes.ok) throw new Error("Failed to load availability");

    const slotsData = await slotsRes.json();
    const summaryData = await summaryRes.json();
    const healthData = await healthRes.json();

    state.slots = slotsData.slots || [];
    state.summary = summaryData.summary || [];
    state.lastScrape = healthData.last_scrape;

    el.loading.classList.add("hidden");
    updateMeta();
    renderDayStrip();
    renderDayPanel();
  } catch (err) {
    el.loading.classList.add("hidden");
    el.dayPanel.innerHTML = `
      <div class="error-state">
        <h3>Couldn't load courts</h3>
        <p>${err.message}. The scraper may still be running — try refreshing in a minute.</p>
      </div>
    `;
  }
}

setupFilters();
loadData();
setInterval(loadData, 60_000);
