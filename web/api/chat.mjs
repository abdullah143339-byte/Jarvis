import process from "node:process";

export const config = { runtime: "nodejs" };

const SYSTEM_PROMPT = `You are JARVIS, a personal AI assistant. You are built by Abdullah.

Personality & rules:
- Reply in the same language the user uses: Pakistani Urdu (Roman/Urdu script) or English.
- Address the user respectfully as "ji" or "sir ji".
- Be direct, honest and execution-first. NEVER claim something worked unless you verified it.
- When you use live web search, briefly note that you checked live sources.
- Keep answers concise and useful. Use short bullets/lists when it helps.
- If the user asks to control their computer (files, apps, videos, browser, system): explain it politely that
  PC control runs only through the local desktop JARVIS app, but still give practical steps/answers.`;

const HISTORY_LIMIT = 24;

function toGeminiContents(messages) {
  const out = [];
  const recent = messages.slice(-HISTORY_LIMIT);
  for (const m of recent) {
    if (!/^[US]|user|assistant|model/.test(m.role)) continue;
    const role = m.role === "user" ? "user" : "model";
    out.push({ role, parts: [{ text: String(m.text ?? "") }] });
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
  if (messages.length === 0) {
    return Response.json({ error: "No messages" }, { status: 400 });
  }

  const model = process.env.GEMINI_MODEL || "gemini-2.0-flash";
  const payload = {
    systemInstruction: { parts: [{ text: SYSTEM_PROMPT }] },
    contents: toGeminiContents(messages),
    tools: [{ googleSearch: {} }],
    generationConfig: {
      temperature: 0.7,
      maxOutputTokens: 1024,
    },
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

    return Response.json({ text, promptFeedback: data?.promptFeedback ?? null });
  } catch (err) {
    console.error("chat handler error", err.message);
    return Response.json({ error: "Upstream failure" }, { status: 500 });
  }
}