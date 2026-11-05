// Records the game into a video, frame by frame on a made-up clock: no dropped frames, the sound
// put back exactly where each hit happened. One take = a Chop run for every cut count in ?cuts=.
//
//   http://localhost:8770/_rec/record.html?cuts=10,20,30&style=burst&camera=front&fruit=orange
//   other options: speed, board, backdrop, material, knife, size, cutsound (auto, knife, glass),
//   notes (off, piano, organ, musicbox, marimba, glass), edit (normal, loop), w=1080, h=1920, fps=30, name

const P = new URLSearchParams(location.search);
const CUTS = (P.get("cuts") || "10,20,30").split(",").map(Number).filter(n => n > 0);
const W = +(P.get("w") || 1080), H = +(P.get("h") || 1920), FPS = +(P.get("fps") || 30);
const NAME = P.get("name") || `${P.get("fruit") || "orange"}-${P.get("style") || "burst"}-${CUTS.join("-")}`;
const say = t => { document.getElementById("rec").textContent = t; };
// any failure ends the take, so whoever is waiting (the Colab notebook) is told instead of waiting forever
addEventListener("error", e => { window.__recDone = { error: String(e.message) }; });
addEventListener("unhandledrejection", e => { window.__recDone = { error: String(e.reason) }; });

// --- the game's own page: index.html's styles and markup
const doc = new DOMParser().parseFromString(await (await fetch("index.html")).text(), "text/html");
doc.querySelectorAll("style").forEach(n => document.head.appendChild(n.cloneNode(true)));
const note = document.getElementById("rec");
document.body.innerHTML = doc.body.innerHTML;
document.body.querySelectorAll("script").forEach(s => s.remove());
document.body.appendChild(note);

// --- looks for this take (this origin keeps its own storage, the game's is untouched)
localStorage.setItem("cutcount.v1", JSON.stringify({
  looks: { fruit: P.get("fruit") || "orange", style: P.get("style") || "burst", camera: P.get("camera") || "front",
    speed: P.get("speed") || "normal", cuts: CUTS[0], board: P.get("board") || "walnut", backdrop: P.get("backdrop") || "teal",
    material: P.get("material") || "real", knife: P.get("knife") || "chef", size: P.get("size") || "m" },
  // quality: best (full shadows) or battery (the light phone profile: much faster without a GPU)
  settings: { sound: true, haptics: false, strength: "normal", quality: P.get("quality") || "best", lang: "en",
    cutSound: P.get("cutsound") || "auto", notes: P.get("notes") || "piano" }, stars: Array(9).fill(3),   // the Sound sheet
}));

// --- a made-up clock and a frame the size of the video
let vnow = 0, waiting = [];
performance.now = () => vnow;
// three.js runs its loop on requestAnimationFrame: hold those callbacks and run them per frame
window.requestAnimationFrame = cb => { waiting.push(cb); return waiting.length; };
window.cancelAnimationFrame = () => {};
Object.defineProperty(window, "innerWidth", { get: () => W / 2 });
Object.defineProperty(window, "innerHeight", { get: () => H / 2 });
Object.defineProperty(window, "devicePixelRatio", { get: () => 2 });

// --- every sound is noted with its moment, and rendered afterwards
const S = await import("../src/sound.js");
const { store } = await import("../src/store.js");     // the game's own settings object
// every look a video would open is open for the recording (a locked one falls back to the default)
store.unlocked = [...(await import("../src/tasks.js")).VIDEO_UNLOCK];
const heard = [], play = {};
for (const k of Object.keys(S.sfx)) { play[k] = S.sfx[k]; S.sfx[k] = (...a) => heard.push({ k, a, t: vnow / 1000 }); }

say("starting the game…");
await import("../src/app.js");
await document.fonts.load("900 100px Poppins");

const $ = id => document.getElementById(id);
const gl = document.querySelector("#stage canvas");
const out = document.createElement("canvas"); out.width = W; out.height = H;
const g = out.getContext("2d");
const preview = document.createElement("canvas"); preview.id = "preview"; preview.width = W / 4; preview.height = H / 4;
document.body.appendChild(preview);

const post = (path, body) => fetch(path, { method: "POST", body }).then(r => r.json());
let fi = 0, title = "", showCount = false;

function overlay() {
  const k = W / 1080;
  g.textAlign = "center"; g.textBaseline = "alphabetic";
  g.shadowColor = "rgba(0,0,0,0.5)"; g.shadowBlur = 24 * k; g.shadowOffsetY = 4 * k;
  if (title) {
    g.font = `900 ${140 * k}px Poppins, sans-serif`; g.fillStyle = "#fdfaf4";
    g.fillText(title, W / 2, 185 * k);                 // above the knife waiting over the fruit
  }
  const sub = $("chopSub").textContent, n = sub.replace(/[^\d]/g, "");
  if (showCount && n && n !== "1") {
    g.font = `900 ${170 * k}px Poppins, sans-serif`; g.fillStyle = "#fdfaf4";
    g.fillText(Number(n).toLocaleString("en-US"), W / 2, H - 330 * k);
    g.font = `800 ${52 * k}px Poppins, sans-serif`; g.fillStyle = "#ff4136";
    g.fillText("PIECES", W / 2, H - 250 * k);
  }
  g.shadowColor = "transparent";
}

