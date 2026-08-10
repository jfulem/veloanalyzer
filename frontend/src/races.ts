import {
  getRaceStats, getMeta, catBadge, todayIso, el,
  UCI_CAT_LABEL, RaceStat,
} from "./raceStats.js";

function $(sel: string): HTMLElement {
  const node = document.querySelector<HTMLElement>(sel);
  if (!node) throw new Error(`Missing element: ${sel}`);
  return node;
}

function num(value: number | null, prefix = ""): string {
  return value === null || value === undefined ? "—" : `${prefix}${value}`;
}

function row(s: RaceStat, destination: string): HTMLTableRowElement {
  const tr = document.createElement("tr");
  tr.dataset["cat"] = s.uci_category;

  tr.appendChild(el("td", {}, s.date ?? ""));

  const nameCell = el("td");
  const link = el("a", { href: `./${destination}#race=${encodeURIComponent(s.slug)}` }, s.name);
  nameCell.appendChild(link);
  tr.appendChild(nameCell);

  const catCell = el("td");
  catCell.appendChild(catBadge(s.uci_category));
  catCell.appendChild(document.createTextNode(` ${s.category}`));
  tr.appendChild(catCell);

  tr.appendChild(el("td", { class: "num" }, String(s.total)));
  tr.appendChild(el("td", { class: "num" }, String(s.ranked)));
  tr.appendChild(el("td", { class: "num" }, num(s.best, "#")));
  tr.appendChild(el("td", { class: "num" }, num(s.avg, "#")));
  return tr;
}

function section(container: HTMLElement, title: string, rows: RaceStat[], destination: string): void {
  container.appendChild(el("p", { class: "section-title" }, `${title} (${rows.length})`));
  if (rows.length === 0) {
    container.appendChild(el("p", { class: "h2h-empty" }, "None."));
    return;
  }

  const table = el("table", { class: "h2h-table" }) as HTMLTableElement;
  const thead = el("thead");
  const headRow = document.createElement("tr");
  for (const [label, cls] of [
    ["Date", ""], ["Race", ""], ["Category", ""],
    ["Riders", "num"], ["Ranked", "num"], ["Best", "num"], ["Avg rank", "num"],
  ] as [string, string][]) {
    headRow.appendChild(el("th", cls ? { class: cls } : {}, label));
  }
  thead.appendChild(headRow);
  table.appendChild(thead);

  const tbody = el("tbody");
  for (const s of rows) tbody.appendChild(row(s, destination));
  table.appendChild(tbody);
  container.appendChild(table);
}

function buildLegend(container: HTMLElement): void {
  for (const [cat, label] of Object.entries(UCI_CAT_LABEL)) {
    const btn = el("button", { class: "legend-item" }) as HTMLButtonElement;
    btn.dataset["cat"] = cat;
    btn.appendChild(catBadge(cat));
    btn.appendChild(document.createTextNode(` ${label}`));
    container.appendChild(btn);
  }

  container.addEventListener("click", (e) => {
    const btn = (e.target as HTMLElement).closest<HTMLElement>(".legend-item");
    if (!btn) return;
    const wasActive = btn.classList.contains("active");
    container.querySelectorAll(".legend-item").forEach((b) => b.classList.remove("active"));
    document.querySelectorAll<HTMLTableRowElement>("tr[data-cat]")
      .forEach((tr) => { tr.style.display = ""; });
    if (wasActive) return;
    btn.classList.add("active");
    document.querySelectorAll<HTMLTableRowElement>("tr[data-cat]").forEach((tr) => {
      if (tr.dataset["cat"] !== btn.dataset["cat"]) tr.style.display = "none";
    });
  });
}

(async () => {
  const loading = $("#loading");
  let stats: RaceStat[];
  let meta: Record<string, string>;
  try {
    [stats, meta] = await Promise.all([getRaceStats(), getMeta()]);
  } catch (err) {
    loading.textContent = `Failed to reach the API: ${err}`;
    return;
  }

  const today = todayIso();
  const upcoming = stats.filter((s) => s.date && s.date >= today);
  const past = stats.filter((s) => !s.date || s.date < today).reverse();

  buildLegend($("#cat-legend"));
  section($("#upcoming-section"), "Upcoming races", upcoming, "app.html");
  section($("#past-section"), "Past races", past, "results.html");

  $("#generated-at").textContent = meta["generated_at"] ?? "";
  loading.style.display = "none";
  $("#content").style.display = "block";
})();
