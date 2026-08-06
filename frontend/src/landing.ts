import { getRaceStats, getSiteStats, getMeta, catBadge, todayIso, el, RaceStat } from "./raceStats.js";

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

    const today = todayIso();
    const upcoming = stats.filter((s) => s.date && s.date >= today);

    const next = upcoming[0];
    const heroStats = $("#hero-stats");
    heroStats.appendChild(chip(String(site.races), "Races tracked", "./races.html"));
    heroStats.appendChild(chip(String(site.riders), "Riders tracked", "./app.html"));
    heroStats.appendChild(chip(
      nextRaceLabel(upcoming),
      "Next race",
      next ? `./app.html#race=${encodeURIComponent(next.slug)}` : "./races.html",
    ));

    const grid = $("#preview-grid");
    if (upcoming.length === 0) {
      grid.appendChild(el("p", { class: "h2h-empty" }, "No upcoming races scheduled."));
    } else {
      // Four, not five: the grid fits four across at the container width, and a
      // fifth card wrapped onto a row of its own looked like a mistake.
      for (const s of upcoming.slice(0, 4)) grid.appendChild(previewCard(s));
    }

    $("#generated-at").textContent = meta["generated_at"] ?? "";
    loading.style.display = "none";
  } catch (err) {
    // The page still explains what the site does and still accepts a request
    // when the API is unreachable — hiding all of it would be a worse failure
    // than showing it without live numbers.
    loading.textContent = `Live data is unavailable right now (${err}).`;
    loading.style.color = "#fc8181";
  }
  content.style.display = "block";
})();
