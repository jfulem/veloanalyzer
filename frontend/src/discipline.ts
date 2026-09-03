// Which discipline the site is showing. One value, read from the URL and
// remembered between pages, threaded onto every API request.
//
// It lives in the query string rather than only in storage so a link to a
// cyclo-cross page stays a cyclo-cross page when it is shared, and in storage
// as well so following the sidebar to another page doesn't silently drop back
// to MTB.

const STORAGE_KEY = "veloanalyzer.discipline";

export const DISCIPLINES = ["XCO", "CX"] as const;
export type Discipline = (typeof DISCIPLINES)[number];

export const DISCIPLINE_LABEL: Record<Discipline, string> = {
  XCO: "MTB XCO",
  CX: "Cyclo-cross",
};

const DISCIPLINE_EMOJI: Record<Discipline, string> = {
  XCO: "🚵",
  CX: "🚴",
};

export const DEFAULT_DISCIPLINE: Discipline = "XCO";

function isDiscipline(value: string): value is Discipline {
  return (DISCIPLINES as readonly string[]).includes(value);
}

function fromStorage(): Discipline | null {
  // Private windows and blocked site data make this throw rather than return
  // null, and a remembered filter is never worth a blank page.
  try {
    const stored = localStorage.getItem(STORAGE_KEY) ?? "";
    return isDiscipline(stored) ? stored : null;
  } catch {
    return null;
  }
}

/** The active discipline: ?discipline= wins, then the last one chosen, then
 *  MTB XCO — which is what every row in a database predating cyclo-cross is. */
export function current(): Discipline {
  const fromUrl = (new URLSearchParams(location.search).get("discipline") ?? "").toUpperCase();
  if (isDiscipline(fromUrl)) return fromUrl;
  return fromStorage() ?? DEFAULT_DISCIPLINE;
}

/** Append ?discipline= to an API path, preserving any query it already has. */
export function apiQuery(path: string): string {
  return `${path}${path.includes("?") ? "&" : "?"}discipline=${current()}`;
}

/** Rewrite an in-site href so it keeps the active discipline. */
export function withDiscipline(href: string): string {
  const disc = current();
  if (disc === DEFAULT_DISCIPLINE) return href;
  const [base, hash = ""] = href.split("#");
  const sep = base!.includes("?") ? "&" : "?";
  return `${base}${sep}discipline=${disc}${hash ? `#${hash}` : ""}`;
}

/** This page's URL with the discipline swapped — the tab's href. */
function urlFor(disc: Discipline): string {
  const url = new URL(location.href);
  url.searchParams.set("discipline", disc);
  return url.toString();
}

function remember(disc: Discipline): void {
  try {
    localStorage.setItem(STORAGE_KEY, disc);
  } catch {
    // Storage unavailable — the href still carries the choice, so the click
    // works; only the preference between visits is lost.
  }
}

interface DisciplineRow {
  discipline: string;
  races: number;
}

const API_BASE = (import.meta.env["VITE_API_BASE"] ?? "").replace(/\/$/, "");

/** Render the switcher into `container`, but only once the API confirms there
 *  is more than one discipline to switch between — an MTB-only database gets
 *  the site exactly as it was, with no stray control. */
export async function mountDisciplineSwitch(container: HTMLElement | null): Promise<void> {
  if (!container) return;

  let available: Discipline[];
  try {
    const resp = await fetch(`${API_BASE}/api/disciplines`);
    if (!resp.ok) return;
    const rows = (await resp.json()) as DisciplineRow[];
    available = DISCIPLINES.filter((d) =>
      rows.some((r) => r.discipline === d && r.races > 0),
    );
  } catch {
    return;
  }
  if (available.length < 2) return;

  const active = current();
  container.innerHTML = "";
  container.classList.add("discipline-switch");

  // Links rather than buttons: choosing a discipline really is a navigation to
  // a different URL, so this way middle-click and "open in new tab" work, the
  // status bar previews the destination, and the choice survives even when
  // localStorage throws. The click handler only records the preference — it
  // never preventDefault()s, so the browser does the navigating.
  for (const disc of available) {
    const tab = document.createElement("a");
    tab.className = "discipline-option";
    tab.href = urlFor(disc);

    const icon = document.createElement("span");
    icon.className = "icon";
    icon.textContent = DISCIPLINE_EMOJI[disc];
    tab.appendChild(icon);
    tab.appendChild(document.createTextNode(DISCIPLINE_LABEL[disc]));

    if (disc === active) {
      tab.classList.add("is-active");
      tab.setAttribute("aria-current", "page");
    }
    tab.addEventListener("click", () => remember(disc));
    container.appendChild(tab);
  }
}

/** Point every in-site link at the active discipline, so moving between pages
 *  doesn't quietly reset the filter for anyone whose storage is unavailable. */
export function linkNav(root: ParentNode = document): void {
  if (current() === DEFAULT_DISCIPLINE) return;
  root.querySelectorAll<HTMLAnchorElement>(".side-nav a, a.brand, a.see-all").forEach((link) => {
    const href = link.getAttribute("href");
    if (href && href.startsWith("./")) link.setAttribute("href", withDiscipline(href));
  });
}

/** Swap any element marked `data-disc-label` for the active discipline's name.
 *  A handful of headings name the discipline in prose ("every MTB XCO start
 *  list"); marking those beats leaving them lying about what is on the page. */
export function labelDiscipline(root: ParentNode = document): void {
  const label = DISCIPLINE_LABEL[current()];
  root.querySelectorAll<HTMLElement>("[data-disc-label]").forEach((node) => {
    node.textContent = label;
  });
}

/** Page chrome common to every entry point: the discipline tabs and
 *  discipline-preserving links. Called once per page rather than run as an
 *  import side effect, so a page that needs neither can simply not call it.
 *  The container is created here instead of being added to nine HTML files,
 *  which would only ever differ from each other by drifting.
 *
 *  The tabs go directly below the brand and above the nav: they change which
 *  sport the entire site is showing, so they outrank the choice of page and
 *  should be read before it, not found underneath it. */
export function initChrome(): void {
  linkNav();
  labelDiscipline();
  const nav = document.querySelector(".side-nav");
  if (!nav || !nav.parentElement) return;
  let host = document.getElementById("discipline-switch");
  if (!host) {
    host = document.createElement("div");
    host.id = "discipline-switch";
    nav.parentElement.insertBefore(host, nav);
  }
  // Deliberately not awaited: it is one small request, and no other content on
  // the page depends on the answer.
  void mountDisciplineSwitch(host);
}
