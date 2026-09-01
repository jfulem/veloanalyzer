import { getAllRiders, getRiderHistory, getMeta, RiderListItem, Rider, RaceResult } from "./api.js";
import { renderRiderPicker } from "./ui/RiderPicker.js";
import { renderH2H } from "./ui/H2H.js";
import { $, applyTwemoji, el } from "./utils.js";

// renderH2H() takes the same per-race-entry Rider shape the start-list pages
// use — adapt the standalone rider record into it rather than changing that
// shared type, same pattern rider.ts already uses to reuse RiderCard.
function toRider(d: RiderListItem): Rider {
  return {
    id: d.id, race_id: 0,
    first_name: d.first_name, last_name: d.last_name, corrected_name: "",
    country: d.country, birth_year: d.birth_year, start_nr: "",
    uci_id: d.uci_id, uci_rank: d.uci_rank, uci_points: d.uci_points,
    cp_xco_points: null, computed_points: null, result_rank: null, result_time: null,
    team: d.team, category: "", match_confidence: 100,
    xcodata_slug: d.xcodata_slug, race_name: "", last_points_date: null,
  };
}

(async () => {
  const loading   = $<HTMLElement>("#loading");
  const content   = $<HTMLElement>("#content");
  const picker1El = $<HTMLElement>("#picker1");
  const picker2El = $<HTMLElement>("#picker2");
  const resultEl  = $<HTMLElement>("#h2h-result");

  let riders: RiderListItem[];
  let meta: Record<string, string>;
  try {
    [riders, meta] = await Promise.all([getAllRiders(), getMeta()]);
  } catch (err) {
    loading.textContent = `Failed to reach the API: ${err}`;
    return;
  }
  $<HTMLElement>("#generated-at").textContent = meta["generated_at"] ?? "";

  let r1: RiderListItem | null = null;
  let r2: RiderListItem | null = null;

  function updateUrl(): void {
    const p = new URLSearchParams();
    if (r1) p.set("r1", String(r1.id));
    if (r2) p.set("r2", String(r2.id));
    const qs = p.toString();
    history.replaceState(null, "", qs ? `?${qs}` : location.pathname);
  }

  async function renderComparison(): Promise<void> {
    updateUrl();
    if (!r1 || !r2) {
      resultEl.innerHTML = "";
      return;
    }
    if (r1.id === r2.id) {
      resultEl.innerHTML = "";
      resultEl.appendChild(el("p", { class: "h2h-empty" }, "Pick two different riders."));
      return;
    }

    resultEl.innerHTML = "";
    resultEl.appendChild(el("p", { class: "h2h-empty" }, "Loading comparison…"));

    const requestFor = [r1.id, r2.id] as [number, number];
    let results1: RaceResult[], results2: RaceResult[];
    try {
      [results1, results2] = await Promise.all([
        getRiderHistory(requestFor[0]),
        getRiderHistory(requestFor[1]),
      ]);
    } catch (err) {
      resultEl.innerHTML = "";
      resultEl.appendChild(el("p", { class: "h2h-empty" }, `Failed to load comparison: ${err}`));
      return;
    }
    // Bail if the user picked someone else while this was in flight.
    if (!r1 || !r2 || r1.id !== requestFor[0] || r2.id !== requestFor[1]) return;

    resultEl.innerHTML = "";
    renderH2H(resultEl, [toRider(r1), toRider(r2)], [...results1, ...results2], [r1.id, r2.id]);
    applyTwemoji(resultEl);
  }

  const params = new URLSearchParams(location.search);
  const initial1 = riders.find((r) => r.id === Number(params.get("r1"))) ?? undefined;
  const initial2 = riders.find((r) => r.id === Number(params.get("r2"))) ?? undefined;

  // Each picker's onSelect fires immediately for its own `initial`, in the
  // order set up below — picker1's fires while r2 is still unset (so
  // renderComparison() no-ops), picker2's fires once both are known, which
  // is what actually triggers the initial comparison. No separate kickoff
  // call needed.
  renderRiderPicker(picker1El, riders, "Search rider 1…", (r) => { r1 = r; renderComparison(); }, initial1);
  renderRiderPicker(picker2El, riders, "Search rider 2…", (r) => { r2 = r; renderComparison(); }, initial2);

  loading.style.display = "none";
  content.style.display = "block";
})();
