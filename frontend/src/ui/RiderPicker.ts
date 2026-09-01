import { RiderListItem } from "../api.js";
import { el, flagEmoji } from "../utils.js";

const MIN_QUERY_LEN   = 2;
const MAX_SUGGESTIONS = 20;

/**
 * Search-as-you-type rider picker. Standalone (not tied to any one race's
 * field), so the head-to-head page can compare any two riders VeloAnalyzer
 * knows about — the same fused UCI-ranking-plus-tracked set the Riders page
 * shows — not just two riders who happen to share a start list.
 */
export function renderRiderPicker(
  container: HTMLElement,
  riders: RiderListItem[],
  placeholder: string,
  onSelect: (rider: RiderListItem | null) => void,
  initial?: RiderListItem,
): void {
  container.innerHTML = "";
  container.classList.add("rider-picker");

  const input = el("input", {
    type: "search", class: "search-box", placeholder, autocomplete: "off",
  }) as HTMLInputElement;
  const dropdown = el("div", { class: "rider-picker-dropdown" });
  dropdown.hidden = true;
  const selected = el("div", { class: "rider-picker-selected" });
  selected.hidden = true;

  container.appendChild(input);
  container.appendChild(dropdown);
  container.appendChild(selected);

  function showSuggestions(raw: string): void {
    const query = raw.trim().toLowerCase();
    dropdown.innerHTML = "";
    if (query.length < MIN_QUERY_LEN) {
      dropdown.hidden = true;
      return;
    }

    const matches = riders
      .filter((r) => `${r.first_name} ${r.last_name} ${r.country} ${r.team}`.toLowerCase().includes(query))
      .slice(0, MAX_SUGGESTIONS);

    if (matches.length === 0) {
      dropdown.appendChild(el("div", { class: "rider-picker-empty" }, "No riders found"));
      dropdown.hidden = false;
      return;
    }

    for (const r of matches) {
      const item = el("div", { class: "rider-picker-item" });
      item.appendChild(el("span", {}, `${r.first_name} ${r.last_name}`.trim()));
      const metaParts = [r.country, r.uci_category, r.uci_rank != null ? `#${r.uci_rank}` : ""].filter(Boolean);
      item.appendChild(el("span", { class: "rider-picker-meta" }, metaParts.join(" · ")));
      item.addEventListener("click", () => selectRider(r));
      dropdown.appendChild(item);
    }
    dropdown.hidden = false;
  }

  function selectRider(r: RiderListItem): void {
    dropdown.hidden = true;
    dropdown.innerHTML = "";
    input.value = "";
    input.hidden = true;

    selected.innerHTML = "";
    selected.hidden = false;
    selected.appendChild(el("span", { class: "rider-picker-name" },
      `${flagEmoji(r.country)} ${r.first_name} ${r.last_name}`.trim()));
    const clearBtn = el("button", { class: "rider-picker-clear" }, "✕");
    clearBtn.type = "button";
    clearBtn.addEventListener("click", () => {
      selected.hidden = true;
      input.hidden = false;
      input.value = "";
      input.focus();
      onSelect(null);
    });
    selected.appendChild(clearBtn);

    onSelect(r);
  }

  input.addEventListener("input", () => showSuggestions(input.value));
  input.addEventListener("focus", () => {
    if (input.value.trim().length >= MIN_QUERY_LEN) showSuggestions(input.value);
  });
  document.addEventListener("click", (e) => {
    if (!container.contains(e.target as Node)) dropdown.hidden = true;
  });

  if (initial) selectRider(initial);
}