async function frame() {
  vnow += 1000 / FPS;
  const run = waiting; waiting = [];
  for (const cb of run) cb(vnow);
  g.drawImage(gl, 0, 0, W, H);                         // right after the render, before the buffer clears
  overlay();
  preview.getContext("2d").drawImage(out, 0, 0, preview.width, preview.height);
  const jpg = await new Promise(r => out.toBlob(r, "image/jpeg", 0.92));
  await fetch(`/rec/frame?i=${fi++}`, { method: "POST", body: jpg });
}
const frames = async s => { for (let i = 0; i < Math.round(s * FPS); i++) await frame(); };

// any count: set it on the game's settings, then pick the current size again, which starts a new round
function setCuts(n) {
  store.looks.cuts = n;
  $("hudLooks").click();
  document.querySelector('[data-tab="fruit"]').click();
  document.querySelector(`[data-seg="size"] [data-v="${store.looks.size}"]`).click();
  $("sheetDone").click();
}

const press = type => gl.dispatchEvent(new PointerEvent(type, { bubbles: true, clientX: W / 4, clientY: H / 4, pointerId: 1, pointerType: "touch", isPrimary: true }));

// edit=loop: a seamless loop. The server turns the timeline around at a frame in the middle of the
// last segment's chopping: both sides of that frame are one continuous shot with the same title
const LOOP = P.get("edit") === "loop";
let seam = 0;

await post(`/rec/start?name=${encodeURIComponent(NAME)}`);
document.querySelector('[data-mode="chop"]').click();
const started = Date.now();                            // the real clock, for the report
for (const [i, n] of CUTS.entries()) {
  setCuts(n);                                          // also starts a fresh fruit
  title = `${n} Cuts`; showCount = false;
  say(`${NAME}\n${title}: getting ready`);
  await frames(0.8);
  press("pointerdown");
  let guard = 0;
  const made = () => Number($("chopBig").textContent.split("/")[0].replace(/[^\d]/g, ""));
  const last = i === CUTS.length - 1;
  while (made() < n) {
    await frame();
    if (LOOP && last && !seam && made() >= Math.ceil(n / 2)) seam = fi;
    if (++guard > FPS * 60) break;                    // never more than a minute of chopping
    if (guard % 10 === 0) say(`${NAME}\n${title}: ${$("chopBig").textContent}  (frame ${fi})`);
  }
  if (LOOP && last && !seam) seam = fi;
  if (store.looks.style === "free") press("pointerup");   // Free style chops while held: let go at n
  showCount = true;
  await frames(3.2);                                  // the fall and the count
  press("pointerup");
}
if (!LOOP) { title = ""; await frames(0.4); }        // a loop ends on the pile, like every segment

say(`${NAME}\nrendering the sound…`);
const dur = fi / FPS, SR = 48000;
const oc = new OfflineAudioContext(2, Math.ceil(SR * dur), SR);
S.useOffline(oc);
for (const e of heard) { S.startAt(e.t); play[e.k](...e.a); }
const buf = await oc.startRendering();
await post("/rec/audio", wav(buf));

say(`${NAME}\nencoding the video…`);
const encode = `/rec/done?fps=${FPS}${seam ? `&loop=${seam}` : ""}`;
if (P.get("defer")) {                                  // the driver closes the browser first: a small server needs the memory
  window.__recDone = { encode };
} else {
  const res = await post(encode);
  window.__recDone = res;
  say(res.path ? `done: ${fi} frames, ${dur.toFixed(1)} s, ${heard.length} sounds\n${res.path}\n(${((Date.now() - started) / 1000).toFixed(0)} s to record)` : `failed: ${res.error}`);
}

function wav(b) {                                      // 16-bit PCM WAV of an AudioBuffer
  const ch = b.numberOfChannels, n = b.length, data = new DataView(new ArrayBuffer(44 + n * ch * 2));
  const str = (o, s) => [...s].forEach((c, i) => data.setUint8(o + i, c.charCodeAt(0)));
  str(0, "RIFF"); data.setUint32(4, 36 + n * ch * 2, true); str(8, "WAVEfmt ");
  data.setUint32(16, 16, true); data.setUint16(20, 1, true); data.setUint16(22, ch, true);
  data.setUint32(24, b.sampleRate, true); data.setUint32(28, b.sampleRate * ch * 2, true);
  data.setUint16(32, ch * 2, true); data.setUint16(34, 16, true); str(36, "data"); data.setUint32(40, n * ch * 2, true);
  const chans = [...Array(ch)].map((_, c) => b.getChannelData(c));
  let o = 44;
  for (let i = 0; i < n; i++) for (let c = 0; c < ch; c++) { const v = Math.max(-1, Math.min(1, chans[c][i])); data.setInt16(o, v * 0x7fff, true); o += 2; }
  return new Blob([data], { type: "audio/wav" });
}
