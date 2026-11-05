// A flavor: its identity, its recipe (roots → operations → names → output),
// the files that reproduce it, exports, and its sequences.
import * as rb from "@abdenlab/refbook";
import type { Catalog } from "../data/catalog.ts";
import { chromSizes, inOrder, sequenceDictionary } from "../data/exports.ts";
import { flavors, manifest, OPERATION_LABELS, targetOrder, targets, type Flavor, type ManifestRow } from "../data/flavors.ts";
import { measure } from "../data/meter.ts";
import { bp, digest, download, h, n } from "../ui.ts";

const ROLE_LABELS: Record<string, string> = {
  "assembled-molecule": "chromosomes", "unlocalized-scaffold": "unlocalized scaffolds",
  "unplaced-scaffold": "unplaced scaffolds", "alt-scaffold": "alt scaffolds",
  "fix-patch": "fix patches", "novel-patch": "novel patches",
};
const role = (r: string) => ROLE_LABELS[r] ?? r;

interface Recipe {
  select: ({ assembly: string; roles: string[]; accessions?: string[]; placed_on?: string[] }
    | { roots: string[] } | { collection: string; groups: string[] })[];
  mask?: { layer: string; with: string }[];
  alphabet?: { iupac?: string };
  rename: { namespace: string; by_role?: Record<string, string>; map?: Record<string, string>; template?: Record<string, string> };
}

async function assemblyNames(cat: Catalog): Promise<Map<string, string>> {
  const members = await cat.table<{ assembly_accession: string; assembly_name: string }>("assembly_members.parquet");
  return new Map(members.map((m) => [m.assembly_accession, m.assembly_name]));
}

function card(title: string, ...body: Parameters<typeof h>[2][]): HTMLElement {
  return h("div", { class: "card" }, h("h3", {}, title), ...body);
}

function recipeDiagram(f: Flavor, recipe: Recipe, rows: ManifestRow[], names: Map<string, string>): HTMLElement {
  const select = recipe.select.map((e) => {
    if ("assembly" in e) {
      return h("div", { class: "entry" },
        h("div", {}, h("strong", {}, names.get(e.assembly) ?? e.assembly), " ", h("code", {}, e.assembly)),
        h("div", {}, e.roles.map(role).join(", ")),
        e.placed_on ? h("div", { class: "muted" }, `only those placed on: ${e.placed_on.join(", ")}`) : null,
        e.accessions ? h("div", { class: "muted" }, `only ${e.accessions.join(", ")}`) : null);
    }
    if ("roots" in e) return h("div", { class: "entry" }, h("strong", {}, "Roots in no assembly"), h("div", {}, e.roots.map((r) => h("code", {}, r, " "))));
    return h("div", { class: "entry" }, h("strong", {}, e.collection), h("div", {}, `groups ${e.groups.join(", ")}`), h("div", { class: "muted" }, "external roots: listed, not hosted"));
  });
  const affected = (op: string) => rows.filter((r) => r.operations.includes(op)).length;
  const ops = f.operations.map((op) => h("div", { class: "entry" },
    h("strong", {}, OPERATION_LABELS[op] ?? op),
    h("div", {}, `changes ${n(affected(op))} of ${n(rows.length)} sequences`)));
  const r = recipe.rename;
  const rename = [
    h("div", { class: "entry" }, "Default: ", h("strong", {}, r.namespace), " names"),
    ...Object.entries(r.by_role ?? {}).map(([k, v]) => h("div", { class: "entry" }, `${role(k)}: `, h("strong", {}, v), " names")),
    ...Object.entries(r.template ?? {}).map(([k, v]) => h("div", { class: "entry" }, `${names.get(k) ?? k}: `, h("code", {}, v))),
    ...Object.entries(r.map ?? {}).map(([k, v]) => h("div", { class: "entry" }, h("code", {}, k), " → ", h("code", {}, v))),
  ];
  const output = [
    h("div", { class: "entry" }, h("strong", {}, `${n(f.n_sequences)} sequences`), h("div", {}, bp(f.total_length))),
    h("ul", { class: "plain" }, f.contents.map((c) => h("li", {}, `${n(c.count)} ${role(c.kind)}`))),
    f.excluded.length ? h("div", { class: "muted" }, "Left out: ", f.excluded.join("; ")) : null,
  ];
  const arrow = () => h("div", { class: "arrow", "aria-hidden": "true" }, "→");
  return h("div", { class: "recipe" },
    card("Select", select), arrow(),
    card("Operations", ops.length ? ops : h("div", { class: "muted entry" }, "None: the roots' bases as submitted")), arrow(),
    card("Rename", rename), arrow(),
    card("Flavor", output));
}

