// The page, from the location hash: #/, #/flavor/<label>,
// #/flavor/<label>/seq/<name>?start=&end=&width=.

export interface Route {
  parts: string[];
  query: URLSearchParams;
}

function parse(): Route {
  const [path, query = ""] = location.hash.replace(/^#/, "").split("?");
  return { parts: path.split("/").filter(Boolean).map(decodeURIComponent), query: new URLSearchParams(query) };
}

export const route = $state<{ current: Route }>({ current: parse() });

window.addEventListener("hashchange", () => {
  route.current = parse();
  window.scrollTo(0, 0);
});

export const href = (...parts: string[]) => "#/" + parts.map(encodeURIComponent).join("/");
