// The page, from the location hash: #/, #/edition/<label>,
// #/edition/<label>/seq/<name>?start=&end=&width=. Links from before the rename (#/flavor/…) are read as #/edition/….

export interface Route {
  parts: string[];
  query: URLSearchParams;
}

function parse(): Route {
  const [path, query = ""] = location.hash.replace(/^#/, "").split("?");
  const parts = path.split("/").filter(Boolean).map(decodeURIComponent);
  if (parts[0] === "flavor") parts[0] = "edition";
  return { parts, query: new URLSearchParams(query) };
}

export const route = $state<{ current: Route }>({ current: parse() });

window.addEventListener("hashchange", () => {
  route.current = parse();
  window.scrollTo(0, 0);
});

export const href = (...parts: string[]) => "#/" + parts.map(encodeURIComponent).join("/");
