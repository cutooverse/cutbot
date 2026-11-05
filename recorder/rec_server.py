"""Recorder server: serves the game and saves what _rec/record.html sends, then builds the MP4.

    ..\\..\\.venv\\Scripts\\python rec_server.py          (from cutgame/_rec)  ->  http://localhost:8770/_rec/record.html

POST /rec/start?name=X      start a take (clears _rec/out/X)
POST /rec/frame?i=N         one JPEG frame
POST /rec/audio             the WAV soundtrack
POST /rec/done?fps=30       encode -> _rec/out/X.mp4, answers {"path": ...}
     &loop=N               a seamless loop that starts at frame N -> _rec/out/X_loop.mp4
"""
from array import array
import functools
import http.server
import json
import os
import shutil
import subprocess
import sys
import wave
from pathlib import Path
from urllib.parse import urlparse, parse_qs

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent                                  # the game folder
OUT = Path(os.environ.get("REC_OUT", HERE / "out"))        # finished videos (on Colab: a Drive folder)
WORK = Path(os.environ.get("REC_WORK", HERE / "out"))      # frames while recording (kept off Drive: faster)
THREADS = os.environ.get("REC_THREADS")             # for ffmpeg on a small server
take = {"dir": None, "name": None}
LOOP_FADE = 0.012                                   # s: only on the old end -> start join, so it does not click


def ffmpeg():
    try:
        import imageio_ffmpeg
        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:                               # noqa: BLE001
        return "ffmpeg"


def rotate_take(d, seam, fps):
    """Seamless loop: frames seam..end then 0..seam-1, the sound cut at the same moment with no fade
    there (the last frame and the first are neighbours in the recording). The frames dir and WAV to encode."""
    frames = sorted((d / "frames").glob("*.jpg"))
    if not 0 < seam < len(frames):
        raise ValueError(f"loop frame {seam} is outside the {len(frames)} frames")
    out = d / "frames_loop"
    shutil.rmtree(out, ignore_errors=True)
    out.mkdir()
    for k, f in enumerate(frames[seam:] + frames[:seam]):
        os.replace(f, out / f"{k:05d}.jpg")
    wav = d / "audio.wav"
    if not wav.exists():
        return out, None
    with wave.open(str(wav)) as w:
        params, pcm = w.getparams(), array("h", w.readframes(w.getnframes()))
    ch, rate = params.nchannels, params.framerate
    cut = round(seam * rate / float(fps)) * ch
    head, tail = pcm[cut:], pcm[:cut]
    n = min(int(rate * LOOP_FADE), len(head) // ch, len(tail) // ch)
    for i in range(n):                              # the old join, now inside the video
        for c in range(ch):
            g = i / n
            head[len(head) - (i + 1) * ch + c] = int(head[len(head) - (i + 1) * ch + c] * g)
            tail[i * ch + c] = int(tail[i * ch + c] * g)
    looped = d / "audio_loop.wav"
    with wave.open(str(looped), "wb") as w:
        w.setparams(params)
        w.writeframes((head + tail).tobytes())
    return out, looped


class Handler(http.server.SimpleHTTPRequestHandler):
    def send_head(self):
        if "If-Modified-Since" in self.headers:
            del self.headers["If-Modified-Since"]
        return super().send_head()

    def end_headers(self):
        self.send_header("Cache-Control", "no-store")
        super().end_headers()

    def log_message(self, fmt, *args):              # frames would flood the console
        if "/rec/frame" not in str(args[0] if args else ""):
            super().log_message(fmt, *args)

    def reply(self, code, obj):
        body = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self):
        u = urlparse(self.path)
        q = {k: v[0] for k, v in parse_qs(u.query).items()}
        data = self.rfile.read(int(self.headers.get("Content-Length", 0)))
        if u.path == "/rec/start":
            name = "".join(c for c in q.get("name", "take") if c.isalnum() or c in "-_") or "take"
            d = WORK / name
            shutil.rmtree(d, ignore_errors=True)
            (d / "frames").mkdir(parents=True)
            take.update(dir=d, name=name)
            return self.reply(200, {"ok": True})
        if not take["dir"]:
            return self.reply(400, {"error": "no take started"})
        d = take["dir"]
        if u.path == "/rec/frame":
            (d / "frames" / f"{int(q['i']):05d}.jpg").write_bytes(data)
            return self.reply(200, {"ok": True})
        if u.path == "/rec/audio":
            (d / "audio.wav").write_bytes(data)
            return self.reply(200, {"ok": True})
        if u.path == "/rec/done":
            fps = q.get("fps", "30")
            OUT.mkdir(parents=True, exist_ok=True)
            frames, audio = d / "frames", d / "audio.wav"
            suffix = ""
            if q.get("loop"):
                frames, audio = rotate_take(d, int(q["loop"]), fps)
                suffix = "_loop"
            out = OUT / f"{take['name']}{suffix}.mp4"
            cmd = [ffmpeg(), "-y", "-loglevel", "error", "-framerate", fps, "-i", str(frames / "%05d.jpg")]
            if audio and audio.exists():
                cmd += ["-i", str(audio), "-c:a", "aac", "-b:a", "192k"]
            cmd += ["-c:v", "libx264", "-preset", "medium", "-crf", "17", "-pix_fmt", "yuv420p", "-movflags", "+faststart", "-shortest"]
            if THREADS:                                 # x264 takes memory per core it sees, and a cloud box shows many
                cmd += ["-threads", THREADS, "-rc-lookahead", "20"]
            cmd.append(str(out))
            r = subprocess.run(cmd, capture_output=True, text=True)
            if r.returncode:
                killed = " (killed from outside: probably out of memory)" if r.returncode < 0 else ""
                return self.reply(500, {"error": r.stderr[-800:].strip() or f"ffmpeg stopped with code {r.returncode}{killed}"})
            if WORK != OUT:
                shutil.rmtree(d, ignore_errors=True)            # frames are not needed any more
            print(f"wrote {out}", flush=True)
            return self.reply(200, {"path": str(out)})
        return self.reply(404, {"error": "unknown"})


port = int(sys.argv[1]) if len(sys.argv) > 1 else int(os.environ.get("PORT", 8770))
print(f"recorder on http://localhost:{port}/_rec/record.html", flush=True)
http.server.ThreadingHTTPServer(("127.0.0.1", port), functools.partial(Handler, directory=str(ROOT))).serve_forever()
