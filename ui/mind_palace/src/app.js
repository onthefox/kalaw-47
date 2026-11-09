// Точка входа MindPalace: компоновка, состояние, фильтры, связывание модулей.

import {
  API_URL,
  LINK_LABELS,
  LINK_TYPES,
  describeIntentResult,
  fetchEntities,
  fetchEvents,
  fetchLinks,
  parseMeta,
  sendIntent,
} from "./api.js";
import { currentTheme, toggleTheme, watchSystemTheme } from "./theme.js";
import { MindGraph } from "./graph.js";

const SHELL_HTML = `
<header class="topbar">
  <div class="brand">
    <span class="brand-mark" aria-hidden="true">◉</span>
    <span class="brand-name">MindPalace</span>
    <span class="brand-sub">Adapt SymbioSystem</span>
  </div>
  <div class="topbar-actions">
    <input id="search" class="search" type="search" placeholder="Поиск: имя или тег   (/)"
      aria-label="Поиск сущностей по имени или тегу" autocomplete="off" />
    <button id="refresh-btn" class="btn btn-icon" type="button" title="Обновить данные" aria-label="Обновить данные">⟳</button>
    <button id="theme-btn" class="btn btn-icon" type="button" aria-label="Переключить тему">◐</button>
  </div>
</header>
<div class="layout">
  <aside class="sidebar" aria-label="Фильтры и команда">
    <section class="panel filters" aria-labelledby="filters-title">
      <h2 id="filters-title">Фильтры</h2>
      <fieldset class="filter-group">
        <legend>Связи</legend>
        <div id="linktype-filters" class="check-list"></div>
      </fieldset>
      <fieldset class="filter-group">
        <legend>Теги</legend>
        <div id="tag-filters" class="chip-row"></div>
        <p id="tags-empty" class="hint" hidden>Теги появятся, когда сущности получат их через «добавить тег».</p>
      </fieldset>
      <fieldset class="filter-group">
        <legend>Приоритет</legend>
        <div id="priority-filters" class="chip-row"></div>
      </fieldset>
      <fieldset class="filter-group">
        <legend>Период создания</legend>
        <div class="date-row">
          <label>с <input type="date" id="date-from" aria-label="Дата создания, от" /></label>
          <label>по <input type="date" id="date-to" aria-label="Дата создания, до" /></label>
        </div>
        <p id="date-hint" class="hint" hidden></p>
      </fieldset>
      <button id="reset-filters" class="btn btn-ghost" type="button">Сбросить фильтры</button>
    </section>
    <section class="panel command" aria-labelledby="command-title">
      <h2 id="command-title">Намерение</h2>
      <form id="intent-form">
        <label class="visually-hidden" for="intent-input">Намерение, например «создать грядка»</label>
        <input id="intent-input" type="text" placeholder="создать грядка" autocomplete="off" />
        <button id="intent-submit" class="btn btn-primary" type="submit">Отправить</button>
      </form>
      <p id="intent-feedback" class="hint" role="status" aria-live="polite"></p>
    </section>
  </aside>
  <main id="graph-region" class="graph-region" aria-label="Граф сущностей">
    <div id="graph" class="graph-holder"></div>
    <div class="graph-toolbar" role="group" aria-label="Управление графом">
      <button id="zoom-in" class="btn btn-icon" type="button" aria-label="Приблизить" title="Приблизить">+</button>
      <button id="zoom-out" class="btn btn-icon" type="button" aria-label="Отдалить" title="Отдалить">−</button>
      <button id="fit" class="btn btn-icon" type="button" aria-label="Показать весь граф" title="Показать весь граф">⌂</button>
    </div>
    <div id="state-overlay" class="state-overlay"></div>
  </main>
</div>
<footer class="statusbar">
  <span id="conn-dot" class="conn-dot" role="img" aria-label="Состояние соединения"></span>
  <span id="stats-line">Загрузка…</span>
  <span id="api-line" class="api-line"></span>
</footer>
<div id="toasts" class="toasts" aria-live="polite"></div>
`;

const state = {
  entities: [],
  links: [],
  loading: true,
  error: "",
  search: "",
  linkTypes: new Set(LINK_TYPES),
  tags: new Set(),
  priorities: new Set(),
  dateFrom: "",
  dateTo: "",
  selectedId: null,
};

/** name → самая ранняя entity.created (unix, сек); основа фильтра «Период». */
let createdIndex = new Map();

let graph = null;
let inFlight = false;

const el = {};

function qs(id) {
  return document.getElementById(id);
}

