"""Cut Count video bot: send it a line like `lemon burst 10,20,30` on Telegram; it records that
video of the game in a headless Chrome and sends it back.

Settings (on Railway: the service's Variables), never in this code:
  TG_TOKEN    the bot's token from @BotFather
  OWNER_ID    who may use it: your Telegram user id, or several, comma-separated. Left empty, the bot
              only answers each message with the sender's id, so you can find yours.
  GAME_REPO   the game's public GitHub repository: owner/name or its address

The game is fetched again before every video, so a push to the game shows up in the next one.
"""
import json
import os
import queue
import re
import shutil
import subprocess
import sys
import threading
import time
import traceback
import urllib.error
import urllib.parse
import urllib.request
import uuid
from pathlib import Path

TOKEN = os.environ.get("TG_TOKEN", "").strip()
OWNERS = {s.strip() for s in os.environ.get("OWNER_ID", "").split(",") if s.strip()}
REPO = os.environ.get("GAME_REPO", "").strip().removesuffix("/").removesuffix(".git")
API = os.environ.get("TG_API", "https://api.telegram.org").rstrip("/")
HERE = Path(__file__).resolve().parent
GAME = Path(os.environ.get("GAME_DIR", "/tmp/game"))
VIDEOS = Path(os.environ.get("VIDEO_DIR", "/tmp/videos"))
PORT = int(os.environ.get("REC_PORT", 8770))
TG_LIMIT = 49 * 1024 * 1024                     # a bot may send files up to 50 MB
CHROME = ["--disable-dev-shm-usage", "--ignore-gpu-blocklist", "--use-angle=swiftshader", "--enable-unsafe-swiftshader"]


def log(*a):
    print(time.strftime("%H:%M:%S"), *a, flush=True)


# --- Telegram ------------------------------------------------------------------------------------

def tg(method, **params):
    data = {k: json.dumps(v) if isinstance(v, (dict, list, bool)) else str(v) for k, v in params.items() if v is not None}
    try:
        with urllib.request.urlopen(f"{API}/bot{TOKEN}/{method}", urllib.parse.urlencode(data).encode(), timeout=70) as r:
            return json.load(r).get("result")
    except urllib.error.HTTPError as e:
        log(method, e.code, e.read()[:300])
    except OSError as e:
        log(method, e)
    return None


def tg_file(method, field, path, **params):
    b = uuid.uuid4().hex
    parts = [f'--{b}\r\nContent-Disposition: form-data; name="{k}"\r\n\r\n{json.dumps(v) if isinstance(v, (bool, dict)) else v}\r\n'.encode()
             for k, v in params.items() if v is not None]
    parts.append(f'--{b}\r\nContent-Disposition: form-data; name="{field}"; filename="{path.name}"\r\nContent-Type: video/mp4\r\n\r\n'.encode())
    body = b"".join(parts) + path.read_bytes() + f"\r\n--{b}--\r\n".encode()
    req = urllib.request.Request(f"{API}/bot{TOKEN}/{method}", body, {"Content-Type": f"multipart/form-data; boundary={b}"})
    try:
        with urllib.request.urlopen(req, timeout=600) as r:
            return json.load(r).get("result")
    except urllib.error.HTTPError as e:
        raise RuntimeError(f"Telegram refused the video: {e.code} {e.read()[:300]!r}")


def say(chat, text, reply_to=None):
    return tg("sendMessage", chat_id=chat, text=text, reply_to_message_id=reply_to, disable_web_page_preview=True)


# --- the game and its looks ----------------------------------------------------------------------

def git(*a):
    return subprocess.run(["git", *a], capture_output=True, text=True)


