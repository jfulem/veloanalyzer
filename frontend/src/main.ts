import { getRaces, Race } from "./api.js";
import { bootRaceBrowser } from "./raceBrowser.js";
import { initChrome } from "./discipline.js";

// Upcoming only: a race counts as "upcoming" until 20:00 on its own date, so
// it stays visible through the day it's actually run.
async function getUpcomingRaces(): Promise<Race[]> {
  const races = await getRaces();
  return races.filter((r) => {
    if (!r.date) return true;
    const cutoff = new Date(r.date);
    cutoff.setHours(20, 0, 0, 0);
    return new Date() <= cutoff;
  });
}

bootRaceBrowser({
  getDisplayRaces: getUpcomingRaces,
  emptyText: "No upcoming races",
});

initChrome();