function showToast(message, kind = "info", timeout = 4000) {
  const toast = document.createElement("div");
  toast.className = `toast toast-${kind}`;
  toast.textContent = message;
  el.toasts.appendChild(toast);
  window.setTimeout(() => toast.remove(), timeout);
}

function setBusy(b) {
  el.intentSubmit.disabled = b;
  el.intentSubmit.textContent = b ? "…" : "Отправить";
}

async function runIntent(text) {
  el.intentFeedback.textContent = "Думаю…";
  el.intentFeedback.classList.remove("intent-error");
  setBusy(true);
  try {
    const result = await sendIntent(text);
    const message = describeIntentResult(result);
    if (message == null) {
      el.intentFeedback.textContent = result.error || "Не удалось выполнить";
      el.intentFeedback.classList.add("intent-error");
    } else {
      el.intentFeedback.textContent = message;
      showToast(message, result.question ? "info" : "ok", result.question ? 7000 : 4000);
    }
    await refresh();
  } catch (err) {
    el.intentFeedback.textContent = err.message;
    el.intentFeedback.classList.add("intent-error");
    showToast(err.message, "error");
  } finally {
    setBusy(false);
  }
}

async function refresh() {
  if (inFlight) return;
  inFlight = true;
  try {
    const [entities, links] = await Promise.all([fetchEntities(), fetchLinks()]);
    state.entities = entities;
    state.links = links;
    state.error = "";
    try {
      const created = await fetchEvents({ eventType: "entity.created", limit: 1000 });
      createdIndex = new Map();
      for (const ev of created) {
        if (!ev || !ev.entity) continue;
        const prev = createdIndex.get(ev.entity);
        if (prev == null || ev.ts < prev) createdIndex.set(ev.entity, ev.ts);
      }
    } catch {
      createdIndex = new Map();
    }
    buildFilterOptions();
    render();
    setConnection(true);
  } catch (err) {
    state.error = err.message;
    render();
    setConnection(false);
  } finally {
    state.loading = false;
    inFlight = false;
  }
}

function setConnection(ok) {
  el.connDot.classList.toggle("ok", ok);
  el.connDot.classList.toggle("fail", !ok);
  el.connDot.setAttribute("aria-label", ok ? "Соединение с API установлено" : "Нет соединения с API");
  el.statsLine.textContent = ok
    ? `Сущностей: ${state.entities.length} · Связей: ${state.links.length}`
    : "Нет данных";
}

function buildFilterOptions() {
  const linkCounts = new Map();
  for (const link of state.links) {
    linkCounts.set(link.type, (linkCounts.get(link.type) || 0) + 1);
  }
  renderLinkTypeFilters(linkCounts);

  const tagCounts = new Map();
  for (const entity of state.entities) {
    const meta = parseMeta(entity);
    const tags = Array.isArray(meta.tags) ? meta.tags : [];
    for (const tag of tags) {
      const key = String(tag);
      tagCounts.set(key, (tagCounts.get(key) || 0) + 1);
    }
  }
  renderTagFilters([...tagCounts.entries()].sort((a, b) => b[1] - a[1]).slice(0, 16));
  el.tagsEmpty.hidden = tagCounts.size > 0;

  const priorityCounts = { high: 0, medium: 0, low: 0 };
  for (const entity of state.entities) {
    const meta = parseMeta(entity);
    if (meta.priority in priorityCounts) priorityCounts[meta.priority] += 1;
  }
  renderPriorityFilters(priorityCounts);
}

function renderLinkTypeFilters(counts) {
  el.linktypeFilters.replaceChildren();
  for (const type of LINK_TYPES) {
    const label = document.createElement("label");
    label.className = "check-item";
    const input = document.createElement("input");
    input.type = "checkbox";
    input.checked = state.linkTypes.has(type);
    input.addEventListener("change", () => {
      if (input.checked) state.linkTypes.add(type);
      else state.linkTypes.delete(type);
      render();
    });
    label.appendChild(input);
    label.appendChild(document.createElement("span")).textContent = LINK_LABELS[type];
    const count = document.createElement("span");
    count.className = "count";
    count.textContent = String(counts.get(type) || 0);
    label.appendChild(count);
    el.linktypeFilters.appendChild(label);
  }
}

function renderTagFilters(entries) {
  el.tagFilters.replaceChildren();
  for (const [tag, count] of entries) {
    const chip = document.createElement("button");
    chip.type = "button";
    chip.className = `chip${state.tags.has(tag) ? " chip-active" : ""}`;
    chip.setAttribute("aria-pressed", String(state.tags.has(tag)));
    chip.textContent = `${tag} · ${count}`;
    chip.addEventListener("click", () => {
      if (state.tags.has(tag)) state.tags.delete(tag);
      else state.tags.add(tag);
      render();
      buildFilterOptions();
    });
    el.tagFilters.appendChild(chip);
  }
}

