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
| `NVIDIA_API_KEY` | optional: captions (Instagram caption, YouTube title, description and tags) from build.nvidia.com; the rules are `captions.md`; the models are tried in order, `nvidia/nemotron-3-ultra-550b-a55b` then `z-ai/glm-5.3-flash` (`CAPTION_MODELS` to change them); a model that says nothing for 90 s is given up |

## Railway

1. Put this folder in a GitHub repository of its own (private is fine).
2. Railway: New Project → Deploy from GitHub repo → that repository. It builds the `Dockerfile`.
3. The service's Variables: `TG_TOKEN`, `GAME_REPO` (and `OWNER_ID` once you know it). It redeploys.
4. Message the bot. `/menu` is the button menu, `/help` how to type a request, `/options` every fruit and look.

Memory, for a server with 1 GB:

- each segment is recorded in a browser of its own, and the MP4 is built after the browser closes;
- at full quality each frame is drawn as 2 x 2 tiles on a canvas a quarter of the size (`tiles=2`), with the
  site's desktop quality (2048 shadows; 4096 alone take over 100 MB more);
- the first round starts without the Looks sheet, which would draw every fruit's thumbnail;
- a part that fails is recorded once more; each part's peak memory is logged.

Measured on Windows (headless Edge, SwiftShader), 1080 at full quality: 0.48 GB for the browser in one
segment (0.77 GB before), 0.63 GB with the helpers for a 5/10/40/75 video, 0.36 GB for the encode.

## Files

- `railway.json` Railway's settings: build the Dockerfile, one copy only (Telegram allows one reader), always restart
- `bot.py` the bot
- `captions.py` the caption writer, `captions.md` its rules (the Cutooverse caption guide)
- `recorder/` a copy of the game's `_rec` recorder; `python sync_recorder.py` copies it again
