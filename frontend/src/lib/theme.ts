export type ThemePref = "light" | "dark" | "system";
const KEY = "sv:theme";

export function getTheme(): ThemePref {
  try {
    const v = localStorage.getItem(KEY);
    return v === "light" || v === "dark" ? v : "system";
  } catch {
    return "system";
  }
}

function apply(pref: ThemePref) {
  const dark =
    pref === "dark" || (pref === "system" && window.matchMedia("(prefers-color-scheme: dark)").matches);
  document.documentElement.classList.toggle("dark", dark);
}

export function setTheme(pref: ThemePref) {
  try {
    if (pref === "system") localStorage.removeItem(KEY);
    else localStorage.setItem(KEY, pref);
  } catch {
    /* storage blocked: still apply for this page */
  }
  apply(pref);
}

/** Keep "system" in step with the OS setting while the app is open. */
export function watchSystemTheme() {
  const mq = window.matchMedia("(prefers-color-scheme: dark)");
  const onChange = () => getTheme() === "system" && apply("system");
  mq.addEventListener("change", onChange);
  return () => mq.removeEventListener("change", onChange);
}
