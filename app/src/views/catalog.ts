// The catalog: every flavor, what it holds, and the files that reproduce it.
import type { Catalog } from "../data/catalog.ts";
import { flavors, OPERATION_LABELS, targets } from "../data/flavors.ts";
import { bp, h, n } from "../ui.ts";

export async function catalogView(cat: Catalog): Promise<HTMLElement> {
  const [fs, ts] = await Promise.all([flavors(cat), targets(cat)]);
  const byFlavor = Map.groupBy(ts, (t) => t.flavor);
  const rows = [...fs].sort((a, b) => a.n_sequences - b.n_sequences || a.flavor.localeCompare(b.flavor));
  return h("section", {},
    h("h1", {}, "GRCh38, as published"),
    h("p", { class: "lede" },
      `"GRCh38" names many different files. They include different sequences, name and order them differently, and some mask or rewrite bases. `,
      `refbook describes each as a recipe over the same original INSDC sequences, and checks it by rebuilding the published file. `,
      `The ${n(ts.length)} files below reduce to ${n(fs.length)} flavors: distinct sets of named sequences.`),
    h("div", { class: "table-wrap" },
      h("table", { class: "flavors" },
        h("thead", {}, h("tr", {},
          h("th", {}, "Flavor"), h("th", { class: "num" }, "Sequences"), h("th", { class: "num" }, "Length"),
          h("th", {}, "Operations"), h("th", {}, "Naming"), h("th", {}, "Published as"))),
        h("tbody", {}, rows.map((f) => h("tr", {},
          h("td", {}, h("a", { href: `#/flavor/${encodeURIComponent(f.flavor)}` }, f.flavor),
            f.patch_release !== null ? h("span", { class: "tag" }, `p${f.patch_release}`) : null),
          h("td", { class: "num" }, n(f.n_sequences)),
          h("td", { class: "num" }, bp(f.total_length, true)),
          h("td", {}, f.operations.length ? f.operations.map((o) => h("span", { class: "op" }, OPERATION_LABELS[o] ?? o)) : h("span", { class: "muted" }, "none")),
          h("td", { class: "naming" }, f.naming.split(";")[0]),
          h("td", {}, h("ul", { class: "plain" }, (byFlavor.get(f.flavor) ?? []).map((t) =>
            h("li", {}, h("span", { class: "publisher" }, t.publisher), " ", h("span", { class: "alias" }, t.alias))))),
        )))),
    ),
  );
}