def get_game():
    """The game's latest version, with the recorder put in it."""
    if (GAME / ".git").exists():                # the latest, even after a force push
        r = git("-C", str(GAME), "fetch", "--depth", "1", "-q", "origin")
        r = r if r.returncode else git("-C", str(GAME), "reset", "--hard", "-q", "FETCH_HEAD")
    else:
        url = REPO if REPO.startswith("http") else f"https://github.com/{REPO}"
        r = git("clone", "--depth", "1", "-q", url + ".git", str(GAME))
    if r.returncode:
        raise RuntimeError("could not get the game: " + r.stderr.strip()[-300:])
    (GAME / "_rec").mkdir(exist_ok=True)
    for f in (HERE / "recorder").iterdir():
        shutil.copy(f, GAME / "_rec" / f.name)
    return git("-C", str(GAME), "log", "-1", "--format=%h %s").stdout.strip()


server = None


def ensure_server():
    global server
    if server and server.poll() is None:
        return
    env = dict(os.environ, REC_OUT=str(VIDEOS), REC_WORK=str(VIDEOS.parent / "rec_work"), REC_THREADS="2")
    env.pop("TG_TOKEN", None)
    server = subprocess.Popen([sys.executable, str(GAME / "_rec" / "rec_server.py"), str(PORT)], env=env)
    for _ in range(50):
        try:
            urllib.request.urlopen(f"http://127.0.0.1:{PORT}/index.html", timeout=1).close()
            return
        except OSError:
            time.sleep(0.2)
    raise RuntimeError("the recorder's server did not start")


FIXED = {                                       # looks that are not lists in the game's code
    "style": {"burst": ["برست", "بریست", "انفجاری"], "dice": ["دایس", "مکعبی"], "free": ["آزاد"]},
    "camera": {"front": ["روبرو", "جلو"], "top": ["بالا"], "close": ["نزدیک"]},
    "speed": {"slow": ["آهسته", "کند"], "normal": ["معمولی"], "fast": ["تند", "سریع"]},
    "material": {"real": ["واقعی"], "glass": ["شیشه‌ای"]},
    "size": {"s": ["small", "کوچک"], "m": ["medium", "متوسط"], "l": ["large", "big", "بزرگ"]},
    "quality": {"full": ["کامل"], "lite": ["سبک"]},
    "notes": {"piano": ["پیانو"], "organ": ["ارگ"], "musicbox": ["جعبه‌موسیقی"], "marimba": ["ماریمبا"], "glass": [], "off": ["nonotes", "بی‌نت"]},
    "cutsound": {"auto": [], "knife": [], "glass": []},
    "edit": {"normal": [], "loop": ["seamless", "لوپ"]},
    "format": {"normal": [], "vs": ["1vsn", "وی‌اس"]},
}
ORDER = ["fruit", "style", "camera", "speed", "knife", "backdrop", "board", "theme", "material", "size", "quality", "notes", "cutsound", "edit", "format"]
DEFAULTS = dict(fruit="orange", style="burst", camera="front", speed="normal", knife="chef", backdrop="teal", board="walnut",
                material="real", size="m", quality="lite", video="720", notes="piano", cutsound="auto", edit="normal", format="normal")  # fits 1 GB of memory
CUTS = [10, 20, 30]
MAX_CUT, MAX_PARTS = 500, 6                     # cuts in one segment (tested up to 500), segments in a video
options = {"fruit": {"orange": {"en": "Orange", "fa": "پرتقال"}}, "backdrop": {}, "board": {}, "knife": {}, "theme": {}}
words = {}                                      # a word as typed -> (look, id)
bycat = {}                                      # look -> {word: id}, for board=glass
FILLER = {"cut", "cuts", "برش", "تا", "و", "با"}
ready = threading.Event()                       # set once the game's looks are known


def norm(s):
    s = s.lower().replace("ي", "ی").replace("ك", "ک").replace("‌", "")
    return s.translate(str.maketrans("۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩", "01234567890123456789"))


