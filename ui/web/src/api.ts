// Minimal client for the Kiln gateway (`kiln serve`).
// In dev, Vite proxies /v1 and /health to the running server (see vite.config.ts).
// In the Tauri build, API_URL can be overridden to point at the served API.

export const API_URL = (import.meta.env.VITE_KILN_API ?? "").replace(/\/$/, "");

async function get(path: string): Promise<any> {
  const res = await fetch(`${API_URL}${path}`);
  if (!res.ok) throw new Error(`${path} → ${res.status}`);
  return res.json();
}

async function post(path: string, body: any): Promise<any> {
  const res = await fetch(`${API_URL}${path}`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!res.ok) throw new Error(`${path} → ${res.status}`);
  return res.json();
}

export const kiln = {
  health: () => get("/health"),
  models: () => get("/v1/models"),
  metrics: () => get("/v1/metrics"),
  load: (model_path: string, backend = "") =>
    post("/v1/load", { model_path, backend }),
  chat: (model: string, messages: { role: string; content: string }[]) =>
    post("/v1/chat/completions", { model, messages, temperature: 0.7, max_tokens: 256 }),
};
