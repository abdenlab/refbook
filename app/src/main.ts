import "./style.css";
import { init } from "@abdenlab/refbook";
import { Blocks } from "./data/blocks.ts";
import { Catalog } from "./data/catalog.ts";
import { measure, onMeasure } from "./data/meter.ts";
import { bytes, errorBox, h } from "./ui.ts";
import { catalogView } from "./views/catalog.ts";
import { flavorView } from "./views/flavor.ts";
import { sequenceView } from "./views/sequence.ts";

// The catalog: ?catalog=<url> on the page, else VITE_CATALOG_URL at build
// time, else /catalog/ (the dev server's copy of the repository's build).
const catalogUrl = new URLSearchParams(location.search).get("catalog") ?? import.meta.env.VITE_CATALOG_URL ?? "/catalog/";

const app = document.getElementById("app")!;
const meter = document.getElementById("meter")!;

// What each action downloaded: the measurement of whether a static catalog is enough.
const log: HTMLElement[] = [];
onMeasure((action, t, total) => {
  log.unshift(h("li", {}, h("span", { class: "action" }, action), ` ${t.requests} req, ${bytes(t.bytes)}, ${t.ms.toFixed(0)} ms`));
  log.length = Math.min(log.length, 4);
  meter.replaceChildren(
    h("span", { class: "total" }, `Downloaded this session: ${total.requests} requests, ${bytes(total.bytes)}`),
    h("ul", {}, log));
});

async function main() {
  await init();
  const cat = await measure("open catalog", () => Catalog.open(catalogUrl));
  let blocks: Promise<Blocks> | null = null;
  const openBlocks = () => (blocks ??= measure("open root_blocks", () => Blocks.open(cat)));

  async function route() {
    const [path, query = ""] = location.hash.replace(/^#/, "").split("?");
    const parts = path.split("/").filter(Boolean).map(decodeURIComponent);
    let page: Promise<HTMLElement>;
    if (parts[0] === "flavor" && parts[2] === "seq" && parts[3]) page = sequenceView(cat, openBlocks, parts[1], parts[3], new URLSearchParams(query));
    else if (parts[0] === "flavor" && parts[1]) page = flavorView(cat, parts[1]);
    else page = measure("catalog", () => catalogView(cat));
    try {
      app.replaceChildren(await page);
      document.title = parts.length ? `${parts.at(-1)} · refbook` : "refbook";
    } catch (e) {
      app.replaceChildren(errorBox(e));
    }
    window.scrollTo(0, 0);
  }
  window.addEventListener("hashchange", route);
  await route();
}

main().catch((e) => app.replaceChildren(errorBox(e), h("p", { class: "muted" }, `Catalog: ${catalogUrl}`)));