def learn(opts):
    """The game's own lists of looks (from _rec/options.html), and every word that names one."""
    global options, words
    options = opts
    w = {}
    bycat.clear()
    for cat in reversed(ORDER):                 # the earlier look wins a word two of them share
        ids = FIXED.get(cat) or {i: [v.get("en", ""), v.get("fa", "")] if "en" in v else [v.get("name", {}).get("en", ""), v.get("name", {}).get("fa", "")]
                                  for i, v in options.get(cat, {}).items()}
        for i, names in ids.items():
            for name in [i, *names]:
                for word in {norm(name), norm(name).replace(" ", "")} - {""}:
                    w[word] = (cat, i)
                    bycat.setdefault(cat, {})[word] = i
    words = w


def parse(text, base=None):
    """`lemon burst 10,20,30 top slow 720` -> the looks, the cut counts, and the words not understood.
    What the line does not name comes from `base` (the chat's menu), else the defaults."""
    t = norm(text)
    for name in sorted((n for n in words if " " in n), key=len, reverse=True):   # names of two words first
        t = t.replace(name, " " + name.replace(" ", "") + " ")
    picks, cuts, unknown = {}, [], []
    for tok in re.split(r"[\s,،;]+", t):
        if not tok or tok in FILLER:
            continue
        if "=" in tok:                          # material=glass: the look named outright
            k, v = tok.split("=", 1)
            if v in bycat.get(k, {}):
                picks[k] = bycat[k][v]
            else:
                unknown.append(tok)
        elif tok.isdigit():
            n = int(tok)
            if n in (720, 1080):
                picks["video"] = str(n)
            elif 1 <= n <= MAX_CUT:
                cuts.append(n)
            else:
                unknown.append(tok)
        elif tok in words:
            cat, i = words[tok]
            picks[cat] = i
        else:
            unknown.append(tok)
    o = dict(base or DEFAULTS)
    th = options.get("theme", {}).get(picks.pop("theme", None) or "")
    if th:                                      # a theme is a board, a backdrop and maybe a fruit
        o.update({k: th[k] for k in ("board", "backdrop", "fruit") if th.get(k)})
    o.update(picks)
    return o, cuts[:MAX_PARTS] or o.pop("cuts", CUTS), unknown


def name_of(cat, i):
    v = options.get(cat, {}).get(i, {})
    v = v.get("name", v)
    return v.get("fa") or v.get("en") or i


def help_text():
    return ("/menu منوی دکمه‌ای: همه‌ی گزینه‌ها با یک لمس.\n\n"
            "یا یک خط بفرست، ویدیو را می‌سازم و همین‌جا می‌فرستم. مثلاً:\n\n"
            "lemon burst 10,20,30\n"
            "هندوانه دایس 5 15 50 top slow\n"
            "pumpkin halloween 20 720 lite\n\n"
            "عددهای ۱ تا ۵۰۰ = تعداد برش هر بخش (تا ۶ بخش)\n"
            "720 یا 1080 = اندازه‌ی ویدیو · lite = سریع‌تر و سبک‌تر · full = کامل\n"
            "هر چه نگویی از تنظیمات منو می‌آید\n"
            "اگر یک کلمه دو معنی دارد، کامل بنویس: material=glass\n\n"
            "/options فهرست میوه‌ها و ظاهرها")


def options_text():
    rows = []
    for cat, title in [("fruit", "میوه"), ("knife", "چاقو"), ("board", "تخته (board=)"), ("backdrop", "پس‌زمینه"), ("theme", "تم")]:
        rows.append(f"{title}:\n" + ", ".join(f"{i} ({name_of(cat, i)})" for i in options.get(cat, {})))
    rows.append("نوع برش: burst, dice, free\nدوربین: front, top, close\nسرعت: slow, normal, fast\n"
                "جنس: real, glass · اندازه‌ی میوه: small, medium, large\n"
                "نت‌ها: piano, organ, musicbox, marimba, notes=glass, nonotes\n"
                "صدای برش: cutsound=auto, cutsound=knife, cutsound=glass\n"
                "نوع ادیت: loop (لوپ بی‌درز) · پیش‌فرض edit=normal\n"
                "قالب: vs (1 Cut VS N Cuts) · پیش‌فرض format=normal")
    return "\n\n".join(rows)


