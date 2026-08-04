import { getRaceStats, getSiteStats, getMeta, catBadge, todayIso, el, RaceStat } from "./raceStats.js";

function $(sel: string): HTMLElement {
  const node = document.querySelector<HTMLElement>(sel);
  if (!node) throw new Error(`Missing element: ${sel}`);
  return node;
}

function chip(value: string, label: string): HTMLElement {
  const wrap = el("div", { class: "hero-chip" });
  wrap.appendChild(el("span", { class: "hero-chip-val" }, value));
  wrap.appendChild(el("span", { class: "hero-chip-lbl" }, label));
  return wrap;
}

function previewCard(s: RaceStat): HTMLElement {
  const a = el("a", { class: "preview-card", href: `./app.html#race=${encodeURIComponent(s.slug)}` });
  a.appendChild(el("div", { class: "preview-date" }, s.date ?? ""));
  a.appendChild(el("div", { class: "preview-name" }, s.name));
  const badgeWrap = el("div");
  badgeWrap.appendChild(catBadge(s.uci_category));
  a.appendChild(badgeWrap);
  return a;
}

function nextRaceLabel(upcoming: RaceStat[]): string {
  const next = upcoming[0];
  if (!next?.date) return "—";
  const days = Math.ceil((Date.parse(`${next.date}T00:00:00Z`) - Date.now()) / 86_400_000);
  return days <= 0 ? "Today" : `${days}d`;
}

(async () => {
  const loading = $("#loading");
  let stats: RaceStat[];
  let site: Awaited<ReturnType<typeof getSiteStats>>;
  let meta: Record<string, string>;
  try {
    [stats, site, meta] = await Promise.all([getRaceStats(), getSiteStats(), getMeta()]);
  } catch (err) {
    loading.textContent = `Failed to reach the API: ${err}`;
    return;
  }

  const today = todayIso();
  const upcoming = stats.filter((s) => s.date && s.date >= today);

  const heroStats = $("#hero-stats");
  heroStats.appendChild(chip(String(site.races), "Races tracked"));
  heroStats.appendChild(chip(String(site.riders), "Riders tracked"));
  heroStats.appendChild(chip(nextRaceLabel(upcoming), "Next race"));

  const grid = $("#preview-grid");
  if (upcoming.length === 0) {
    grid.appendChild(el("p", { class: "h2h-empty" }, "No upcoming races scheduled."));
  } else {
    for (const s of upcoming.slice(0, 5)) grid.appendChild(previewCard(s));
  }

  $("#generated-at").textContent = meta["generated_at"] ?? "";
  loading.style.display = "none";
  $("#content").style.display = "block";
})();
