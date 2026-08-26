import { UciArchiveRace } from "./api.js";

// Preferred tab order when a race has more than one category on record.
export const CAT_ORDER = ["ME", "WE", "MJ", "WJ", "MU23", "WU23"];

// One competition, not one competition+category — the archive API returns a
// row per category, but the browse list and race page both want one row per
// race, with category chosen afterwards.
export interface GroupedRace {
  xco_race_id: string;
  comp_name: string;
  date: string;
  venue: string;
  country: string;
  categories: Record<string, number>;   // category → finisher count
}

export function groupByCompetition(races: UciArchiveRace[]): GroupedRace[] {
  const byId = new Map<string, GroupedRace>();
  for (const r of races) {
    let g = byId.get(r.xco_race_id);
    if (!g) {
      g = { xco_race_id: r.xco_race_id, comp_name: r.comp_name, date: r.date,
            venue: r.venue, country: r.country, categories: {} };
      byId.set(r.xco_race_id, g);
    }
    g.categories[r.category] = r.finishers;
  }
  return [...byId.values()].sort((a, b) => (a.date < b.date ? 1 : a.date > b.date ? -1 : 0));
}

export function sortedCategories(categories: Record<string, number>): string[] {
  const cats = Object.keys(categories);
  return cats.sort((a, b) => {
    const ia = CAT_ORDER.indexOf(a), ib = CAT_ORDER.indexOf(b);
    return (ia === -1 ? 99 : ia) - (ib === -1 ? 99 : ib);
  });
}