# --- the menu: buttons under a message ----------------------------------------------------------

CATS = [("fruit", "🍋 میوه"), ("style", "✂️ برش"), ("cuts", "🔢 تعداد"), ("camera", "🎥 دوربین"), ("speed", "⚡ سرعت"),
        ("edit", "🎬 ادیت"), ("notes", "🎵 نت"), ("cutsound", "🔊 صدا"), ("knife", "🔪 چاقو"), ("board", "🪵 تخته"),
        ("backdrop", "🖼 پس‌زمینه"), ("theme", "🎨 تم"), ("material", "💎 جنس"), ("size", "📏 میوه"),
        ("video", "📐 ویدیو"), ("quality", "✨ کیفیت"), ("format", "🎞 قالب")]
TITLES = {"cuts": "تعداد برش هر بخش (۱ تا ۵۰۰، تا ۶ بخش)\nیک سری آماده را بزن، یا با «ساختن دلخواه» عددها را دانه‌دانه بچین، یا «تایپ عدد».",
          "format": "قالب ویدیو\n1 VS N: مثل ویدیوهای Blender؛ ۲ ثانیه از اوج بخش آخر در شروع، عنوان کوچک‌تر، بدون شمارش قطعه‌ها و بدون نت.\n"
                    "این قالب کل ویدیو را در یک مرورگر می‌سازد: روی حافظه‌ی ۱ گیگ فقط با 720 و سبک.",
          "edit": "نوع ادیت\nلوپ بی‌درز: فریم آخر به فریم اول می‌رسد.",
          "notes": "سازی که با هر برش یک نت می‌زند", "cutsound": "صدای برش\nخودکار: برای میوه‌ی شیشه‌ای شیشه، وگرنه چاقو.",
          "theme": "تم: تخته و پس‌زمینه را با هم عوض می‌کند.", "video": "اندازه‌ی ویدیو\n1080 حدود ۱.۵ گیگ حافظه می‌خواهد.",
          "quality": "کیفیت\nکامل: سایه و جزئیات بیشتر، کندتر و پرمصرف‌تر."}
LABELS = {
    "style": {"burst": "برست", "dice": "دایس", "free": "آزاد"},
    "camera": {"front": "روبرو", "top": "بالا", "close": "نزدیک"},
    "speed": {"slow": "آهسته", "normal": "معمولی", "fast": "تند"},
    "edit": {"normal": "معمولی", "loop": "لوپ"},
    "notes": {"piano": "پیانو", "organ": "ارگ", "musicbox": "جعبه‌موسیقی", "marimba": "ماریمبا", "glass": "شیشه", "off": "بدون نت"},
    "cutsound": {"auto": "خودکار", "knife": "چاقو", "glass": "شیشه"},
    "material": {"real": "واقعی", "glass": "شیشه‌ای"},
    "size": {"s": "کوچک", "m": "متوسط", "l": "بزرگ"},
    "video": {"720": "720", "1080": "1080"},
    "quality": {"lite": "سبک", "full": "کامل"},
    "format": {"normal": "معمولی", "vs": "1 VS N"},
}
CUT_PRESETS = ["10,20,30", "5,15,30", "1,10,50", "1,10,100", "10,50,100", "1,5,10,50,100", "1,10,100,200", "1,50,100,200",
               "1,10,100,200,500", "50,100,200", "100,200,300", "1,100,500", "20", "50", "100", "200", "300", "500"]
ADD = [1, 2, 3, 5, 8, 10, 15, 20, 25, 30, 40, 50, 75, 100, 150, 200, 300, 500]   # the builder's number pad
typing = set()                                  # chats whose next line of numbers is the menu's cut counts
MENU_TEXT = "🎛 تنظیمات ویدیو\nهر گزینه را بزن و آخر «ساخت ویدیو» را."
settings = {}                                   # chat -> its menu; a restart goes back to the defaults