function sequencesTable(f: Flavor, rows: ManifestRow[]): HTMLElement {
  const body = h("tbody");
  const filter = h("input", { type: "search", placeholder: "Filter by name or root", class: "filter", "aria-label": "Filter sequences" });
  const render = () => {
    const q = filter.value.trim().toLowerCase();
    const shown = rows.filter((r) => !q || r.name.toLowerCase().includes(q) || r.root_id.toLowerCase().includes(q));
    body.replaceChildren(...shown.slice(0, 500).map((r) => h("tr", {},
      h("td", {}, h("a", { href: `#/flavor/${encodeURIComponent(f.flavor)}/seq/${encodeURIComponent(r.name)}` }, r.name)),
      h("td", {}, h("code", {}, r.root_id)),
      h("td", {}, r.operations.map((o) => h("span", { class: "op" }, OPERATION_LABELS[o] ?? o))),
      h("td", { class: "num" }, n(r.length)),
      h("td", {}, h("code", { class: "small" }, r.md5)))));
    if (shown.length > 500) body.append(h("tr", {}, h("td", { colspan: 5, class: "muted" }, `and ${n(shown.length - 500)} more: filter to find them`)));
  };
  filter.addEventListener("input", render);
  render();
  return h("div", {}, filter, h("div", { class: "table-wrap" }, h("table", {},
    h("thead", {}, h("tr", {}, h("th", {}, "Name"), h("th", {}, "Root"), h("th", {}, "Operations"), h("th", { class: "num" }, "Length"), h("th", {}, "MD5"))),
    body)));
}

export async function flavorView(cat: Catalog, label: string): Promise<HTMLElement> {
  const [fs, ts, rows, names] = await measure(`flavor ${label}`, () =>
    Promise.all([flavors(cat), targets(cat), manifest(cat, label), assemblyNames(cat)]));
  const f = fs.find((x) => x.flavor === label);
  if (!f) return h("section", {}, h("h1", {}, "No such flavor"), h("p", {}, h("a", { href: "#/" }, "Back to the catalog")));
  const recipe: Recipe = JSON.parse(f.recipe);
  const mine = ts.filter((t) => t.flavor === label);

  const order = h("select", { "aria-label": "Order" },
    h("option", { value: "" }, "canonical order (by name)"),
    mine.map((t) => h("option", { value: t.target }, `${t.publisher}: ${t.alias}`)));
  const ordered = async () => {
    const names = order.value ? await targetOrder(cat, order.value) : undefined;
    return inOrder(rows, names);
  };
  const stem = () => (order.value || label);
  const seqcol = async () => {
    const r = await ordered();
    const args = [r.map((x) => x.name), r.map((x) => x.length), r.map((x) => x.sha512t24u)] as const;
    return JSON.stringify({ names: args[0], lengths: args[1], sequences: args[2], ...rb.seqcolAncillary(...args) }, null, 1);
  };

  return h("section", {},
    h("p", { class: "crumbs" }, h("a", { href: "#/" }, "Catalog"), " / ", label),
    h("h1", {}, label),
    h("p", { class: "lede" }, `${f.assembly}${f.patch_release !== null ? `, patch release ${f.patch_release}` : ""}: `,
      `${n(f.n_sequences)} sequences, ${bp(f.total_length)}. Published as ${n(mine.length)} file${mine.length === 1 ? "" : "s"}.`),

    h("h2", {}, "Identity"),
    h("dl", { class: "ids" },
      h("dt", {}, "Flavor ID"), h("dd", {}, digest(f.id), h("div", { class: "muted" }, "The named sequence set, whatever the order: the level-1 digest of sorted_named_sequences.")),
      h("dt", {}, "Seqcol digest"), h("dd", {}, digest(f.seqcol_digest), h("div", { class: "muted" }, "GA4GH sequence collection, in canonical order (by name). Each published file has its own, for its own order."))),

    h("h2", {}, "Recipe"),
    recipeDiagram(f, recipe, rows, names),

    h("h2", {}, "Published files"),
    h("p", { class: "muted" }, "Each file was rebuilt from the roots by the recipe, sequence by sequence, and matched."),
    h("div", { class: "table-wrap" }, h("table", {},
      h("thead", {}, h("tr", {}, h("th", {}, "Publisher"), h("th", {}, "File"), h("th", {}, "Checked by"), h("th", {}, "Seqcol digest (its order)"))),
      h("tbody", {}, mine.map((t) => h("tr", {},
        h("td", {}, t.publisher),
        h("td", {}, h("a", { href: t.published, rel: "noopener" }, t.alias)),
        h("td", {}, t.evidence === "content" ? "every sequence's bases" : "its .dict (names, lengths, MD5s)"),
        h("td", {}, h("code", { class: "small" }, t.seqcol_digest))))))),

    h("h2", {}, "Export"),
    h("div", { class: "exports" }, order,
      h("button", { type: "button", onclick: async () => download(`${stem()}.chrom.sizes`, chromSizes(await ordered())) }, "chrom.sizes"),
      h("button", { type: "button", onclick: async () => download(`${stem()}.dict`, sequenceDictionary(await ordered())) }, ".dict (with MD5)"),
      h("button", { type: "button", onclick: async () => download(`${stem()}.seqcol.json`, await seqcol(), "application/json") }, "seqcol (level 2)"),
      h("button", { type: "button", onclick: () => download(`${label}.recipe.json`, JSON.stringify(recipe, null, 2), "application/json") }, "recipe")),

    h("h2", {}, "Sequences"),
    sequencesTable(f, rows));
}
