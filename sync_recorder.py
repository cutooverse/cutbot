"""Copies the recorder from the game's folder (cutgame/_rec, kept out of the game's repository).

    python sync_recorder.py        after changing record.js / record.html / rec_server.py / options.html
"""
import shutil
from pathlib import Path

HERE = Path(__file__).resolve().parent
SRC = HERE.parent / "cutgame" / "_rec"
(HERE / "recorder").mkdir(exist_ok=True)
for name in ("record.html", "record.js", "rec_server.py", "options.html"):
    shutil.copy(SRC / name, HERE / "recorder" / name)
    print("copied", name)
