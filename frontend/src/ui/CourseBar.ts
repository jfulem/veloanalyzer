import { Race } from "../api.js";
import { el, totalClimbM, totalDistanceKm } from "../utils.js";

/** The course and the race-day conditions, above the field-strength stats.
 *
 *  A sibling of StatsBar rather than more cards inside it: that one is handed
 *  Rider[] and every card it draws is a field-strength number, while these
 *  describe the race itself and are absent for most races until someone
 *  measures the venue. Keeping them in their own container means the whole
 *  block can be hidden, instead of punching holes in a grid that is otherwise
 *  always complete.
 *
 *  Reuses StatsBar's .stats-grid / .stat-card classes, so there is no new CSS
 *  and the two rows line up.
 */
export function renderCourseBar(container: HTMLElement, race: Race): void {
  container.innerHTML = "";

  const distance = totalDistanceKm(race.lap_km, race.laps);
  const climb    = totalClimbM(race.lap_elevation_m, race.laps);

  const cards: { label: string; value: string }[] = [];
  if (race.lap_km)  cards.push({ label: "Lap",       value: `${race.lap_km} km` });
  if (race.laps)    cards.push({ label: "Laps",      value: String(race.laps) });
  if (distance)     cards.push({ label: "Distance",  value: `${distance.toFixed(1)} km` });
  if (climb)        cards.push({ label: "Climbing",  value: `${climb} m` });

  // Temperature is the one reading that is always worth showing when we have
  // any weather at all; rain and wind only earn their place when there was
  // some. A dry, still day says what it needs to by saying nothing.
  const conditions: string[] = [];
  if (race.weather_temp_max_c != null && race.weather_temp_min_c != null) {
    conditions.push(`${Math.round(race.weather_temp_min_c)}–${Math.round(race.weather_temp_max_c)} °C`);
  }
  if (race.weather_precip_mm != null) {
    conditions.push(race.weather_precip_mm > 0
      ? `${race.weather_precip_mm} mm rain`
      : "dry");
  }
  if (race.weather_wind_kmh != null) {
    conditions.push(`${Math.round(race.weather_wind_kmh)} km/h wind`);
  }

  const terrain = (race.terrain || "").trim();
  if (!cards.length && !conditions.length && !terrain) {
    container.hidden = true;
    return;
  }
  container.hidden = false;

  if (cards.length) {
    const grid = el("div", { class: "stats-grid" });
    for (const c of cards) {
      const card = el("div", { class: "stat-card" });
      card.appendChild(el("div", { class: "stat-value" }, c.value));
      card.appendChild(el("div", { class: "stat-label" }, c.label));
      grid.appendChild(card);
    }
    container.appendChild(grid);
  }

  const notes: string[] = [];
  if (terrain) notes.push(terrain);
  // "Race-day", deliberately, and the tooltip says why: these are the day's
  // figures for the venue, so a morning junior race and an afternoon elite one
  // share them, and the rain may all have fallen after everyone went home.
  if (conditions.length) notes.push(`Race day: ${conditions.join(" · ")}`);
  if (notes.length) {
    const line = el("p", { class: "course-note" }, notes.join(" — "));
    if (conditions.length) {
      line.title = "Conditions are the daily summary for the venue, not the "
        + "hour of this category's race.";
    }
    container.appendChild(line);
  }
}
