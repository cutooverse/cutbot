"""Instagram and YouTube copy for the videos, written by a model on NVIDIA's API with captions.md as its rules.

Settings (Railway: the service's Variables), never in this code:
  NVIDIA_API_KEY   the key from build.nvidia.com; without it the bot makes no captions
  CAPTION_MODEL    optional: another model on the same API (default z-ai/glm-5.3-flash)
"""
import html
import json
import os
import re
import urllib.error
import urllib.request
from pathlib import Path

KEY = os.environ.get("NVIDIA_API_KEY", "").strip()
MODEL = os.environ.get("CAPTION_MODEL", "z-ai/glm-5.3-flash").strip()
BASE = os.environ.get("CAPTION_API", "https://integrate.api.nvidia.com/v1").rstrip("/")
RULES = Path(__file__).with_name("captions.md").read_text(encoding="utf-8")

# "another tone" walks through these: the name shown in Telegram, and what the model is told
TONES = [("پرانرژی", "high energy, bold and punchy"),
         ("آرام و ASMR", "calm, soft and soothing, ASMR first"),
         ("بامزه", "playful and funny"),
         ("کنجکاوی", "mysterious, built on curiosity: make them need to see the end"),
         ("چالشی", "a challenge thrown at the viewer"),
         ("اعتراف", "a casual confession, as if telling a friend")]
FIELDS = [("instagram", "📸 Instagram Caption"), ("title", "🎬 YouTube Title"),
          ("description", "📝 YouTube Description"), ("tags", "🏷️ YouTube Tags")]


def ask(messages, effort=True):
    """The model's answer, without its thinking."""
    body = {"model": MODEL, "messages": messages, "temperature": 0.9, "top_p": 0.95, "max_tokens": 2048, "stream": False}
    if effort:
        body["reasoning_effort"] = "low"        # the API's default thinks at length: slow, and no better for copy
    req = urllib.request.Request(f"{BASE}/chat/completions", json.dumps(body).encode(),
                                 {"Authorization": f"Bearer {KEY}", "Content-Type": "application/json", "Accept": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=180) as r:
            msg = json.load(r)["choices"][0]["message"]
    except urllib.error.HTTPError as e:
        detail = e.read()[:300].decode("utf-8", "replace")
        if effort and e.code in (400, 422):     # a model that does not take reasoning_effort
            return ask(messages, effort=False)
        raise RuntimeError(f"caption API {e.code}: {detail}")
    return re.sub(r"<think>.*?</think>", "", msg.get("content") or "", flags=re.S).strip()


def write(subject, facts="", tone=0, avoid=()):
    """{instagram, title, description, tags} for `subject`, or {raw} when the answer is not the JSON asked for."""
    prompt = [f"Subject: {subject}"]
    if facts:
        prompt.append("What the video shows (facts; use these and invent nothing else):\n" + facts)
    prompt.append(f"Tone for this version: {TONES[tone % len(TONES)][1]}.")
    if avoid:
        prompt.append("Earlier versions opened like this; do not reuse these hooks, titles or structures:\n" + "\n".join(f"- {a}" for a in avoid[-8:]))
    prompt.append('Reply with only a JSON object, no code fences and nothing around it: '
                  '{"instagram": "...", "title": "...", "description": "...", "tags": "..."}')
    text = ask([{"role": "system", "content": RULES}, {"role": "user", "content": "\n\n".join(prompt)}])
    m = re.search(r"\{.*\}", text, re.S)
    try:
        data = json.loads(m.group(0))
        out = {k: str(data.get(k) or "").strip() for k, _ in FIELDS}
        if out["instagram"] or out["title"]:
            return out
    except (AttributeError, ValueError):
        pass
    return {"raw": text}


def openers(c):
    """What a later version must not repeat: the caption's first line and the title."""
    return [x for x in ((c.get("instagram") or c.get("raw") or "").strip().split("\n")[0], c.get("title", "")) if x]


def as_html(c, subject, tone=0, done=False):
    """The message: each part in a block that copies with one tap."""
    esc = lambda s: html.escape(s, quote=False)
    head = f"{'✅' if done else '📝'} <b>{esc(subject)}</b> · لحن: {TONES[tone % len(TONES)][0]}"
    if "raw" in c:
        body = [f"<pre>{esc(c['raw'][:3600])}</pre>"]
    else:
        body = [f"<b>{label}</b>\n<pre>{esc(c[k])}</pre>" for k, label in FIELDS if c.get(k)]
    text = "\n\n".join([head, *body])
    return text if len(text) <= 4000 else text[:3990] + "…</pre>"
