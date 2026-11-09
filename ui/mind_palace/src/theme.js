// Управление темой (dark/light) и настройками движения.
//
// Приоритет: явный выбор пользователя (localStorage) → системная схема
// (prefers-color-scheme) → тёмная по умолчанию. Пока пользователь не сделал
// явный выбор, тема следует за системой в реальном времени.

const STORAGE_KEY = "mindpalace.theme";

function readStoredTheme() {
  try {
    const stored = localStorage.getItem(STORAGE_KEY);
    return stored === "light" || stored === "dark" ? stored : null;
  } catch {
    return null;
  }
}

function systemTheme() {
  return window.matchMedia("(prefers-color-scheme: light)").matches ? "light" : "dark";
}

export function currentTheme() {
  return document.documentElement.dataset.theme === "light" ? "light" : "dark";
}

function setTheme(theme, persist) {
  document.documentElement.dataset.theme = theme;
  if (persist) {
    try {
      localStorage.setItem(STORAGE_KEY, theme);
    } catch {
      // localStorage недоступен (приватный режим) — тема просто не сохранится
    }
  }
  document.dispatchEvent(new CustomEvent("themechange", { detail: { theme } }));
}

export function applyTheme(theme) {
  setTheme(theme === "light" ? "light" : "dark", true);
}

export function toggleTheme() {
  setTheme(currentTheme() === "dark" ? "light" : "dark", true);
}

/** Пока нет явного выбора — следим за системной схемой. */
export function watchSystemTheme() {
  if (readStoredTheme()) return;
  const mq = window.matchMedia("(prefers-color-scheme: light)");
  const onChange = (event) => setTheme(event.matches ? "light" : "dark", false);
  if (typeof mq.addEventListener === "function") {
    mq.addEventListener("change", onChange);
  } else if (typeof mq.addListener === "function") {
    mq.addListener(onChange); // старые Safari
  }
}

export function prefersReducedMotion() {
  return window.matchMedia("(prefers-reduced-motion: reduce)").matches;
}

/** Длительность анимации с учётом reduced motion. */
export function motionDuration(normalMs) {
  return prefersReducedMotion() ? 0 : normalMs;
}
