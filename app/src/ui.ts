// A few helpers for building pages without a framework.

type Child = Node | string | number | null | undefined | false | Child[];
type Attrs = Record<string, string | number | boolean | EventListener | null | undefined>;

/** An element: h("a", { href: "#/" }, "home"). Attributes starting with "on" are listeners. */
export function h<K extends keyof HTMLElementTagNameMap>(tag: K, attrs: Attrs = {}, ...children: Child[]): HTMLElementTagNameMap[K] {
  const el = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (v === null || v === undefined || v === false) continue;
    if (k.startsWith("on") && typeof v === "function") el.addEventListener(k.slice(2), v);
    else el.setAttribute(k, v === true ? "" : String(v));
  }
  append(el, children);
  return el;
}

function append(el: Node, children: Child[]): void {
  for (const c of children) {
    if (c === null || c === undefined || c === false) continue;
    if (Array.isArray(c)) append(el, c);
    else el.appendChild(typeof c === "object" ? c : document.createTextNode(String(c)));
  }
}

export const n = (x: number) => x.toLocaleString("en-US");

/** A length in bases: 3,099,922,541 bp, or 3.10 Gb in tight places. */
export function bp(x: number, short = false): string {
  if (!short) return `${n(x)} bp`;
  for (const [unit, size] of [["Gb", 1e9], ["Mb", 1e6], ["kb", 1e3]] as const) {
    if (x >= size) return `${(x / size).toFixed(x >= 10 * size ? 1 : 2)} ${unit}`;
  }
  return `${x} bp`;
}

export function bytes(x: number): string {
  if (x >= 1e6) return `${(x / 1e6).toFixed(2)} MB`;
  if (x >= 1e3) return `${(x / 1e3).toFixed(1)} kB`;
  return `${x} B`;
}

/** A digest in monospace with a copy button. */
export function digest(value: string): HTMLElement {
  const copy = h("button", { class: "copy", title: "Copy", type: "button" }, "copy");
  copy.addEventListener("click", async () => {
    await navigator.clipboard?.writeText(value);
    copy.textContent = "copied";
    setTimeout(() => (copy.textContent = "copy"), 1200);
  });
  return h("span", { class: "digest" }, h("code", {}, value), copy);
}

/** Offer text as a file to save. */
export function download(filename: string, text: string, type = "text/plain"): void {
  const url = URL.createObjectURL(new Blob([text], { type }));
  const a = h("a", { href: url, download: filename });
  document.body.appendChild(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

export function errorBox(e: unknown): HTMLElement {
  return h("div", { class: "error" }, h("strong", {}, "Something went wrong. "), String((e as Error)?.message ?? e));
}