function renderPriorityFilters(counts) {
  el.priorityFilters.replaceChildren();
  for (const priority of ["high", "medium", "low"]) {
    const chip = document.createElement("button");
    chip.type = "button";
    chip.className = `chip chip-priority-${priority}${state.priorities.has(priority) ? " chip-active" : ""}`;
    chip.setAttribute("aria-pressed", String(state.priorities.has(priority)));
    chip.textContent = `${priority} · ${counts[priority]}`;
    chip.addEventListener("click", () => {
      if (state.priorities.has(priority)) state.priorities.delete(priority);
      else state.priorities.add(priority);
      render();
      buildFilterOptions();
    });
    el.priorityFilters.appendChild(chip);
  }
}

function computeVisible() {
  const dateActive = Boolean(state.dateFrom || state.dateTo);
  const fromTs = state.dateFrom ? Date.parse(`${state.dateFrom}T00:00:00`) / 1000 : null;
  const toTs = state.dateTo ? Date.parse(`${state.dateTo}T23:59:59`) / 1000 : null;
  const query = state.search.trim().toLowerCase();

  const visible = [];
  const highlight = new Set();
  let hiddenNoDate = 0;

  for (const entity of state.entities) {
    const meta = parseMeta(entity);
    const tags = Array.isArray(meta.tags) ? meta.tags.map(String) : [];
    if (state.tags.size && !tags.some((tag) => state.tags.has(tag))) continue;
    if (state.priorities.size) {
      const priority = meta.priority || null;
      if (!priority || !state.priorities.has(priority)) continue;
    }
    const createdTs = createdIndex.has(entity.name) ? createdIndex.get(entity.name) : null;
    if (dateActive) {
      if (createdTs == null) {
        hiddenNoDate += 1;
        continue;
      }
      if (fromTs != null && createdTs < fromTs) continue;
      if (toTs != null && createdTs > toTs) continue;
    }
    const node = {
      id: String(entity.id),
      name: entity.name,
      tags,
      priority: meta.priority || null,
      createdTs,
    };
    if (
      query &&
      (entity.name.toLowerCase().includes(query) ||
        tags.some((tag) => tag.toLowerCase().includes(query)))
    ) {
      highlight.add(node.id);
    }
    visible.push(node);
  }

  const visibleIds = new Set(visible.map((node) => node.id));
  const links = state.links
    .filter(
      (link) =>
        state.linkTypes.has(link.type) &&
        visibleIds.has(String(link.source_id)) &&
        visibleIds.has(String(link.target_id)),
    )
    .map((link) => ({ ...link }));

  const degree = new Map();
  for (const link of links) {
    degree.set(String(link.source_id), (degree.get(String(link.source_id)) || 0) + 1);
    degree.set(String(link.target_id), (degree.get(String(link.target_id)) || 0) + 1);
  }
  for (const node of visible) node.degree = degree.get(node.id) || 0;

  return { visible, links, highlight, hiddenNoDate, dateActive };
}

function renderOverlay(visibleCount) {
  const overlay = el.stateOverlay;
  overlay.replaceChildren();
  overlay.hidden = true;

  if (state.loading && !state.entities.length) {
    overlay.hidden = false;
    overlay.innerHTML =
      '<div class="state-card"><div class="spinner" aria-hidden="true"></div><p>Загрузка графа…</p></div>';
    return;
  }
  if (state.error) {
    overlay.hidden = false;
    const card = document.createElement("div");
    card.className = "state-card state-error";
    const title = document.createElement("p");
    title.textContent = "Не удалось получить данные";
    const detail = document.createElement("p");
    detail.className = "hint";
    detail.textContent = state.error;
    const retry = document.createElement("button");
    retry.type = "button";
    retry.className = "btn btn-primary";
    retry.textContent = "Повторить";
    retry.addEventListener("click", () => {
      state.loading = true;
      refresh();
    });
    card.append(title, detail, retry);
    overlay.appendChild(card);
    return;
  }
  if (!state.entities.length) {
    overlay.hidden = false;
    overlay.innerHTML =
      '<div class="state-card"><p>Пока нет сущностей</p>' +
      '<p class="hint">Введите в поле «Намерение» слева: <code>создать грядка</code>, затем <code>создать помидор</code> — ' +
      "и узлы появятся на графе.</p></div>";
    return;
  }
  if (!visibleCount) {
    overlay.hidden = false;
    overlay.innerHTML =
      '<div class="state-card"><p>Ничего не найдено по фильтрам</p>' +
      '<p class="hint">Ослабьте фильтры или нажмите «Сбросить фильтры».</p></div>';
  }
}

