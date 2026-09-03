import { getRaceStats, getSiteStats, getMeta, todayIso, el, RaceStat } from "./raceStats.js";
import { renderCalendar, CalendarController } from "./calendar.js";
import { renderMap, MapController } from "./map.js";
import { renderRaceList } from "./raceList.js";
import { initChrome } from "./discipline.js";

const API_BASE = (import.meta.env["VITE_API_BASE"] ?? "").replace(/\/$/, "");

function $(sel: string): HTMLElement {
  const node = document.querySelector<HTMLElement>(sel);
  if (!node) throw new Error(`Missing element: ${sel}`);
  return node;
}

/** Each stat doubles as a shortcut to the page that shows the detail behind it,
 *  so the numbers are a way in rather than decoration. */
function chip(value: string, label: string, href: string): HTMLElement {
  const wrap = el("a", { class: "hero-chip", href });
  wrap.appendChild(el("span", { class: "hero-chip-val" }, value));
  wrap.appendChild(el("span", { class: "hero-chip-lbl" }, label));
  return wrap;
}

function nextRaceLabel(upcoming: RaceStat[]): string {
  const next = upcoming[0];
  if (!next?.date) return "—";
  const days = Math.ceil((Date.parse(`${next.date}T00:00:00Z`) - Date.now()) / 86_400_000);
  return days <= 0 ? "Today" : `${days}d`;
}

// ── Request form ────────────────────────────────────────────────────────────
function wireRequestForm(): void {
  const form   = document.querySelector<HTMLFormElement>("#request-form");
  const button = document.querySelector<HTMLButtonElement>("#rq-submit");
  const msg    = document.querySelector<HTMLElement>("#rq-msg");
  if (!form || !button || !msg) return;

  const show = (text: string, ok: boolean): void => {
    msg.textContent = text;
    msg.className = `form-msg ${ok ? "ok" : "err"}`;
    msg.hidden = false;
  };

  form.addEventListener("submit", async (e) => {
    e.preventDefault();
    const data = new FormData(form);
    const url = String(data.get("url") ?? "").trim();
    if (!url) {
      show("Please paste a link to the start list.", false);
      return;
    }

    button.disabled = true;
    const original = button.textContent;
    button.textContent = "Sending…";
    try {
      const resp = await fetch(`${API_BASE}/api/race-requests`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          url,
          race_name: String(data.get("race_name") ?? "").trim(),
          category:  String(data.get("category") ?? "").trim(),
          note:      String(data.get("note") ?? "").trim(),
          email:     String(data.get("email") ?? "").trim(),
          website:   String(data.get("website") ?? ""),   // honeypot
        }),
      });
      if (resp.ok) {
        form.reset();
        show("Thanks — the suggestion has been recorded and will be reviewed.", true);
      } else {
        // The API returns a human-readable reason; fall back if it doesn't.
        const detail = await resp.json().then(
          (b: { detail?: string }) => b.detail,
          () => undefined,
        );
        show(detail ?? "Something went wrong. Please try again later.", false);
      }
    } catch {
      show("Could not reach the server. Please try again later.", false);
    } finally {
      button.disabled = false;
      button.textContent = original;
    }
  });
}

(async () => {
  wireRequestForm();

  const loading = $("#loading");
  const content = $("#content");
  try {
    const [stats, site, meta] = await Promise.all([getRaceStats(), getSiteStats(), getMeta()]);

    // Leaflet measures its container's pixel size at construction time, so
    // #map has to already be visible before renderMap() runs below — a
    // display:none ancestor at that point would leave the map permanently
    // blank, since nothing here calls invalidateSize() after the fact.
    loading.style.display = "none";
    content.style.display = "block";

    const today = todayIso();
    const upcoming = stats.filter((s) => s.date && s.date >= today);

    const next = upcoming[0];
    const heroStats = $("#hero-stats");
    heroStats.appendChild(chip(String(site.races), "Races tracked", "./races.html"));
    heroStats.appendChild(chip(String(site.riders), "Riders tracked", "./riders.html"));
    heroStats.appendChild(chip(
      nextRaceLabel(upcoming),
      "Next race",
      next ? `./app.html#race=${encodeURIComponent(next.slug)}` : "./races.html",
    ));

    // Selecting a race (or a day's/venue's worth of races) in either widget
    // highlights the same set in the other and lists them all in the shared
    // panel below. The circular reference between the two controllers is
    // safe: neither callback runs until a later user click, by which point
    // both are assigned.
    const raceListCtrl = renderRaceList($("#race-list"), stats);
    let calendarCtrl: CalendarController;
    let mapCtrl: MapController;
    calendarCtrl = renderCalendar($("#calendar"), stats, {
      onSelect: (raceIds) => { raceListCtrl.show(raceIds); mapCtrl.highlight(raceIds); },
    });
    mapCtrl = renderMap($("#map"), stats, {
      onSelect: (raceIds) => { raceListCtrl.show(raceIds); calendarCtrl.highlight(raceIds); },
    });

    $("#generated-at").textContent = meta["generated_at"] ?? "";
  } catch (err) {
    // The page still explains what the site does and still accepts a request
    // when the API is unreachable — hiding all of it would be a worse failure
    // than showing it without live numbers.
    loading.textContent = `Live data is unavailable right now (${err}).`;
    loading.style.color = "#fc8181";
  }
  content.style.display = "block";
})();

initChrome();
