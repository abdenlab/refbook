// The page, from the location hash: #/, #/catalog, #/catalog/<assembly>[/edition/<label>[/seq/<name>?start=&end=]],
// #/editor, #/editor/<assembly>, #/sequences?q=, #/sequence/<SQ.>, #/identify, #/learn.

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