def menu_of(chat):
    return settings.setdefault(chat, dict(DEFAULTS, cuts=list(CUTS)))


def choices(cat):
    if cat == "cuts":
        return [(c, c.replace(",", " · ")) for c in CUT_PRESETS]
    return list(LABELS[cat].items()) if cat in LABELS else [(i, name_of(cat, i)) for i in options.get(cat, {})]


def now(s, cat):
    return ",".join(map(str, s["cuts"])) if cat == "cuts" else s.get(cat, "")


def grid(buttons, n):
    return [buttons[i:i + n] for i in range(0, len(buttons), n)]


def main_keys(s):
    def value(cat):
        return dict(choices(cat)).get(now(s, cat), now(s, cat).replace(",", "·")) or "انتخاب"
    keys = grid([{"text": f"{title}: {value(cat)}", "callback_data": f"c:{cat}"} for cat, title in CATS], 2)
    return keys + [[{"text": "▶️ ساخت ویدیو", "callback_data": "go"}]]


def cat_keys(s, cat):
    keys = [{"text": ("✅ " if i == now(s, cat) else "") + label, "callback_data": f"s:{cat}:{i}"} for i, label in choices(cat)]
    extra = [[{"text": "🧩 ساختن دلخواه", "callback_data": "b:new"}, {"text": "⌨️ تایپ عدد", "callback_data": "t"}]] if cat == "cuts" else []
    return grid(keys, 3) + extra + [[{"text": "⬅️ برگشت", "callback_data": "m"}]]


def build_text(s):
    series = " · ".join(map(str, s.get("draft", []))) or "—"
    return f"🧩 ساختن سری دلخواه\nسری: {series}\nهر عدد را بزن تا به آخر سری برود (تا {MAX_PARTS} عدد)، بعد «ثبت»."


def build_keys():
    pad = grid([{"text": str(n), "callback_data": f"b:+{n}"} for n in ADD], 6)
    return pad + [[{"text": "↩️ حذف آخری", "callback_data": "b:undo"}, {"text": "🗑 پاک", "callback_data": "b:clear"}],
                  [{"text": "✅ ثبت", "callback_data": "b:ok"}, {"text": "⬅️ برگشت", "callback_data": "c:cuts"}]]


def send_menu(chat):
    ready.wait(300)                             # just after a start the looks are still loading
    tg("sendMessage", chat_id=chat, text=MENU_TEXT, reply_markup={"inline_keyboard": main_keys(menu_of(chat))})


def enqueue(chat, msg_id, o, cuts):
    ahead = jobs.unfinished_tasks
    jobs.put((chat, msg_id, o, cuts))
    if ahead:
        say(chat, f"در صف: {ahead} ویدیو جلوتر است.", msg_id)


