import L from "leaflet";
import "leaflet/dist/leaflet.css";
import { RaceStat, catBadge } from "./raceStats.js";

/** Same destination rule as calendar.ts: results once a race has finished
 *  results, otherwise the (upcoming) start list. */
function raceHref(race: RaceStat): string {
  const page = race.finished > 0 ? "./results.html" : "./app.html";
  return `${page}#race=${encodeURIComponent(race.slug)}`;
}

/** A small colored dot rather than Leaflet's default pin: no marker-image
 *  assets to bundle, and it matches the calendar widget's own future/past
 *  color coding (blue/green) so the two widgets read as one system. */
function dotIcon(color: string): L.DivIcon {
  return L.divIcon({
    className: "map-dot",
    html: `<span style="background:${color}"></span>`,
    iconSize: [14, 14],
    iconAnchor: [7, 7],
  });
}

const FUTURE_COLOR = "#63b3ed";
const PAST_COLOR = "#68d391";

/** Renders a Leaflet map with one marker per race that has coordinates.
 *  Races without lat/lon (no location: in races.yml yet, or not geocoded)
 *  are simply absent — no wrong pin is better than a guessed one. */
export function renderMap(container: HTMLElement, races: RaceStat[]): void {
  const located = races.filter((r): r is RaceStat & { lat: number; lon: number } =>
    r.lat !== null && r.lon !== null);

  if (located.length === 0) {
    container.innerHTML = "";
    const empty = document.createElement("p");
    empty.className = "cal-empty";
    empty.textContent = "No race locations yet.";
    container.appendChild(empty);
    return;
  }

  const map = L.map(container, { scrollWheelZoom: false });
  L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", {
    attribution: "&copy; <a href=\"https://www.openstreetmap.org/copyright\">OpenStreetMap</a> contributors",
    maxZoom: 18,
  }).addTo(map);

  const bounds = L.latLngBounds(located.map((r) => [r.lat, r.lon]));

  for (const race of located) {
    const isPast = race.finished > 0;
    const marker = L.marker([race.lat, race.lon], {
      icon: dotIcon(isPast ? PAST_COLOR : FUTURE_COLOR),
    }).addTo(map);

    const popup = document.createElement("div");
    const link = document.createElement("a");
    link.href = raceHref(race);
    link.textContent = race.name;
    popup.appendChild(link);
    popup.appendChild(document.createElement("br"));
    const meta = document.createElement("span");
    meta.style.cssText = "font-size:.78rem;color:#718096";
    meta.textContent = `${race.location}${race.date ? ` · ${race.date}` : ""} `;
    popup.appendChild(meta);
    popup.appendChild(catBadge(race.uci_category));
    marker.bindPopup(popup);
  }

  if (located.length === 1) {
    map.setView([located[0]!.lat, located[0]!.lon], 9);
  } else {
    map.fitBounds(bounds, { padding: [24, 24] });
  }
}
