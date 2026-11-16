"""Instagram and YouTube copy for the videos, written by a model on NVIDIA's API with captions.md as its rules.

Settings (Railway: the service's Variables), never in this code:
  NVIDIA_API_KEY   the key from build.nvidia.com; without it the bot makes no captions
  CAPTION_MODELS   optional: the models to try, in order, comma-separated
                   (default nvidia/nemotron-3-ultra-550b-a55b, then z-ai/glm-5.3-flash)
"""
import html
import json
import os
import re
import time
import urllib.error
import urllib.request
from pathlib import Path

KEY = os.environ.get("NVIDIA_API_KEY", "").strip()
MODELS = [m.strip() for m in os.environ.get("CAPTION_MODELS", os.environ.get("CAPTION_MODEL", "")
                                            or "nvidia/nemotron-3-ultra-550b-a55b,z-ai/glm-5.3-flash").split(",") if m.strip()]
WAIT = float(os.environ.get("CAPTION_WAIT", 90))        # s for a model's first word (and between words) before the next model
TOTAL = float(os.environ.get("CAPTION_TOTAL", 240))     # s for a whole answer
# how each model is told to keep its thinking short (a model that does not take it is asked again without)
SHORT = {"glm": {"reasoning_effort": "low"}, "nemotron": {"chat_template_kwargs": {"enable_thinking": False}}}
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


def known_ids():
    """The model ids the API has, by the name its web page uses (dots in a version become dashes)."""
    req = urllib.request.Request(f"{BASE}/models", headers={"Authorization": f"Bearer {KEY}", "Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=30) as r:
        ids = [m["id"] for m in json.load(r).get("data", [])]
    return {re.sub(r"[^a-z0-9/]+", "-", i.lower()): i for i in ids}


def stream(model, messages, short=True):
    """One model's answer, read as it is written: a model that says nothing for WAIT seconds is given up."""
    body = {"model": model, "messages": messages, "temperature": 0.9, "top_p": 0.95, "max_tokens": 2048, "stream": True}
    if short:
        body.update(next((v for k, v in SHORT.items() if k in model.lower()), {}))
    req = urllib.request.Request(f"{BASE}/chat/completions", json.dumps(body).encode(),
                                 {"Authorization": f"Bearer {KEY}", "Content-Type": "application/json", "Accept": "text/event-stream"})
    try:
        r = urllib.request.urlopen(req, timeout=WAIT)
    except urllib.error.HTTPError as e:
        detail = e.read()[:300].decode("utf-8", "replace")
        if short and e.code in (400, 422):      # it does not take the setting for short thinking
            return stream(model, messages, short=False)
        raise RuntimeError(f"{e.code}: {detail}")
    text, start = [], time.time()
    with r:
        for line in r:                          # each word comes as "data: {...}"; thinking keeps the line alive too
            line = line.decode("utf-8", "replace").strip()
            if not line.startswith("data:"):
                continue
            data = line[5:].strip()
            if data == "[DONE]":
                break
            try:
                delta = json.loads(data)["choices"][0].get("delta") or {}
            except (ValueError, KeyError, IndexError):
                continue
            text.append(delta.get("content") or "")
            if time.time() - start > TOTAL:
                raise RuntimeError(f"no full answer in {TOTAL:.0f} s")
    out = re.sub(r"<think>.*?</think>", "", "".join(text), flags=re.S).strip()
    if not out:
        raise RuntimeError("an empty answer")
    return out


def ask(messages):
    """The first model in MODELS that answers; the model's name with it."""
    errors = []
    for model in MODELS:
        try:
            return stream(model, messages), model
        except urllib.error.HTTPError:
            raise
        except RuntimeError as e:
            if str(e).startswith("404"):          # not this name: look it up in the API's list
                try:
                    real = known_ids().get(re.sub(r"[^a-z0-9/]+", "-", model.lower()))
                    if real and real != model:
                        return stream(real, messages), real
                except Exception as e2:         # noqa: BLE001
                    e = e2
            errors.append(f"{model.split('/')[-1]}: {str(e)[:150]}")
        except Exception as e:                  # noqa: BLE001  (a timeout, a dropped connection)
            errors.append(f"{model.split('/')[-1]}: {str(e)[:150] or type(e).__name__}")
    raise RuntimeError(" | ".join(errors))


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
    text, model = ask([{"role": "system", "content": RULES}, {"role": "user", "content": "\n\n".join(prompt)}])
    m = re.search(r"\{.*\}", text, re.S)
    try:
        data = json.loads(m.group(0))
        out = {k: str(data.get(k) or "").strip() for k, _ in FIELDS}
        if out["instagram"] or out["title"]:
            return dict(out, model=model)
    except (AttributeError, ValueError):
        pass
    return {"raw": text, "model": model}


def openers(c):
    """What a later version must not repeat: the caption's first line and the title."""
    return [x for x in ((c.get("instagram") or c.get("raw") or "").strip().split("\n")[0], c.get("title", "")) if x]


def as_html(c, subject, tone=0, done=False):
    """The message: each part in a block that copies with one tap."""
    esc = lambda s: html.escape(s, quote=False)
    head = f"{'✅' if done else '📝'} <b>{esc(subject)}</b> · لحن: {TONES[tone % len(TONES)][0]}"
    if c.get("model"):
        head += f" · {esc(c['model'].split('/')[-1])}"
    if "raw" in c:
        body = [f"<pre>{esc(c['raw'][:3600])}</pre>"]
    else:
        body = [f"<b>{label}</b>\n<pre>{esc(c[k])}</pre>" for k, label in FIELDS if c.get(k)]
    text = "\n\n".join([head, *body])
    return text if len(text) <= 4000 else text[:3990] + "…</pre>"
