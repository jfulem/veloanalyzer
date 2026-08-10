import { Race } from "./api.js";
import { getRaceStats } from "./raceStats.js";
import { bootRaceBrowser } from "./raceBrowser.js";

// Only races with at least one captured finishing position — not simply
// "in the past", since a race can be past but still awaiting results, and not
// "ranked" (that counts UCI-ranked entrants, which is true before the race is
// even run). A RaceStat's extra fields are a superset of Race, so it can
// stand in for one directly.
async function getResultRaces(): Promise<Race[]> {
  const stats = await getRaceStats();
  return stats
    .filter((s) => s.finished > 0)
    .sort((a, b) => (b.date || "0000-00-00").localeCompare(a.date || "0000-00-00"));
}

bootRaceBrowser({
  getDisplayRaces: getResultRaces,
  emptyText: "No results available yet",
});
