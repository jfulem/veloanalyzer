import { RaceStat, catBadge, el } from "./raceStats.js";

const WEEKDAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];
const MONTH_NAMES = [
  "January", "February", "March", "April", "May", "June",
  "July", "August", "September", "October", "November", "December",
];

/** Destination for a given race: results once it has finished results,
 *  otherwise the (upcoming) start list — same rule used by results.ts. */
function raceHref(race: RaceStat): string {
  const page = race.finished > 0 ? "./results.html" : "./app.html";
  return `${page}#race=${encodeURIComponent(race.slug)}`;
}

/** Renders a month calendar with race days highlighted. `races` is the full
 *  set (not just upcoming) so past months show results too. Re-renders in
 *  place on month navigation; the caller mounts it once. */
export function renderCalendar(container: HTMLElement, races: RaceStat[]): void {
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
  let openDay: string | null = null;

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
      openDay = null;
      draw();
    });
    next.addEventListener("click", () => {
      viewMonth += 1;
      if (viewMonth > 11) { viewMonth = 0; viewYear += 1; }
      openDay = null;
      draw();
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
      // published them, scrape missed them, etc). raceHref() below still
      // uses finished > 0 to decide the link target, since that's genuinely
      // about whether results.html has anything to show.
      const isPast = iso < todayIso;
      const classes = ["cal-day", "in-month"];
      if (iso === todayIso) classes.push("today");
      if (dayRaces.length > 0) {
        classes.push("has-race", isPast ? "past" : "future");
      }
      const cell = el("div", { class: classes.join(" ") }, String(day));
      if (dayRaces.length > 0) {
        cell.appendChild(el("span", { class: `cal-dot ${isPast ? "past" : "future"}` }));
        cell.setAttribute("role", "button");
        cell.setAttribute("tabindex", "0");
        const activate = (): void => {
          if (dayRaces.length === 1) {
            window.location.href = raceHref(dayRaces[0]!);
          } else {
            openDay = openDay === iso ? null : iso;
            draw();
          }
        };
        cell.addEventListener("click", activate);
        cell.addEventListener("keydown", (e) => {
          if (e.key === "Enter" || e.key === " ") { e.preventDefault(); activate(); }
        });
      }
      grid.appendChild(cell);
    }

    if (openDay) {
      const dayRaces = byDate.get(openDay) ?? [];
      const list = el("div", { class: "cal-daylist" });
      for (const race of dayRaces) {
        const link = el("a", { href: raceHref(race) });
        link.appendChild(document.createTextNode(`${race.name} `));
        link.appendChild(catBadge(race.uci_category));
        list.appendChild(link);
      }
      grid.appendChild(list);
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
}
