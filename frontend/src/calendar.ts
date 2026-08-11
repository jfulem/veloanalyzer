import { RaceStat, el } from "./raceStats.js";

const WEEKDAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];
const MONTH_NAMES = [
  "January", "February", "March", "April", "May", "June",
  "July", "August", "September", "October", "November", "December",
];

export interface CalendarOptions {
  /** Fired when the user clicks a day: every race on it, or [] when the day
   *  is toggled closed again. Lets the caller sync the shared race list and
   *  the map's highlight. */
  onSelect?: (raceIds: number[]) => void;
}

export interface CalendarController {
  /** Selects races from outside (e.g. a map marker click): jumps to the
   *  first one's month if needed and rings its day. Empty array clears.
   *  Doesn't itself fire onSelect — this is the receiving half of the sync,
   *  not a simulated click, so it can't loop back into the map. */
  highlight(raceIds: number[]): void;
}

/** Renders a month calendar with race days highlighted. `races` is the full
 *  set (not just upcoming) so past months show results too. Re-renders in
 *  place on month navigation; the caller mounts it once. */
export function renderCalendar(
  container: HTMLElement, races: RaceStat[], opts: CalendarOptions = {},
): CalendarController {
  const byDate = new Map<string, RaceStat[]>();
  for (const r of races) {
    if (!r.date) continue;
    const list = byDate.get(r.date);
    if (list) list.push(r);
    else byDate.set(r.date, [r]);
  }

  const today = new Date();
  const todayIso = today.toISOString().slice(0, 10);
  let viewYear = today.getFullYear();
  let viewMonth = today.getMonth(); // 0-based
  // The single ringed day — doubles as both "what the user clicked" and
  // "what an external highlight() selected", so the two never disagree.
  let selectedDay: string | null = null;

  function draw(): void {
    container.innerHTML = "";
    container.appendChild(el("div", { class: "cal-header" }, ""));
    const header = container.querySelector(".cal-header")!;
    header.appendChild(el("div", { class: "cal-title" }, `${MONTH_NAMES[viewMonth]} ${viewYear}`));

    const nav = el("div", { class: "cal-nav" });
    const prev = el("button", { type: "button", "aria-label": "Previous month" }, "‹");
    const next = el("button", { type: "button", "aria-label": "Next month" }, "›");
    prev.addEventListener("click", () => {
      viewMonth -= 1;
      if (viewMonth < 0) { viewMonth = 11; viewYear -= 1; }
      selectedDay = null;
      draw();
      opts.onSelect?.([]);
    });
    next.addEventListener("click", () => {
      viewMonth += 1;
      if (viewMonth > 11) { viewMonth = 0; viewYear += 1; }
      selectedDay = null;
      draw();
      opts.onSelect?.([]);
    });
    nav.appendChild(prev);
    nav.appendChild(next);
    header.appendChild(nav);

    const grid = el("div", { class: "cal-grid" });
    for (const wd of WEEKDAYS) grid.appendChild(el("div", { class: "cal-weekday" }, wd));

    const firstOfMonth = new Date(Date.UTC(viewYear, viewMonth, 1));
    // Monday-first offset: getUTCDay() is 0=Sun..6=Sat.
    const leading = (firstOfMonth.getUTCDay() + 6) % 7;
    const daysInMonth = new Date(Date.UTC(viewYear, viewMonth + 1, 0)).getUTCDate();

    for (let i = 0; i < leading; i++) grid.appendChild(el("div", { class: "cal-day" }));

    for (let day = 1; day <= daysInMonth; day++) {
      const iso = `${viewYear}-${String(viewMonth + 1).padStart(2, "0")}-${String(day).padStart(2, "0")}`;
      const dayRaces = byDate.get(iso) ?? [];
      // Chronological, not data-driven: a race whose date has passed is
      // "past" even if results haven't been captured yet (organizer hasn't
      // published them, scrape missed them, etc). raceHref in raceList.ts
      // still uses finished > 0 to decide the link target, since that's
      // genuinely about whether results.html has anything to show.
      const isPast = iso < todayIso;
      const classes = ["cal-day", "in-month"];
      if (iso === todayIso) classes.push("today");
      if (dayRaces.length > 0) {
        classes.push("has-race", isPast ? "past" : "future");
      }
      if (iso === selectedDay) classes.push("selected");
      const cell = el("div", { class: classes.join(" ") }, String(day));
      if (dayRaces.length > 0) {
        cell.appendChild(el("span", { class: `cal-dot ${isPast ? "past" : "future"}` }));
        cell.setAttribute("role", "button");
        cell.setAttribute("tabindex", "0");
        // Toggles the day rather than sometimes jumping straight to a single
        // race — matches the map's click-to-preview pattern, and the shared
        // race-list panel below both widgets shows the details either way.
        const activate = (): void => {
          selectedDay = selectedDay === iso ? null : iso;
          draw();
          opts.onSelect?.(selectedDay ? dayRaces.map((r) => r.id) : []);
        };
        cell.addEventListener("click", activate);
        cell.addEventListener("keydown", (e) => {
          if (e.key === "Enter" || e.key === " ") { e.preventDefault(); activate(); }
        });
      }
      grid.appendChild(cell);
    }

    container.appendChild(grid);

    if (races.every((r) => !r.date)) {
      container.appendChild(el("p", { class: "cal-empty" }, "No dated races yet."));
    }

    container.appendChild(el("div", { class: "cal-legend" }, ""));
    const legend = container.querySelector(".cal-legend")!;
    const upcoming = el("span");
    upcoming.appendChild(el("span", { class: "dot", style: "background:#63b3ed" }));
    upcoming.appendChild(document.createTextNode("Upcoming"));
    const past = el("span");
    past.appendChild(el("span", { class: "dot", style: "background:#68d391" }));
    past.appendChild(document.createTextNode("Results"));
    legend.appendChild(upcoming);
    legend.appendChild(past);
  }

  draw();

  return {
    highlight(raceIds: number[]): void {
      if (raceIds.length === 0) {
        if (selectedDay === null) return;
        selectedDay = null;
        draw();
        return;
      }
      const race = races.find((r) => r.id === raceIds[0]);
      if (!race?.date) return;
      const [y, m] = race.date.split("-").map(Number);
      viewYear = y!;
      viewMonth = m! - 1;
      selectedDay = race.date;
      draw();
    },
  };
}
