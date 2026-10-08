import { getStore } from "@netlify/blobs";

// GET  /api/data  -> public. Returns { data, rev, editor } (editor = caller sent the right key)
// PUT  /api/data  -> needs x-edit-key header == EDIT_KEY env var. Body: { rev, data }
const EMPTY = { apps: [], sessions: [], events: [] };
const json = (body, status = 200) =>
  new Response(JSON.stringify(body), { status, headers: { "content-type": "application/json", "cache-control": "no-store" } });

export default async (req) => {
  const store = getStore("tracker");
  const secret = process.env.EDIT_KEY;
  const isEditor = !!secret && req.headers.get("x-edit-key") === secret;
  const saved = (await store.get("state", { type: "json" })) || { rev: 0, data: EMPTY };

  if (req.method === "GET") return json({ ...saved, editor: isEditor });

  if (req.method === "PUT") {
    if (!isEditor) return json({ error: "wrong or missing edit key" }, 401);
    const text = await req.text();
    if (text.length > 2_000_000) return json({ error: "too large" }, 413);
    let body;
    try { body = JSON.parse(text); } catch { return json({ error: "bad json" }, 400); }
    const d = body.data;
    if (!d || !Array.isArray(d.apps) || !Array.isArray(d.sessions) || !Array.isArray(d.events))
      return json({ error: "bad shape" }, 400);
    if (body.rev !== saved.rev) return json({ error: "out of date", ...saved }, 409);
    const goals = d.goals && typeof d.goals === "object" && !Array.isArray(d.goals) ? d.goals : {};
    const next = { rev: saved.rev + 1, data: { apps: d.apps, sessions: d.sessions, events: d.events, goals } };
    await store.setJSON("state", next);
    return json({ ...next, editor: true });
  }
  return json({ error: "method not allowed" }, 405);
};

export const config = { path: "/api/data" };