def press(q):
    """A button under a message."""
    chat, user = q["message"]["chat"]["id"], q.get("from", {}).get("id")
    if not allowed(user, chat):
        tg("answerCallbackQuery", callback_query_id=q["id"])
        return log("ignored a button from", user)
    s, data = menu_of(chat), q.get("data", "")
    tg("answerCallbackQuery", callback_query_id=q["id"], text="ساخته می‌شود ⏳" if data == "go" else None)

    def show(text, keys):
        tg("editMessageText", chat_id=chat, message_id=q["message"]["message_id"], text=text, reply_markup={"inline_keyboard": keys})

    if data == "n":                             # under a finished video, which cannot turn into a menu
        send_menu(chat)
    elif data == "go":
        enqueue(chat, None, dict(s), list(s["cuts"]))
    elif data.startswith("b:"):                 # the series builder
        d, op = s.setdefault("draft", []), data[2:]
        if op == "new":
            d.clear()
        elif op.startswith("+") and int(op[1:]) in ADD and len(d) < MAX_PARTS:
            d.append(int(op[1:]))
        elif op == "undo" and d:
            d.pop()
        elif op == "clear":
            d.clear()
        elif op == "ok" and d:
            s["cuts"] = list(d)
            return show(MENU_TEXT, main_keys(s))
        show(build_text(s), build_keys())
    elif data == "t":
        typing.add(chat)
        show(f"⌨️ عددها را بفرست، مثلاً 7,25,80 یا 1 10 100 500\n(۱ تا {MAX_CUT}، تا {MAX_PARTS} عدد). در منو ثبت می‌شوند و ویدیو هنوز ساخته نمی‌شود.",
             [[{"text": "⬅️ برگشت", "callback_data": "c:cuts"}]])
    elif data.startswith("c:") and data[2:] in dict(CATS):
        typing.discard(chat)
        cat = data[2:]
        show(TITLES.get(cat, dict(CATS)[cat]), cat_keys(s, cat))
    elif data.startswith("s:"):
        _, cat, v = data.split(":", 2)
        if cat in dict(CATS) and v in dict(choices(cat)):
            if cat == "cuts":
                s["cuts"] = [int(n) for n in v.split(",")]
            elif cat == "theme":                # a theme is a board, a backdrop and maybe a fruit
                th = options["theme"][v]
                s.update({k: th[k] for k in ("board", "backdrop", "fruit") if th.get(k)})
            else:
                s[cat] = v
        show(MENU_TEXT, main_keys(s))
    else:
        show(MENU_TEXT, main_keys(s))


# --- recording -----------------------------------------------------------------------------------

def make_video(browser, o, cuts, on_status, name, **extra):
    """Records one take, or one part of it (extra: append=1 / tail=0); where to ask for its MP4 once the browser is closed."""
    w, h = ("720", "1280") if o["video"] == "720" else ("1080", "1920")
    q = dict(cuts=",".join(map(str, cuts)), style=o["style"], camera=o["camera"], fruit=o["fruit"], speed=o["speed"],
             board=o["board"], backdrop=o["backdrop"], knife=o["knife"], material=o["material"], size=o["size"],
             notes=o["notes"], cutsound=o["cutsound"], edit=o["edit"], **({"format": "vs"} if o.get("format") == "vs" else {}),
             quality="best" if o["quality"] == "full" else "battery", w=w, h=h, fps=30, name=name, defer=1,
             **{k: v for k, v in extra.items() if v is not None})
    page = browser.new_page(viewport={"width": 540, "height": 960})
    errors = []
    page.on("pageerror", lambda e: errors.append(str(e)))
    try:
        page.goto(f"http://127.0.0.1:{PORT}/_rec/record.html?{urllib.parse.urlencode(q)}", timeout=120000)
        seen, changed, told = None, time.time(), 0.0
        while True:
            done = page.evaluate("window.__recDone || null")
            if done:
                break
            status = page.evaluate("(document.getElementById('rec') || {}).textContent || ''")
            if status != seen:
                seen, changed = status, time.time()
            if time.time() - changed > 600:     # nothing new for 10 minutes: the page is stuck
                done = {"error": "stuck at: " + status + (" / " + errors[-1] if errors else "")}
                break
            if time.time() - told > 20:
                on_status(status)
                told = time.time()
            page.wait_for_timeout(3000)
    finally:
        page.close()
    if not done.get("encode"):
        raise RuntimeError(done.get("error") or "the recording failed")
    return done["encode"]


def encode(url):
    """Frames and sound -> MP4, with the browser's memory free again."""
    req = urllib.request.Request(f"http://127.0.0.1:{PORT}{url}", data=b"", method="POST")
    try:
        with urllib.request.urlopen(req, timeout=1800) as r:
            return Path(json.load(r)["path"])
    except urllib.error.HTTPError as e:
        raise RuntimeError("encoding failed: " + str(json.load(e).get("error"))[:600])


