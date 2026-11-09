// Клиент REST API Adapt SymbioSystem (vanilla ES module).
//
// Базовый URL настраивается (в порядке приоритета):
//   1. window.KALAW_API_URL (может быть выставлен до загрузки модулей,
//      в т.ч. из query-параметра ?api=... — см. index.html)
//   2. значение по умолчанию http://localhost:8000
// Пустая строка означает same-origin (UI и API на одном порту).

const DEFAULT_API_URL = "http://localhost:8000";

const rawUrl =
  typeof window !== "undefined" && typeof window.KALAW_API_URL === "string"
    ? window.KALAW_API_URL.trim()
    : "";

export const API_URL = rawUrl.replace(/\/+$/, "") || DEFAULT_API_URL;

const JSON_HEADERS = { "Content-Type": "application/json" };

async function request(path, options = {}) {
  let res;
  try {
    res = await fetch(API_URL + path, options);
  } catch (err) {
    throw new Error(
      `Нет связи с API (${API_URL || "same-origin"}). ` +
        "Запустите backend: uvicorn backend.main:app --port 8000",
    );
  }
  if (!res.ok) {
    let detail = `${res.status} ${res.statusText}`;
    try {
      const body = await res.json();
      if (body && body.detail) {
        detail =
          typeof body.detail === "string"
            ? body.detail
            : JSON.stringify(body.detail);
      }
    } catch {
      // Тело ответа не JSON — используем статус
    }
    throw new Error(detail);
  }
  return res.json();
}

// Постраничная выборка (backend отдаёт {items, has_more}, лимит страницы 500).
async function fetchAll(path) {
  const out = [];
  let skip = 0;
  for (;;) {
    const sep = path.includes("?") ? "&" : "?";
    const page = await request(`${path}${sep}skip=${skip}&limit=500`);
    const items = Array.isArray(page) ? page : page.items || [];
    out.push(...items);
    if (Array.isArray(page) || !page.has_more || items.length === 0) break;
    skip += items.length;
    if (skip >= 20000) break; // предохранитель от зацикливания
  }
  return out;
}

export function fetchEntities() {
  return fetchAll("/entities");
}

export function fetchLinks(type = null) {
  return fetchAll(type ? `/links?type=${encodeURIComponent(type)}` : "/links");
}

export function fetchEvents({ eventType = null, entity = null, since = null, limit = 300 } = {}) {
  const params = new URLSearchParams();
  if (eventType) params.set("event_type", eventType);
  if (entity) params.set("entity", entity);
  if (since != null) params.set("since", String(since));
  params.set("limit", String(limit));
  const qs = params.toString();
  return request(`/events${qs ? `?${qs}` : ""}`).then((data) => data.items || []);
}

export function fetchStats() {
  return request("/stats");
}

export function fetchHealth() {
  return request("/health");
}

export function createEntity(name, parentId = null) {
  const payload = { name };
  if (parentId != null) payload.parent_id = parentId;
  return request("/entity", {
    method: "POST",
    headers: JSON_HEADERS,
    body: JSON.stringify(payload),
  });
}

export function createLink(source, target, type) {
  return request("/link", {
    method: "POST",
    headers: JSON_HEADERS,
    body: JSON.stringify({ source, target, type }),
  });
}

export function sendIntent(text, sessionId = null) {
  const payload = { intent: text };
  if (sessionId) payload.session_id = sessionId;
  return request("/intent", {
    method: "POST",
    headers: JSON_HEADERS,
    body: JSON.stringify(payload),
  });
}

// meta — JSON-строка в поле Entity.meta; теги и приоритет живут внутри.
export function parseMeta(entity) {
  try {
    const parsed = JSON.parse(entity.meta || "{}");
    return parsed && typeof parsed === "object" && !Array.isArray(parsed) ? parsed : {};
  } catch {
    return {};
  }
}

export const LINK_TYPES = ["contains", "depends", "relates", "blocks", "triggers"];

export const LINK_LABELS = {
  contains: "содержит",
  depends: "зависит от",
  relates: "связано",
  blocks: "блокирует",
  triggers: "запускает",
};

// Человекочитаемое описание результата intent-движка (null → трактовать как ошибку).
export function describeIntentResult(result) {
  if (!result || typeof result !== "object") return "Готово";
  if (result.error) return null;
  if (result.question) return result.question;
  if (result.created && result.created.name) {
    return `Создана сущность «${result.created.name}»`;
  }
  if (result.created && result.created.source) {
    return `Связь создана: ${result.created.source} → ${result.created.target}`;
  }
  if (result.exists && result.exists.name) {
    return `«${result.exists.name}» уже существует`;
  }
  if (result.deleted) return `Удалено: «${result.deleted}»`;
  if (result.connections) return `Найдено связей: ${result.connections.length}`;
  if (result.tagged) return "Тег добавлен";
  return "Готово";
}
