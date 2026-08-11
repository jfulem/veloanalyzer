import L from "leaflet";
import "leaflet/dist/leaflet.css";
import { RaceStat, todayIso } from "./raceStats.js";

export interface MapOptions {
  /** Fired when the user clicks a marker, with every race at that point (a
   *  venue usually has one per category). Lets the caller sync the calendar
   *  and the shared race-list panel. */
  onSelect?: (raceIds: number[]) => void;
}

export interface MapController {
  /** Selects races from outside (e.g. a calendar day click): highlights and
   *  fits the view to every one of them that has a marker. Races that share
   *  no marker (no coordinates) are silently skipped rather than pointing
   *  at nothing. Empty array clears. Doesn't itself fire onSelect. */
  highlight(raceIds: number[]): void;
}

type LocatedRace = RaceStat & { lat: number; lon: number };

interface MarkerGroup {
  lat: number;
  lon: number;
  raceIds: number[];
  isPast: boolean;
  marker: L.Marker;
}

/** Same destination rule as calendar.ts/raceList.ts: results once a race has
 *  finished results, otherwise the (upcoming) start list. */
function raceHref(race: RaceStat): string {
  const page = race.finished > 0 ? "./results.html" : "./app.html";
  return `${page}#race=${encodeURIComponent(race.slug)}`;
}

/** A small colored dot rather than Leaflet's default pin: no marker-image
 *  assets to bundle, and it matches the calendar widget's own future/past
 *  color coding (blue/green) so the two widgets read as one system. Selected
 *  gets a larger dot with a ring, matching the calendar's gold selection ring. */
function dotIcon(color: string, selected: boolean): L.DivIcon {
  const size = selected ? 20 : 14;
  const ring = selected ? "box-shadow:0 0 0 2px #f6e05e;" : "";
  return L.divIcon({
    className: "map-dot",
    html: `<span style="background:${color};${ring}"></span>`,
    iconSize: [size, size],
    iconAnchor: [size / 2, size / 2],
  });
}

const FUTURE_COLOR = "#63b3ed";
const PAST_COLOR = "#68d391";

/** Renders a Leaflet map with one marker per venue (races sharing a
 *  location: — usually one event's several categories — collapse onto a
 *  single point rather than stacking identical, unclickable markers).
 *  Races without lat/lon (no location: in races.yml yet, or not geocoded)
 *  are simply absent — no wrong pin is better than a guessed one. */
export function renderMap(
  container: HTMLElement, races: RaceStat[], opts: MapOptions = {},
): MapController {
  const located = races.filter((r): r is LocatedRace => r.lat !== null && r.lon !== null);

  if (located.length === 0) {
    container.innerHTML = "";
    const empty = document.createElement("p");
    empty.className = "cal-empty";
    empty.textContent = "No race locations yet.";
    container.appendChild(empty);
    return { highlight() {} };
  }

  const map = L.map(container, { scrollWheelZoom: false });
  L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", {
    attribution: "&copy; <a href=\"https://www.openstreetmap.org/copyright\">OpenStreetMap</a> contributors",
    maxZoom: 18,
  }).addTo(map);

  const today = todayIso();
  const byPoint = new Map<string, LocatedRace[]>();
  for (const race of located) {
    const key = `${race.lat},${race.lon}`;
    const list = byPoint.get(key);
    if (list) list.push(race);
    else byPoint.set(key, [race]);
  }

  const groups: MarkerGroup[] = [];
  const groupByRaceId = new Map<number, MarkerGroup>();
  let selected: MarkerGroup[] = [];

  for (const [, group] of byPoint) {
    const { lat, lon } = group[0]!;
    // A venue is "past" once every race there has happened — one category
    // still upcoming (a rare split-date entry) keeps the point blue.
    const isPast = group.every((r) => r.date < today);
    const marker = L.marker([lat, lon], { icon: dotIcon(isPast ? PAST_COLOR : FUTURE_COLOR, false) }).addTo(map);

    const popup = document.createElement("div");
    const title = document.createElement("strong");
    title.textContent = group[0]!.location || group[0]!.name;
    popup.appendChild(title);
    popup.appendChild(document.createElement("br"));
    const meta = document.createElement("span");
    meta.style.cssText = "font-size:.78rem;color:#718096";
    meta.textContent = group.length === 1
      ? group[0]!.name
      : `${group.length} races — see the list below`;
    popup.appendChild(meta);
    marker.bindPopup(popup, { autoClose: false, closeOnClick: false });

    const raceIds = group.map((r) => r.id);
    const markerGroup: MarkerGroup = { lat, lon, raceIds, isPast, marker };
    groups.push(markerGroup);
    for (const id of raceIds) groupByRaceId.set(id, markerGroup);

    marker.on("click", () => {
      // Updates this widget's own highlight directly, the same way a
      // calendar day click updates the calendar directly — onSelect is only
      // for notifying the *other* widget, not how this one reacts to itself.
      const alreadySelected = selected.length === 1 && selected[0] === markerGroup;
      setSelected(alreadySelected ? [] : [markerGroup]);
      opts.onSelect?.(alreadySelected ? [] : raceIds);
    });
  }

  const allBounds = L.latLngBounds(groups.map((g) => [g.lat, g.lon]));
  if (groups.length === 1) {
    map.setView([groups[0]!.lat, groups[0]!.lon], 9);
  } else {
    map.fitBounds(allBounds, { padding: [24, 24] });
  }

  function setSelected(next: MarkerGroup[]): void {
    for (const g of selected) {
      g.marker.setIcon(dotIcon(g.isPast ? PAST_COLOR : FUTURE_COLOR, false));
      g.marker.closePopup();
    }
    selected = next;
    for (const g of selected) {
      g.marker.setIcon(dotIcon(g.isPast ? PAST_COLOR : FUTURE_COLOR, true));
      g.marker.openPopup();
    }
  }

  return {
    highlight(raceIds: number[]): void {
      const uniqueGroups = [...new Set(raceIds.map((id) => groupByRaceId.get(id)).filter((g): g is MarkerGroup => !!g))];
      setSelected(uniqueGroups);
      if (uniqueGroups.length === 0) return;
      if (uniqueGroups.length === 1) {
        map.panTo([uniqueGroups[0]!.lat, uniqueGroups[0]!.lon]);
      } else {
        map.fitBounds(L.latLngBounds(uniqueGroups.map((g) => [g.lat, g.lon])), { padding: [24, 24] });
      }
    },
  };
}
