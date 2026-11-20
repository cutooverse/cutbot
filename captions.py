"""Instagram and YouTube copy for the videos, written by a model on NVIDIA's API with captions.md as its rules.

Settings (Railway: the service's Variables), never in this code:
  NVIDIA_API_KEY   the key from build.nvidia.com; without it the bot makes no captions
  CAPTION_MODELS   optional: the models to try, in order, comma-separated
                   (default nvidia/nemotron-3-ultra-550b-a55b, then z-ai/glm-5.3-flash)
"""
import html
import json
import os
import random
import re
import threading
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

# every caption draws its tone, its opening, its call to comment, its emoji level and its title's shape at random,
# never the ones the last few captions used: the name shown in Telegram, and what the model is told
TONES = [("پرانرژی", "high energy, bold and punchy"),
         ("آرام و ASMR", "calm, soft and soothing, ASMR first"),
         ("بامزه", "playful and funny"),
         ("کنجکاوی", "mysterious, built on curiosity: make them need to see the end"),
         ("چالشی", "a challenge thrown at the viewer"),
         ("اعتراف", "a casual confession, as if telling a friend"),
         ("سینمایی", "dramatic and cinematic, like a movie trailer"),
         ("مینیمال", "minimal: very few words, every one counts"),
         ("POV", "written as a POV that puts the viewer right in the scene"),
         ("رقابتی", "a friendly contest: the viewer guesses, votes or picks a side")]
OPENINGS = ["a direct question to the viewer", "a bold claim", "a one-word reaction, then one short line", "a 'POV:' line",
            "a 'Guess…' tease", "a number or a countdown", "a playful confession", "a dare", "a 'This is your sign to…' line",
            "an unpopular opinion", "a quiet lowercase ASMR whisper", "a one-sentence micro story", "a 'Nobody talks about…' line",
            "a 'Wait for it…' line", "a short sound word (like CRUNCH or SNAP) on its own line"]
KEYWORDS = ["ASMR", "MORE", "CRUNCH", "SLICE", "🔪", "the fruit's own emoji", "a number from 1 to 10", "YES or NO",
            "PART 2", "AGAIN", "their favourite fruit", "SATISFYING"]
EMOJIS = ["two emojis at most", "a moderate number of emojis", "an emoji only at the end of some lines", "no emojis in the first line"]
TITLES = ["a question", "a statement with a number in it", "a POV", "'I tried…' or 'We tried…'", "an exclamation",
          "a 'vs' comparison when the video has more than one count", "a 'This is what happens when…'", "a short 'Watch…' command"]
HISTORY = Path(os.environ.get("CAPTION_HISTORY", "/tmp/caption_history.json"))   # what recent captions used (a restart forgets it)
_lock = threading.Lock()
try:
    _hist = json.loads(HISTORY.read_text(encoding="utf-8"))
except (OSError, ValueError):
    _hist = {}


def _fresh(kind, items, keep):
    """An index into `items` that the last `keep` captions did not use."""
    recent = _hist.get(kind, [])[-keep:]
    left = [i for i in range(len(items)) if i not in recent] or list(range(len(items)))
    return random.choice(left)


def _remember(kind, value, keep=40):
    _hist[kind] = (_hist.get(kind, []) + (value if isinstance(value, list) else [value]))[-keep:]


def other_tone(tone):
    """For "another tone": a tone that is neither this one nor one of the last few."""
    with _lock:
        recent = set(_hist.get("tones", [])[-3:]) | {tone}
    return random.choice([i for i in range(len(TONES)) if i not in recent] or [i for i in range(len(TONES)) if i != tone])
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
    body = {"model": model, "messages": messages, "temperature": 1.0, "top_p": 0.95, "max_tokens": 2048, "stream": True}
    if short:                                   # the extras a model may refuse: a fresh seed, and short thinking
        body.update(next((v for k, v in SHORT.items() if k in model.lower()), {}), seed=random.randrange(1 << 30))
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


def write(subject, facts="", tone=None, avoid=()):
    """{instagram, title, description, tags, tone} for `subject` (or {raw, tone} when the answer is not the JSON asked
    for). The tone is drawn at random when not given; the opening, the comment keyword, the emojis and the title's
    shape always are, and none repeats what the last captions used."""
    with _lock:
        tone = _fresh("tones", TONES, 3) if tone is None else tone
        opening, keyword = _fresh("openings", OPENINGS, 6), _fresh("keywords", KEYWORDS, 4)
        emoji, shape = _fresh("emojis", EMOJIS, 1), _fresh("titles", TITLES, 3)
        recent = list(avoid) + [a for a in _hist.get("openers", [])[-12:] if a not in avoid]
    prompt = [f"Subject: {subject}"]
    if facts:
        prompt.append("What the video shows (facts; use these and invent nothing else):\n" + facts)
    prompt.append(f"Tone for this version: {TONES[tone][1]}.\n"
                  f"Open the Instagram caption with {OPENINGS[opening]}. Ask people to comment {KEYWORDS[keyword]}. "
                  f"Use {EMOJIS[emoji]}. Shape the YouTube title as {TITLES[shape]}. "
                  "Pick fresh words: no phrase from the examples in your rules, and vary the description and tags too.")
    if recent:
        prompt.append("Earlier captions opened like this; do not reuse these hooks, titles, words or structures:\n"
                      + "\n".join(f"- {a}" for a in recent[-16:]))
    prompt.append('Reply with only a JSON object, no code fences and nothing around it: '
                  '{"instagram": "...", "title": "...", "description": "...", "tags": "..."}')
    text, model = ask([{"role": "system", "content": RULES}, {"role": "user", "content": "\n\n".join(prompt)}])
    m = re.search(r"\{.*\}", text, re.S)
    out = {"raw": text}
    try:
        data = json.loads(m.group(0))
        got = {k: str(data.get(k) or "").strip() for k, _ in FIELDS}
        if got["instagram"] or got["title"]:
            out = got
    except (AttributeError, ValueError):
        pass
    out.update(model=model, tone=tone)
    with _lock:                                 # what the next captions must not repeat
        _remember("tones", tone); _remember("openings", opening); _remember("keywords", keyword)
        _remember("emojis", emoji); _remember("titles", shape); _remember("openers", openers(out))
        try:
            HISTORY.write_text(json.dumps(_hist), encoding="utf-8")
        except OSError:
            pass
    return out


def openers(c):
    """What a later version must not repeat: the caption's first line and the title."""
    return [x for x in ((c.get("instagram") or c.get("raw") or "").strip().split("\n")[0], c.get("title", "")) if x]


def as_html(c, subject, done=False):
    """The message: each part in a block that copies with one tap."""
    esc = lambda s: html.escape(s, quote=False)
    head = f"{'✅' if done else '📝'} <b>{esc(subject)}</b> · لحن: {TONES[c.get('tone', 0) % len(TONES)][0]}"
    if c.get("model"):
        head += f" · {esc(c['model'].split('/')[-1])}"
    if "raw" in c:
        body = [f"<pre>{esc(c['raw'][:3600])}</pre>"]
    else:
        body = [f"<b>{label}</b>\n<pre>{esc(c[k])}</pre>" for k, label in FIELDS if c.get(k)]
    text = "\n\n".join([head, *body])
    return text if len(text) <= 4000 else text[:3990] + "…</pre>"
