import { useEffect, useState } from "react";
import { kiln } from "./api";

type Health = { status: string; model_loaded: boolean; backend: string } | null;
type Metrics = { avg_ttft: number; avg_tokens_per_second: number; requests: number } | null;

export function App() {
  const [health, setHealth] = useState<Health>(null);
  const [metrics, setMetrics] = useState<Metrics>(null);
  const [models, setModels] = useState<string[]>([]);
  const [input, setInput] = useState("");
  const [reply, setReply] = useState("");
  const [busy, setBusy] = useState(false);

  async function refresh() {
    try {
      setHealth(await kiln.health());
      setMetrics(await kiln.metrics());
      setModels((await kiln.models()).data.map((m: any) => m.id));
    } catch {
      setHealth(null);
    }
  }

  useEffect(() => {
    refresh();
    const id = setInterval(refresh, 2000);
    return () => clearInterval(id);
  }, []);

  async function send() {
    if (!input.trim() || busy) return;
    setBusy(true);
    setReply("");
    try {
      const model = models[0] ?? "kiln";
      const res = await kiln.chat(model, [{ role: "user", content: input }]);
      setReply(res.choices?.[0]?.message?.content ?? "(no response)");
      setInput("");
    } catch (e) {
      setReply(`error: ${(e as Error).message}`);
    } finally {
      setBusy(false);
      refresh();
    }
  }

  return (
    <main>
      <header>
        <h1>Kiln</h1>
        <span className={`dot ${health?.status === "ok" ? "ok" : "down"}`} />
        <span className="muted">{health ? health.backend || health.status : "offline"}</span>
      </header>

      <section className="cards">
        <div className="card">
          <h3>Status</h3>
          <p>model loaded: <b>{health ? String(health.model_loaded) : "—"}</b></p>
        </div>
        <div className="card">
          <h3>TTFT (avg)</h3>
          <p>{(metrics?.avg_ttft ?? 0).toFixed(2)} s</p>
        </div>
        <div className="card">
          <h3>Throughput</h3>
          <p>{(metrics?.avg_tokens_per_second ?? 0).toFixed(1)} tok/s</p>
        </div>
        <div className="card">
          <h3>Requests</h3>
          <p>{metrics?.requests ?? 0}</p>
        </div>
      </section>

      <section className="chat">
        <div className="reply">{reply || <span className="muted">ask the loaded model…</span>}</div>
        <div className="input-row">
          <input
            value={input}
            placeholder={models[0] ? `chat with ${models[0]}` : "load a model first"}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && send()}
            disabled={busy}
          />
          <button onClick={send} disabled={busy || !models[0]}>
            {busy ? "…" : "Send"}
          </button>
        </div>
      </section>
    </main>
  );
}
