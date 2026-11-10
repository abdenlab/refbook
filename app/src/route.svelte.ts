// The page, from the location hash: #/, #/catalog (books or sequences), #/catalog/books,
// #/catalog/books/<assembly>[/edition/<label>[/seq/<name>?start=&end=]], #/catalog/sequences?q=,
// #/catalog/sequences/<SQ.>, #/editor, #/editor/<assembly>, #/identify, #/about.

export interface Route {
  parts: string[];
  query: URLSearchParams;
}

function parse(): Route {
  const [path, query = ""] = location.hash.replace(/^#/, "").split("?");
  const parts = path.split("/").filter(Boolean).map(decodeURIComponent);
  return { parts, query: new URLSearchParams(query) };
}

export const route = $state<{ current: Route }>({ current: parse() });

window.addEventListener("hashchange", () => {
  route.current = parse();
  window.scrollTo(0, 0);
});

export const href = (...parts: string[]) => "#/" + parts.map(encodeURIComponent).join("/");
