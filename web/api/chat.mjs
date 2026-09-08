import process from "node:process";

export const config = { runtime: "nodejs" };

const SYSTEM_PROMPT = `You are JARVIS, a personal AI assistant. You are built by Abdullah.

Personality & rules:
- Reply in the same language the user uses: Pakistani Urdu (Roman/Urdu script) or English.
- Address the user respectfully as "ji" or "sir ji".
- Be direct, honest and execution-first. NEVER claim something worked unless you verified it.
- When LIVE_WEB_RESULTS are provided, base your answer on them and briefly say you checked live sources.
- Keep answers concise and useful. Use short bullets/lists when it helps.
- If the user asks to control their computer (files, apps, videos, browser, system): explain politely that
  PC control runs only through the local desktop JARVIS app, but still give practical steps/answers.`;

const HISTORY_LIMIT = 24;
const DDG_URL = "https://html.duckduckgo.com/html/";
const DDG_UA =
  "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36";

function stripTags(s) {
  return String(s ?? "")
    .replace(/<[^>]*>/g, " ")
    .replace(/&amp;/g, "&")
    .replace(/&quot;/g, '"')
    .replace(/&lt;/g, "<")
    .replace(/&gt;/g, ">")
    .replace(/&#x27;/g, "'")
    .replace(/\s+/g, " ")
    .trim();
}

async function ddgSearch(query) {
  try {
    const resp = await fetch(`${DDG_URL}?q=${encodeURIComponent(query)}`, {
      headers: { "User-Agent": DDG_UA, "Accept-Language": "en-US,en;q=0.8" },
      signal: AbortSignal.timeout(6000),
    });
    if (!resp.ok) return [];
    const html = await resp.text();
    const blocks = html.split('<div class="result').slice(1);
    const hits = [];
    for (const block of blocks) {
      const m = block.match(/result__a[^>]*href="([^"]+)"[^>]*>(.*?)<\/a>/s);
      const s = block.match(/result__snippet[^>]*>(.*?)<\/a>/s);
      if (!m) continue;
      const url = m[1].replace(/^\/\/duckduckgo\.com\/l\/\?uddg=/, "");
      let u = decodeURIComponent(url.split("&rut=")[0]);
      if (!/^https?:/.test(u)) u = m[1];
      hits.push({
        title: stripTags(m[2]),
        url: u,
        snippet: s ? stripTags(s[1]) : "",
      });
      if (hits.length >= 4) break;
    }
    return hits;
  } catch {
    return [];
  }
}

function toGeminiContents(messages, liveContext) {
  const recent = messages.slice(-HISTORY_LIMIT);
  const out = [];
  for (let i = 0; i < recent.length; i++) {
    const m = recent[i];
    const role = m.role === "user" ? "user" : "model";
    let text = String(m.text ?? "");
    if (i === recent.length - 1 && liveContext) {
      text += `\n\nLIVE_WEB_RESULTS:\n${liveContext}`;
    }
    if (!text.trim()) continue;
    out.push({ role, parts: [{ text }] });
  }
  return out;
}

export default async function handler(req) {
  if (req.method === "OPTIONS") {
    return new Response("ok", { status: 204 });
  }
  if (req.method !== "POST") {
    return Response.json({ error: "Method not allowed" }, { status: 405 });
  }

  const key = process.env.GEMINI_API_KEY;
  if (!key) {
    return Response.json(
      { error: "Server not configured (GEMINI_API_KEY missing)." },
      { status: 500 }
    );
  }

  let body;
  try {
    body = await req.json();
  } catch {
    return Response.json({ error: "Bad JSON body" }, { status: 400 });
  }

  const messages = Array.isArray(body.messages) ? body.messages : [];
  const live = body.live !== false;
  if (messages.length === 0) {
    return Response.json({ error: "No messages" }, { status: 400 });
  }

  const lastUserText = [...messages]
    .reverse()
    .find((m) => m.role === "user");
  const query = lastUserText ? String(lastUserText.text ?? "") : "";

  let liveContext = "";
  if (live && query) {
    const hits = await ddgSearch(query);
    if (hits.length) {
      liveContext = hits
        .map((h) => `- ${h.title} — ${h.url}\n  ${h.snippet}`)
        .join("\n");
    }
  }

  const model = process.env.GEMINI_MODEL || "gemini-3.6-flash";
  const payload = {
    systemInstruction: { parts: [{ text: SYSTEM_PROMPT }] },
    contents: toGeminiContents(messages, liveContext),
    generationConfig: { temperature: 0.7, maxOutputTokens: 1024 },
  };

  try {
    const resp = await fetch(
      `https://generativelanguage.googleapis.com/v1beta/models/${model}:generateContent?key=${encodeURIComponent(key)}`,
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      }
    );

    if (resp.status >= 400) {
      const errText = await resp.text();
      console.error("Gemini error", resp.status, errText.slice(0, 300));
      return Response.json(
        { error: "Gemini API error", detail: errText.slice(0, 300) },
        { status: 502 }
      );
    }

    const data = await resp.json();
    const text =
      data?.candidates?.[0]?.content?.parts
        ?.map((p) => p.text ?? "")
        .join("")
        .trim() || "";

    return Response.json({ text, live: !!liveContext });
  } catch (err) {
    console.error("chat handler error", err.message);
    return Response.json({ error: "Upstream failure" }, { status: 500 });
  }
}