def seconds(path):
    r = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(path)],
                       capture_output=True, text=True)
    return float(r.stdout.strip() or 0)


def fit(path, dur):
    """A copy small enough for Telegram (the bitrate that just fits), when the video is not."""
    if path.stat().st_size <= TG_LIMIT:
        return path
    kbps = max(500, int(TG_LIMIT * 8 * 0.9 / max(dur, 1) / 1000) - 128)
    small = path.with_name(path.stem + "-tg.mp4")
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(path), "-c:v", "libx264", "-preset", "medium", "-threads", "2", "-b:v", f"{kbps}k",
                    "-maxrate", f"{int(kbps * 1.3)}k", "-bufsize", f"{kbps * 2}k", "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "128k",
                    "-movflags", "+faststart", str(small)], check=True)
    return small


jobs = queue.Queue()


def worker():
    from playwright.sync_api import sync_playwright
    pw = sync_playwright().start()
    try:
        with_browser(pw, load_options)
    except Exception:                           # noqa: BLE001
        log("options:", traceback.format_exc())
    ready.set()
    while True:
        chat, msg_id, o, cuts = jobs.get()
        note = say(chat, f"⏳ شروع شد: {name_of('fruit', o['fruit'])} · {o['style']} · {'/'.join(map(str, cuts))}", msg_id)
        note_id = note and note.get("message_id")
        last = [""]

        def on_status(s, chat=chat, note_id=note_id):
            s = s.split("\n", 1)[-1].strip()
            if note_id and s and s != last[0]:
                last[0] = s
                tg("editMessageText", chat_id=chat, message_id=note_id, text="⏳ " + s)

        started, files = time.time(), []
        try:
            log("game:", get_game())
            ensure_server()
            # each segment in a browser of its own: memory never piles up from one segment into the next
            name = f"{o['fruit']}-{o['style']}-{'-'.join(map(str, cuts))}-{int(time.time())}"
            # (the 1 VS N format is one take: its opening is cut from the last segment)
            parts = [cuts] if o.get("format") == "vs" else [[n] for n in cuts]
            for k, seg in enumerate(parts):
                part = (lambda s, k=k: on_status(f"بخش {k + 1} از {len(parts)} · {s.split(chr(10), 1)[-1]}")) if len(parts) > 1 else on_status
                final = k == len(parts) - 1
                url = with_browser(pw, lambda b: make_video(b, o, seg, part, name, append=1 if k else None, tail=None if final else 0))
            on_status("در حال ساختن MP4…")
            path = encode(url)
            files.append(path)
            dur = seconds(path)
            send = fit(path, dur)
            files.append(send)
            on_status(f"در حال فرستادن ({send.stat().st_size / 1e6:.0f} MB)…")
            w, h = (720, 1280) if o["video"] == "720" else (1080, 1920)
            tg_file("sendVideo", "video", send, chat_id=chat, reply_to_message_id=msg_id, supports_streaming=True,
                    width=w, height=h, duration=int(dur), reply_markup={"inline_keyboard": [[{"text": "🎛 منو", "callback_data": "n"}]]},
                    caption=f"{name_of('fruit', o['fruit'])} · {o['style']} · {'/'.join(map(str, cuts))} cuts{' · loop' if o['edit'] == 'loop' else ''}{' · 1 VS N' if o.get('format') == 'vs' else ''} · {(time.time() - started) / 60:.1f} min")
            if note_id:
                tg("deleteMessage", chat_id=chat, message_id=note_id)
        except Exception as e:                  # noqa: BLE001
            log(traceback.format_exc())
            hint = "\n\nحافظه‌ی سرور کم آمد: اندازه‌ی ویدیو را 720 و کیفیت را سبک بگذار، یا حافظه‌ی سرور را بیشتر کن." if "out of memory" in str(e) else ""
            say(chat, f"❌ {str(e)[:900]}{hint}", msg_id)
        finally:
            for f in files:
                f.unlink(missing_ok=True)
            jobs.task_done()


