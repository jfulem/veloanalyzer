import { RaceStat, catBadge, el } from "./raceStats.js";

export interface RaceListController {
  /** Shows every given race, grouped by venue. Empty array hides the panel. */
  show(raceIds: number[]): void;
}

/** Same destination rule as calendar.ts/map.ts: results once a race has
 *  finished results, otherwise the (upcoming) start list. */
function raceHref(race: RaceStat): string {
  const page = race.finished > 0 ? "./results.html" : "./app.html";
  return `${page}#race=${encodeURIComponent(race.slug)}`;
}

/** Full-width panel below the calendar/map row showing whichever races are
 *  currently selected in either widget. Pulled out of both widgets rather
 *  than rendered inline in each: a calendar day or a map marker can each
 *  represent several races at several venues (a shared date, or one event's
 *  several categories stacked at one point), and cramming that list inside
 *  a fixed-size box either clipped it or made the box grow — which, for the
 *  calendar specifically, desynced its height from the map's (Leaflet sizes
 *  its canvas once at construction and doesn't notice the container growing
 *  later), leaving a dead gap under the map. A separate full-width panel
 *  that appears below both avoids that entirely, since neither widget's own
 *  box size changes when a selection is made. */
export function renderRaceList(container: HTMLElement, races: RaceStat[]): RaceListController {
  const byId = new Map(races.map((r) => [r.id, r]));

  function show(raceIds: number[]): void {
    container.innerHTML = "";
    const selected = raceIds
      .map((id) => byId.get(id))
      .filter((r): r is RaceStat => !!r);

    if (selected.length === 0) {
      container.hidden = true;
      return;
    }
    container.hidden = false;

    // Grouped by venue: a shared date (several events, one each) and a
    // shared event (several categories, one venue) both read as one flat
    // list otherwise, with no visual cue for which races actually happened
    // in the same place.
    const byLocation = new Map<string, RaceStat[]>();
    for (const race of selected) {
      const key = race.location || "Location unknown";
      const list = byLocation.get(key);
      if (list) list.push(race);
      else byLocation.set(key, [race]);
    }

    for (const [location, group] of byLocation) {
      const section = el("div", { class: "race-list-group" });
      const heading = el("div", { class: "race-list-location" });
      heading.appendChild(document.createTextNode(location));
      heading.appendChild(el("span", { class: "race-list-date" }, group[0]!.date ?? ""));
      section.appendChild(heading);

      for (const race of [...group].sort((a, b) => a.uci_category.localeCompare(b.uci_category))) {
        const row = el("a", { class: "race-list-row", href: raceHref(race) });
        row.appendChild(el("span", { class: "race-list-name" }, race.name));
        row.appendChild(catBadge(race.uci_category));
        section.appendChild(row);
      }
      container.appendChild(section);
    }
  }

  return { show };
}
