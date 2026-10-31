const API = "http://localhost:8000";

export async function getEntities(skip = 0, limit = 100) {
  const r = await fetch(API + `/entities?skip=${skip}&limit=${limit}`);
  const data = await r.json();
  return data.items || data; // Поддержка старого и нового формата
}

export async function getLinks(skip = 0, limit = 100) {
  const r = await fetch(API + `/links?skip=${skip}&limit=${limit}`);
  const data = await r.json();
  return data.items || data; // Поддержка старого и нового формата
}

export async function sendIntent(intent) {
  const r = await fetch(API + "/intent", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ intent }),
  });
  return await r.json();
}
