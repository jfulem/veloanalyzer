import { getRiderDetail, getRiderHistory, getMeta, Rider, RaceResult } from "./api.js";
import { renderRiderCard } from "./ui/RiderCard.js";
import { el } from "./utils.js";
import { initChrome } from "./discipline.js";

const PAGE_LABELS: Record<string, string> = {
  "app":     "Start List",
  "results": "Results",
  "riders":  "Riders",
  "races":   "Races",
};

function backLabel(fromUrl: string): string {
  try {
    const u = new URL(fromUrl, location.href);
    const stem = u.pathname.replace(/^.*\//, "").replace(/\.html$/, "");
    return PAGE_LABELS[stem] ?? "Back";
  } catch {
    return "Back";
  }
}

(async () => {
  const params   = new URLSearchParams(location.search);
  const riderId  = Number(params.get("id"));
  const fromUrl  = params.get("from") ?? "";

  const backBar     = document.getElementById("back-bar")!;
  const loadingEl   = document.getElementById("loading")!;
  const riderCardEl = document.getElementById("rider-card")!;

  // Back button
  const backBtn = el("a", { class: "rider-back-btn", href: fromUrl || "./riders.html" },
    `← ${backLabel(fromUrl)}`);
  backBar.appendChild(backBtn);

  if (!riderId) {
    loadingEl.textContent = "No rider specified.";
    return;
  }

  getMeta().then((m) => {
    document.getElementById("generated-at")!.textContent = m["generated_at"] ?? "";
  }).catch(() => { /* non-critical */ });

  // Show pre-loaded data instantly when navigating from a race page, then
  // silently refresh in the background so direct links still work.
  const cached = sessionStorage.getItem(`rider_${riderId}`);
  if (cached) {
    try {
      const { rider, results } = JSON.parse(cached) as { rider: Rider; results: RaceResult[] };
      document.title = `${rider.first_name} ${rider.last_name} — VeloAnalyzer`;
      renderRiderCard(riderCardEl, rider, results);
      loadingEl.style.display = "none";
      riderCardEl.style.display = "block";
      sessionStorage.removeItem(`rider_${riderId}`);
      return;
    } catch { /* corrupt cache — fall through to fetch */ }
  }

  try {
    const [detail, history] = await Promise.all([
      getRiderDetail(riderId),
      getRiderHistory(riderId),
    ]);

    document.title = `${detail.first_name} ${detail.last_name} — VeloAnalyzer`;

    const rider: Rider = {
      id: detail.id,
      race_id: 0,
      first_name: detail.first_name,
      last_name: detail.last_name,
      corrected_name: "",
      country: detail.country,
      birth_year: detail.birth_year,
      start_nr: "",
      uci_id: detail.uci_id,
      uci_rank: detail.uci_rank,
      uci_points: detail.uci_points,
      cp_xco_points: null,
      computed_points: null,
      result_rank: null,
      result_time: null,
      team: detail.team,
      category: "",
      match_confidence: 100,
      xcodata_slug: detail.xcodata_slug,
      race_name: "",
      last_points_date: null,
    };

    renderRiderCard(riderCardEl, rider, history);
    loadingEl.style.display = "none";
    riderCardEl.style.display = "block";
  } catch (err) {
    loadingEl.textContent = `Failed to load rider: ${err}`;
  }
})();

initChrome();
