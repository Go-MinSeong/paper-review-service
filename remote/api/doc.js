// Single-slot remote workbench: GET returns the slot, PUT replaces it.
// Auth: `x-token` header must equal the REMOTE_TOKEN env var.
//
// Storage: Vercel Blob. The blob CDN ignores query-string cache busting, so
// overwriting one pathname serves stale reads for minutes. Instead every save
// writes a NEW immutable blob (random suffix) and readers pick the newest via
// list() — read-after-write correct; old revisions are pruned best-effort.
import { put, list, del } from "@vercel/blob";

const PREFIX = "paper-review/slot-";

const revOf = (b) => +(b.pathname.match(/slot-(\d+)/)?.[1] || 0);

async function newestBlob() {
  const { blobs } = await list({ prefix: PREFIX, limit: 100 });
  if (!blobs.length) return null;
  blobs.sort(
    (a, b) => revOf(b) - revOf(a) || new Date(b.uploadedAt) - new Date(a.uploadedAt)
  );
  return blobs;
}

async function readSlot() {
  const blobs = await newestBlob();
  if (!blobs) return null;
  const res = await fetch(blobs[0].url, { cache: "no-store" });
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
      // Summary is read-only on mobile: a save carries no report, so keep the
      // one the push delivered instead of dropping it. Reports built before
      // report.md existed arrive as html.
      report_md: body.report_md ?? cur?.report_md ?? "",
      report_html: body.report_html ?? cur?.report_html ?? "",
      figures: body.figures ?? cur?.figures ?? [],
      rev: (cur?.rev || 0) + 1,
      pushed_at: body.force ? new Date().toISOString() : cur?.pushed_at,
      updated_at: new Date().toISOString(),
    };
    await put(`${PREFIX}${doc.rev}.json`, JSON.stringify(doc), {
      access: "public",
      addRandomSuffix: true, // unique URL → immutable, never a stale CDN hit
      contentType: "application/json",
    });
    // prune older revisions (best effort — a failure here is harmless)
    try {
      const blobs = await newestBlob();
      const stale = (blobs || []).slice(1).map((b) => b.url);
      if (stale.length) await del(stale);
    } catch (e) { /* ignore */ }
    return res.status(200).json({ ok: true, rev: doc.rev, slug: doc.slug });
  }

  res.setHeader("Allow", "GET, PUT");
  return res.status(405).json({ error: "method not allowed" });
}