def with_browser(pw, fn):
    browser = pw.chromium.launch(args=CHROME)
    try:
        return fn(browser)
    finally:
        browser.close()


def load_options(browser):
    log("game:", get_game())
    ensure_server()
    page = browser.new_page()
    try:
        page.goto(f"http://127.0.0.1:{PORT}/_rec/options.html", timeout=120000)
        page.wait_for_function("window.__options", timeout=120000)
        opts = page.evaluate("window.__options")
        log("WebGL:", page.evaluate("""() => { const gl = document.createElement('canvas').getContext('webgl2');
          const e = gl && gl.getExtension('WEBGL_debug_renderer_info'); return gl ? gl.getParameter(e ? e.UNMASKED_RENDERER_WEBGL : gl.RENDERER) : null; }"""))
    finally:
        page.close()
    if opts.get("error"):
        raise RuntimeError(opts["error"])
    learn(opts)
    log("looks:", {k: len(v) for k, v in opts.items()})


# --- the conversation ----------------------------------------------------------------------------

def allowed(user, chat):
    return str(user) in OWNERS or str(chat) in OWNERS


def handle(msg):
    chat, user = msg["chat"]["id"], msg.get("from", {}).get("id")
    text = (msg.get("text") or "").strip()
    if not text:
        return
    if not OWNERS:
        say(chat, f"شناسه‌ی شما: {user}\nدر Railway متغیر OWNER_ID را {user} بگذارید تا ربات برای شما کار کند.", msg["message_id"])
        return
    if not allowed(user, chat):
        log("ignored a message from", user)
        return
    cmd = text.split()[0].split("@")[0].lower()
    if cmd in ("/start", "/menu"):
        send_menu(chat)
    elif cmd == "/help":
        say(chat, help_text())
    elif cmd == "/options":
        say(chat, options_text())
    elif cmd.startswith("/"):
        say(chat, help_text())
    else:
        ready.wait(300)                         # just after a start the looks are still loading
        o, cuts, unknown = parse(text, menu_of(chat))
        if chat in typing and not unknown and re.fullmatch(r"[\d\s,،;۰-۹٠-٩]+", text):
            typing.discard(chat)
            menu_of(chat)["cuts"] = list(cuts)
            return send_menu(chat)
        if unknown:
            say(chat, "این‌ها را نشناختم: " + " ".join(unknown) + "\n/options فهرست همه‌چیز", msg["message_id"])
            return
        enqueue(chat, msg["message_id"], o, list(cuts))


def main():
    missing = [k for k, v in (("TG_TOKEN", TOKEN), ("GAME_REPO", REPO)) if not v]
    if missing:
        sys.exit("set " + ", ".join(missing))
    learn(options)
    threading.Thread(target=worker, daemon=True).start()
    me = tg("getMe")
    log("bot:", me and me.get("username"), "owners:", len(OWNERS))
    tg("setMyCommands", commands=[{"command": "menu", "description": "منوی ساخت ویدیو"}, {"command": "help", "description": "راهنمای نوشتنی"},
                                  {"command": "options", "description": "فهرست میوه‌ها و ظاهرها"}])
    for owner in OWNERS:                        # also how you learn a video died with the server (out of memory)
        say(owner, "✅ ربات روشن شد: /menu\nاگر ویدیویی در حال ساخت بود قطع شده است؛ دوباره بفرست (با حافظه‌ی کم: 720 و سبک).")
    offset = None
    while True:
        updates = tg("getUpdates", offset=offset, timeout=50, allowed_updates=["message", "callback_query"])
        if updates is None:
            time.sleep(5)
            continue
        for u in updates:
            offset = u["update_id"] + 1
            if "message" in u or "callback_query" in u:
                try:
                    press(u["callback_query"]) if "callback_query" in u else handle(u["message"])
                except Exception:               # noqa: BLE001
                    log(traceback.format_exc())


if __name__ == "__main__":
    main()