function render() {
  const { visible, links, highlight, hiddenNoDate, dateActive } = computeVisible();

  graph.update({
    nodes: visible,
    links,
    highlightIds: highlight,
    selectedId: state.selectedId,
  });

  el.dateHint.hidden = !(dateActive && hiddenNoDate > 0);
  if (!el.dateHint.hidden) {
    el.dateHint.textContent = `Скрыто без известной даты создания: ${hiddenNoDate}`;
  }
  renderOverlay(visible.length);
}

function resetFilters() {
  state.linkTypes = new Set(LINK_TYPES);
  state.tags.clear();
  state.priorities.clear();
  state.dateFrom = "";
  state.dateTo = "";
  state.search = "";
  el.search.value = "";
  el.dateFrom.value = "";
  el.dateTo.value = "";
  buildFilterOptions();
  render();
}

function updateThemeButton() {
  const dark = currentTheme() === "dark";
  el.themeBtn.textContent = dark ? "☀" : "☾";
  el.themeBtn.setAttribute(
    "aria-label",
    dark ? "Включить светлую тему" : "Включить тёмную тему",
  );
  el.themeBtn.title = dark ? "Светлая тема" : "Тёмная тема";
}

function wireEvents() {
  el.search.addEventListener("input", () => {
    state.search = el.search.value;
    render();
  });
  el.search.addEventListener("keydown", (event) => {
    if (event.key === "Enter") {
      event.preventDefault();
      const first = computeVisible();
      if (first.highlight.size) {
        const id = first.visible.find((n) => first.highlight.has(n.id)).id;
        graph.focusEntity(id);
        selectEntity(id);
      }
    } else if (event.key === "Escape") {
      el.search.value = "";
      state.search = "";
      render();
      el.search.blur();
    }
  });

  document.addEventListener("keydown", (event) => {
    if (event.key === "/" && !event.defaultPrevented) {
      const tag = document.activeElement && document.activeElement.tagName;
      if (tag !== "INPUT" && tag !== "TEXTAREA" && tag !== "SELECT") {
        event.preventDefault();
        el.search.focus();
      }
    } else if (event.key === "Escape") {
      if (el.intentForm.contains(document.activeElement)) return;
      selectEntity(null);
    }
  });

  el.refreshBtn.addEventListener("click", () => refresh());
  el.themeBtn.addEventListener("click", () => {
    toggleTheme();
    updateThemeButton();
  });
  document.addEventListener("themechange", updateThemeButton);

  el.zoomIn.addEventListener("click", () => graph.zoomBy(1.3));
  el.zoomOut.addEventListener("click", () => graph.zoomBy(1 / 1.3));
  el.fit.addEventListener("click", () => graph.fit());

  el.dateFrom.addEventListener("change", () => {
    state.dateFrom = el.dateFrom.value;
    render();
  });
  el.dateTo.addEventListener("change", () => {
    state.dateTo = el.dateTo.value;
    render();
  });
  el.resetFilters.addEventListener("click", resetFilters);

  el.intentForm.addEventListener("submit", (event) => {
    event.preventDefault();
    const text = el.intentInput.value.trim();
    if (!text) return;
    el.intentInput.value = "";
    runIntent(text);
  });

  document.addEventListener("visibilitychange", () => {
    if (!document.hidden && !inFlight) refresh();
  });
  window.setInterval(() => {
    if (!document.hidden && !inFlight) refresh();
  }, 10000);
}

function selectEntity(id) {
  state.selectedId = id;
  graph.setSelected(id);
}

function mount() {
  document.getElementById("app").innerHTML = SHELL_HTML;
  for (const id of [
    "search", "refresh-btn", "theme-btn", "linktype-filters", "tag-filters", "tags-empty",
    "priority-filters", "date-from", "date-to", "date-hint", "reset-filters", "intent-form",
    "intent-input", "intent-submit", "intent-feedback", "graph", "zoom-in", "zoom-out", "fit",
    "state-overlay", "conn-dot", "stats-line", "api-line", "toasts",
  ]) {
    el[id.replace(/-([a-z])/g, (_, c) => c.toUpperCase())] = qs(id);
  }

  el.apiLine.textContent = `API: ${API_URL || "same-origin"}`;
  graph = new MindGraph(el.graph, { onSelect: selectEntity });
  updateThemeButton();
  wireEvents();
  watchSystemTheme();
  refresh();
}

mount();
