// Single-slot remote workbench: GET returns the slot, PUT replaces it.
// Auth: `x-token` header must equal the REMOTE_TOKEN env var.
// Storage: one JSON blob (Vercel Blob). Public blob URLs are unguessable
// (random store host) but not private — don't push anything truly secret.
import { put, list } from "@vercel/blob";

const PATH = "paper-review/slot.json";

async function readSlot() {
  const { blobs } = await list({ prefix: PATH, limit: 1 });
  if (!blobs.length) return null;
  // Cache-bust: blob CDN caches by URL; a unique query forces a fresh read
  // so mobile edits are visible to an immediate local pull.
  const res = await fetch(`${blobs[0].url}?t=${Date.now()}`, { cache: "no-store" });
  if (!res.ok) return null;
  return res.json();
}

export default async function handler(req, res) {
  const token = req.headers["x-token"];
  if (!process.env.REMOTE_TOKEN || token !== process.env.REMOTE_TOKEN) {
    return res.status(401).json({ error: "bad token" });
  }

  if (req.method === "GET") {
    const doc = await readSlot();
    return res.status(200).json(doc || { empty: true });
  }

  if (req.method === "PUT") {
    const body = req.body || {};
    if (typeof body.md !== "string" || !body.md.trim()) {
      return res.status(400).json({ error: "md required" });
    }
    const cur = await readSlot();
    // Mobile saves pass baseRev for optimistic concurrency; local push passes
    // force=true because pushing IS the slot swap.
    if (!body.force && cur && body.baseRev !== cur.rev) {
      return res.status(409).json({ error: "rev conflict", rev: cur.rev });
    }
    const doc = {
      slug: body.slug ?? cur?.slug ?? "unknown",
      title: body.title ?? cur?.title ?? "",
      md: body.md,
      figures: body.figures ?? cur?.figures ?? [],
      rev: (cur?.rev || 0) + 1,
      pushed_at: body.force ? new Date().toISOString() : cur?.pushed_at,
      updated_at: new Date().toISOString(),
    };
    await put(PATH, JSON.stringify(doc), {
      access: "public",
      addRandomSuffix: false,
      contentType: "application/json",
    });
    return res.status(200).json({ ok: true, rev: doc.rev, slug: doc.slug });
  }

  res.setHeader("Allow", "GET, PUT");
  return res.status(405).json({ error: "method not allowed" });
}
