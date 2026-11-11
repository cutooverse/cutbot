# Cut Count video bot

A Telegram bot that records videos of the Cut Count game: send it `lemon burst 10,20,30` and it
sends back the MP4. It runs anywhere Docker runs (Railway, Render, Fly.io, a VPS) and needs no
open port: it asks Telegram for messages (long polling).

## Variables

| name | what |
|---|---|
| `TG_TOKEN` | the bot's token from @BotFather |
| `OWNER_ID` | your Telegram user id (several: comma-separated). Leave it empty at first: the bot answers with your id |
| `GAME_REPO` | the game's public GitHub repository, `owner/name` |

## Railway

1. Put this folder in a GitHub repository of its own (private is fine).
2. Railway: New Project → Deploy from GitHub repo → that repository. It builds the `Dockerfile`.
3. The service's Variables: `TG_TOKEN`, `GAME_REPO` (and `OWNER_ID` once you know it). It redeploys.
4. Message the bot. `/menu` is the button menu, `/help` how to type a request, `/options` every fruit and look.

Each segment is recorded in a browser of its own and the MP4 is built after the browser closes, so memory
does not pile up. Measured on Windows (Edge, SwiftShader) for 1080 at full quality, 5/15/30 cuts: about
0.8 GB per segment, about 0.3 GB for the encode. Railway's Trial stops at 1 GB, its Free plan at 0.5 GB.

## Files

- `railway.json` Railway's settings: build the Dockerfile, one copy only (Telegram allows one reader), always restart
- `bot.py` the bot
- `recorder/` a copy of the game's `_rec` recorder; `python sync_recorder.py` copies it again
