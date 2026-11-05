// A region of one sequence of a flavor: its bases, built in the browser from
// the root's bases and the flavor's operations, with what the operations
// changed marked. Coordinates are shown 1-based, inclusive, as genome
// browsers show them.
import type { Blocks } from "../data/blocks.ts";
import type { Catalog } from "../data/catalog.ts";
import { manifest, OPERATION_LABELS, region, verify, type ManifestRow } from "../data/flavors.ts";
import { measure } from "../data/meter.ts";
import { bp, errorBox, h, n } from "../ui.ts";

const LINE = 60;
const WIDTHS = [600, 1200, 6000];

/** Where to start by default: after a leading run of N (chromosomes begin with telomere gaps). */
async function firstBase(cat: Catalog, row: ManifestRow): Promise<number> {
  const runs = await cat.table<{ root_id: string; start: number; end: number }>("layer_n_runs.parquet");
  const lead = runs.find((r) => r.root_id === row.root_id && r.start === 0);
  return lead && lead.end < row.length ? lead.end : 0;
}

function parseLocus(text: string, length: number): [number, number] | null {
  const m = /^\s*(?:[^:]+:)?([\d,]+)\s*[-–]\s*([\d,]+)\s*$/.exec(text);
  if (!m) return null;
  const [s, e] = [Number(m[1].replaceAll(",", "")), Number(m[2].replaceAll(",", ""))];
  if (!(s >= 1 && e >= s && e <= length)) return null;
  return [s - 1, e];
}

/** The bases as lines, with runs of N and of bases the operations changed marked. */
function basesBlock(start: number, bases: Uint8Array, root: Uint8Array): HTMLElement {
  const pre = h("pre", { class: "bases" });
  const decode = (a: Uint8Array) => new TextDecoder().decode(a);
  const gutter = n(start + bases.length).length;
  for (let i = 0; i < bases.length; i += LINE) {
    const line = h("div", { class: "line" }, h("span", { class: "pos" }, n(start + i + 1).padStart(gutter)), " ");
    let j = i;
    const end = Math.min(i + LINE, bases.length);
    while (j < end) {
      const kind = (k: number) => (bases[k] !== root[k] ? "changed" : bases[k] === 78 ? "n" : "");
      const c = kind(j);
      let k = j + 1;
      while (k < end && kind(k) === c) k++;
      const text = decode(bases.subarray(j, k));
      line.append(c ? h("span", { class: c, title: c === "changed" ? `as submitted: ${decode(root.subarray(j, k))}` : null }, text) : text);
      j = k;
    }
    pre.append(line);
  }
  return pre;
}

export async function sequenceView(cat: Catalog, blocks: () => Promise<Blocks>, label: string, name: string, params: URLSearchParams): Promise<HTMLElement> {
  const rows = await manifest(cat, label);
  const row = rows.find((r) => r.name === name);
  const crumbs = h("p", { class: "crumbs" }, h("a", { href: "#/" }, "Catalog"), " / ",
    h("a", { href: `#/flavor/${encodeURIComponent(label)}` }, label), " / ", name);
  if (!row) return h("section", {}, crumbs, h("h1", {}, "No such sequence"));
  const store = await blocks();
  if (!store.hosts(row.root_id)) {
    return h("section", {}, crumbs, h("h1", {}, name),
      h("p", {}, `${row.root_id} is an external root: refbook lists it with its digests, but does not host its bases.`));
  }

  const width = WIDTHS.includes(Number(params.get("width"))) ? Number(params.get("width")) : 1200;
  let start = params.has("start") ? Math.max(0, Number(params.get("start"))) : await firstBase(cat, row);
  start = Math.min(start, Math.max(0, row.length - 1));
  const end = Math.min(row.length, params.has("end") ? Number(params.get("end")) : start + width);
  const go = (s: number, e: number, w = width) => {
    const p = new URLSearchParams({ start: String(Math.max(0, s)), end: String(Math.min(row.length, e)), width: String(w) });
    location.hash = `#/flavor/${encodeURIComponent(label)}/seq/${encodeURIComponent(name)}?${p}`;
  };

  const view = h("div", { class: "view" }, h("p", { class: "muted" }, "Reading bases…"));
  const locus = h("input", { class: "locus", value: `${name}:${n(start + 1)}-${n(end)}`, "aria-label": "Region, 1-based inclusive" });
  const submit = (e: Event) => {
    e.preventDefault();
    const r = parseLocus(locus.value, row.length);
    if (r) go(r[0], r[1]);
    else locus.setCustomValidity(`A region within 1-${n(row.length)}, e.g. ${name}:1,000,001-1,001,200`), locus.reportValidity();
  };
  locus.addEventListener("input", () => locus.setCustomValidity(""));
  const span = end - start;
  const widthSelect = h("select", { "aria-label": "Bases shown", onchange: (e: Event) => go(start, start + Number((e.target as HTMLSelectElement).value), Number((e.target as HTMLSelectElement).value)) },
    WIDTHS.map((w) => h("option", { value: w, selected: w === width }, `${n(w)} bp`)));
  const checkOut = h("span", { class: "muted" });
  const check = h("button", { type: "button" }, "Check the whole sequence");
  check.addEventListener("click", async () => {
    check.disabled = true;
    checkOut.textContent = ` building ${bp(row.length, true)}…`;
    try {
      const ok = await measure(`check ${name}`, () => verify(cat, store, row));
      checkOut.textContent = ok ? " ✓ matches its MD5 and SQ. digest" : " ✗ does not match its digests";
      checkOut.className = ok ? "ok" : "bad";
    } catch (e) {
      checkOut.textContent = ` ${(e as Error).message}`;
    } finally {
      check.disabled = false;
    }
  });

  const section = h("section", {}, crumbs,
    h("h1", {}, name),
    h("p", { class: "lede" }, `${bp(row.length)}, from root `, h("code", {}, row.root_id),
      row.operations.length ? ` with ${row.operations.map((o) => OPERATION_LABELS[o] ?? o).join(" and ")}` : ", as submitted", "."),
    h("form", { class: "controls", onsubmit: submit },
      h("button", { type: "button", onclick: () => go(start - span, start), disabled: start === 0 }, "←"),
      locus, h("button", { type: "submit" }, "Go"),
      h("button", { type: "button", onclick: () => go(end, end + span), disabled: end >= row.length }, "→"),
      widthSelect),
    row.operations.length ? h("p", { class: "legend" }, h("span", { class: "changed" }, "ACGT"), " changed by the operations (hover for the bases as submitted)  ", h("span", { class: "n" }, "N"), " unknown") : null,
    view,
    h("p", {}, check, checkOut));

  measure(`view ${name}:${start + 1}-${end}`, () => region(cat, store, row, start, end))
    .then(({ bases, root }) => view.replaceChildren(basesBlock(start, bases, root)))
    .catch((e) => view.replaceChildren(errorBox(e)));
  return section;
}
