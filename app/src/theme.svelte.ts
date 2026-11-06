// The colour theme: the system's (no data-theme on <html>), or light or dark as chosen in the header.
// Remembered in this browser; index.html applies it before the page paints.

export type Theme = "system" | "light" | "dark";
const KEY = "refbook-theme";

function saved(): Theme {
  try {
    const t = localStorage.getItem(KEY);
    return t === "light" || t === "dark" ? t : "system";
  } catch {
    return "system";
  }
}

export const theme = $state<{ current: Theme }>({ current: saved() });

export function setTheme(t: Theme) {
  theme.current = t;
  if (t === "system") delete document.documentElement.dataset.theme;
  else document.documentElement.dataset.theme = t;
  try {
    if (t === "system") localStorage.removeItem(KEY);
    else localStorage.setItem(KEY, t);
  } catch {
    // Storage can be blocked: the choice then lasts until the page reloads.
  }
}

/** The next in the cycle the header button steps through. */
export const NEXT: Record<Theme, Theme> = { system: "light", light: "dark", dark: "system" };
export const LABEL: Record<Theme, string> = {
  system: "Theme: as the system's", light: "Theme: light", dark: "Theme: dark",
};
