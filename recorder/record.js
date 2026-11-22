// Records the game into a video, frame by frame on a made-up clock: no dropped frames, the sound
// put back exactly where each hit happened. One take = a Chop run for every cut count in ?cuts=.
//
//   http://localhost:8770/_rec/record.html?cuts=10,20,30&style=burst&camera=front&fruit=orange
//   other options: speed, board, backdrop, material, knife, size, cutsound (auto, knife, glass),
//   notes (off, piano, organ, musicbox, marimba, glass), edit (normal, loop), w=1080, h=1920, fps=30, name
//   knife=saw: the chainsaw (sawvoice: classic, deep); the clip runs on until its motor has run down
//   format=vs: the "1 Cut VS N Cuts" short: a 2 s opening from the last segment's frenzy, smaller titles,
//   no piece count, a zoom out into the first segment, no notes unless asked. blur=3: motion blur (3 renders a frame)
//   append=1: go on with the take of the same name (one segment per browser, for a server short of memory);
//   tail=0: no empty moment at the end (a segment that is not the last)
//   part=first|mid|last (format=vs in parts): the first keeps the opening's frames free, the last makes the
//   opening from its own frenzy and writes it there, with its sound apart (hook.wav, mixed in by the server);
//   series=25,75: the whole take's counts, for the opening's "25 Cuts VS 75 Cuts"
//   cover=1: no video, one still for a post's cover: the last count's pile, the count written on the blade
//   (cover=white or etched forces the letters; at, wide, tilt, settle: see cover())
//   tiles=2: each frame drawn as 2 x 2 tiles on a canvas a quarter of the size, then put together: the same
//   picture for much less memory and more time (a server with 1 GB)

const P = new URLSearchParams(location.search);
const CUTS = (P.get("cuts") || "10,20,30").split(",").map(Number).filter(n => n > 0);
const W = +(P.get("w") || 1080), H = +(P.get("h") || 1920), FPS = +(P.get("fps") || 30);
// Where the social apps draw over a video (Reels, TikTok, Shorts, on a 1080 x 1920 frame): their bar and
// buttons over the top 250 px, the caption and buttons over the bottom 420. Nothing to read goes there.
// The title and the count go under the top one; the game frames the scene (the cutter, the fruit, the board
// with its mark on the front edge) into the band between the words and the bottom one (CUT_BAND, shares of the height).
const SAFE_TOP = 262, SAFE_BOTTOM = 440;
window.CUT_BAND = [(P.get("format") === "vs" ? 540 : 480) / 1920, (1920 - SAFE_BOTTOM - 10) / 1920];
const COVER = P.get("cover");                          // a still for a post's cover instead of a video (see cover())
const SAW = P.get("knife") === "saw";                  // the chainsaw: its motor's start and run-down belong in the clip
const NAME = P.get("name") || `${P.get("fruit") || "orange"}-${P.get("style") || "burst"}-${CUTS.join("-")}`;
const VS = P.get("format") === "vs", BLUR = Math.max(1, +(P.get("blur") || 1));
const TILES = Math.max(1, Math.round(+(P.get("tiles") || 1)));
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
    speed: P.get("speed") || "normal", cuts: CUTS[0], board: P.get("board") || "walnut", backdrop: P.get("backdrop") || (VS ? "short" : "teal"),
    material: P.get("material") || "real", knife: P.get("knife") || "chef", size: P.get("size") || "m" },
  // quality: best (full shadows) or battery (the light phone profile: much faster without a GPU)
  settings: { sound: true, haptics: false, strength: "normal", quality: P.get("quality") || "best", lang: "en",
    cutSound: P.get("cutsound") || "auto", notes: P.get("notes") || (VS ? "off" : "piano"), saw: P.get("sawvoice") || "classic" }, stars: Array(9).fill(3),   // the Sound sheet
}));

// --- a made-up clock and a frame the size of the video
let vnow = 0, waiting = [];
performance.now = () => vnow;
// three.js runs its loop on requestAnimationFrame: hold those callbacks and run them per frame
window.requestAnimationFrame = cb => { waiting.push(cb); return waiting.length; };
window.cancelAnimationFrame = () => {};
Object.defineProperty(window, "innerWidth", { get: () => W / 2 });
Object.defineProperty(window, "innerHeight", { get: () => H / 2 });
Object.defineProperty(window, "devicePixelRatio", { get: () => 2 / TILES });   // tiled: the canvas is one tile

// --- tiles: the game's one render of a frame becomes TILES x TILES renders, each a part of the view at
// the canvas's full sharpness, copied into `shot` as it is made
let shot = null;
if (TILES > 1) {
  const THREE = await import("three");
  shot = document.createElement("canvas"); shot.width = W; shot.height = H;
  const sg = shot.getContext("2d");
  let wrapped = null;
  THREE.Scene.prototype.onBeforeRender = function (renderer) {   // the first render tells us the game's renderer
    if (wrapped || !renderer.domElement.closest?.("#stage")) return;
    wrapped = renderer;
    const draw = renderer.render;
    renderer.render = function (scene, cam) {
      if (renderer.getRenderTarget() || !cam.isPerspectiveCamera) return draw.call(this, scene, cam);   // reflections, shadows
      const el = renderer.domElement, cw = el.width, ch = el.height;
      const v = cam.view && cam.view.enabled ? { ...cam.view } : null;       // the game's own offset (the Looks sheet lifts the view)
      const full = v || { fullWidth: cw, fullHeight: ch, offsetX: 0, offsetY: 0, width: cw, height: ch };
      const kx = cw / full.width, ky = ch / full.height;
      for (let ty = 0; ty < TILES; ty++) for (let tx = 0; tx < TILES; tx++) {
        cam.setViewOffset(full.fullWidth * kx * TILES, full.fullHeight * ky * TILES,
          full.offsetX * kx * TILES + tx * cw, full.offsetY * ky * TILES + ty * ch, cw, ch);
        draw.call(this, scene, cam);
        sg.drawImage(el, 0, 0, cw, ch, Math.round(tx * W / TILES), Math.round(ty * H / TILES), Math.round(W / TILES), Math.round(H / TILES));
      }
      if (v) cam.setViewOffset(v.fullWidth, v.fullHeight, v.offsetX, v.offsetY, v.width, v.height); else cam.clearViewOffset();
    };
  };
}

// --- every sound is noted with its moment, and rendered afterwards
const S = await import("../src/sound.js");
const { store } = await import("../src/store.js");     // the game's own settings object
// every look a video would open is open for the recording (a locked one falls back to the default)
store.unlocked = [...(await import("../src/tasks.js")).VIDEO_UNLOCK];
const heard = [], play = {};
for (const k of Object.keys(S.sfx)) { play[k] = S.sfx[k]; S.sfx[k] = (...a) => heard.push({ k, a, t: vnow / 1000 }); }

if (VS) {                                              // the short's look: a pale teal, and no knife waiting in the shot
  const { BACKDROPS } = await import("../src/stage.js");
  BACKDROPS.short = { name: { en: "Short", fa: "شورت" }, sky: ["#5a7b80", "#6d8b90"], bg: "#6a888d", floor: "#86a3a8", ground: 0x6a888d, key: 0xfff1dc, rim: 0xe6fbff, light: false };
  if ((P.get("style") || "burst") === "burst") {
    const { KnifeRig } = await import("../src/knife.js");
    const update = KnifeRig.prototype.update;
    KnifeRig.prototype.update = function (dt) { update.call(this, dt); this.group.visible = !!this.anim; };
  }
}

say("starting the game…");
await import("../src/app.js");
await document.fonts.load("900 100px Poppins");
await document.fonts.load("700 100px Poppins");
if (VS) {                                              // the short's cut lines read at phone size: thicker than the game's
  const { fruitMaterials } = await import("../src/fruits.js");
  const mats = fruitMaterials(store.looks.fruit, store.looks.material === "glass", 0);
  for (const m of [mats.skin, mats.flesh]) m.userData.U.uLineW.value = 0.0011;
}

const $ = id => document.getElementById(id);
const gl = document.querySelector("#stage canvas");
const out = document.createElement("canvas"); out.width = W; out.height = H;
const g = out.getContext("2d");
const preview = document.createElement("canvas"); preview.id = "preview"; preview.width = W / 4; preview.height = H / 4;
document.body.appendChild(preview);

const post = (path, body) => fetch(path, { method: "POST", body }).then(r => r.json());
const HOOK = VS && P.get("edit") !== "loop" ? 2 * FPS : 0;  // the opening's frames, filled in when the last segment is done
const PART = P.get("part") || "only";                 // one take, or one segment of a take made in parts
const FIRST = PART === "only" || PART === "first", LAST = PART === "only" || PART === "last";
let fi = FIRST ? HOOK : 0, title = "", showCount = false, zoomFrom = -1;
let ring = null, ringOn = false;                       // the last segment's picture without titles, for the opening
const base = document.createElement("canvas"); base.width = W; base.height = H;
const b = base.getContext("2d");
const cutLabel = n => `${n} ${n === 1 ? "Cut" : "Cuts"}`;

// the short's captions: Poppins Bold 112 from y 150 with a soft shadow, as the Blender videos have them
function caption(lines) {
  const k = W / 1080;
  const px = lines.length > 1 ? 96 : 112;              // the three-line opening card a little smaller: it starts lower now
  g.font = `700 ${px * k}px Poppins, sans-serif`; g.textAlign = "center"; g.textBaseline = "alphabetic";
  g.shadowColor = "rgba(0,0,0,0.6)"; g.shadowBlur = 14 * k; g.shadowOffsetX = 3 * k; g.shadowOffsetY = 5 * k;
  let y = SAFE_TOP * k;
  for (const [text, color] of lines) {
    const m = g.measureText(text);
    g.fillStyle = color; g.fillText(text, W / 2, y + m.actualBoundingBoxAscent);
    y += m.actualBoundingBoxAscent + m.actualBoundingBoxDescent + px * k * 0.18;
  }
  g.shadowColor = "transparent"; g.shadowBlur = g.shadowOffsetX = g.shadowOffsetY = 0;
}

function overlay() {
  if (VS) { if (title) caption([[title, "#ffffff"]]); return; }
  const k = W / 1080;
  g.textAlign = "center"; g.textBaseline = "alphabetic";
  g.shadowColor = "rgba(0,0,0,0.5)"; g.shadowBlur = 24 * k; g.shadowOffsetY = 4 * k;
  if (title) {
    g.font = `900 ${120 * k}px Poppins, sans-serif`; g.fillStyle = "#fdfaf4";
    g.fillText(title, W / 2, (SAFE_TOP + 88) * k);     // its top on the safe line: clear of the apps' own bar
  }
  const sub = $("chopSub").textContent, n = sub.replace(/[^\d]/g, "");
  if (showCount && n && n !== "1") {                   // the count: one line under the title, clear of the board and its mark
    const num = Number(n).toLocaleString("en-US"), y = (SAFE_TOP + 200) * k;
    g.font = `900 ${100 * k}px Poppins, sans-serif`; const wn = g.measureText(num).width;
    g.font = `800 ${54 * k}px Poppins, sans-serif`; const wl = g.measureText("PIECES").width, gap = 16 * k, x0 = (W - wn - gap - wl) / 2;
    g.textAlign = "left";
    g.font = `900 ${100 * k}px Poppins, sans-serif`; g.fillStyle = "#fdfaf4"; g.fillText(num, x0, y);
    g.font = `800 ${54 * k}px Poppins, sans-serif`; g.fillStyle = "#ff4136"; g.fillText("PIECES", x0 + wn + gap, y);
    g.textAlign = "center";
  }
  g.shadowColor = "transparent";
}

async function frame() {
  if (gl.getContext("webgl2")?.isContextLost()) {      // the picture is gone (a browser short of memory): every frame would be black
    window.__recDone = { error: "WebGL context lost: the browser probably ran out of memory" };
    throw new Error(window.__recDone.error);
  }
  const zoom = zoomFrom < 0 ? 1 : 1 + 1.6 * Math.max(0, 1 - (fi - zoomFrom) / (0.45 * FPS)) ** 3;
  for (let j = 0; j < BLUR; j++) {                      // several moments of each frame, averaged: motion blur
    vnow += 1000 / FPS / BLUR;
    const run = waiting; waiting = [];
    for (const cb of run) cb(vnow);
    b.globalAlpha = 1 / (j + 1);                        // right after the render, before the buffer clears
    const src = shot || gl, cw = src.width, ch = src.height;   // the game's canvas (half the video's size at light quality), or the tiles
    const sw = cw / zoom, sh = ch / zoom;               // zooming on the fruit, 38 % down the frame
    b.drawImage(src, (cw - sw) / 2, (ch * 0.38) * (1 - 1 / zoom), sw, sh, 0, 0, W, H);
  }
  g.drawImage(base, 0, 0);
  if (ringOn) {
    ring.push({ t: vnow / 1000, jpg: await new Promise(r => base.toBlob(r, "image/jpeg", 0.97)) });
    if (ring.length > HOOK) ring.shift();               // keeps the last 2 s of the chopping
  }
  overlay();
  preview.getContext("2d").drawImage(out, 0, 0, preview.width, preview.height);
  if (COVER) {                                         // only the last picture is kept
    fi++; window.__recBeat = fi;
    if (fi % 20 === 0) await new Promise(r => setTimeout(r));
    return;
  }
  const jpg = await new Promise(r => out.toBlob(r, "image/jpeg", 0.92));
  await fetch(`/rec/frame?i=${fi++}`, { method: "POST", body: jpg });
  window.__recBeat = fi;                               // a heartbeat: a slow frame (a burst on one CPU) is not a stuck page
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

if (!COVER) await post(`/rec/start?name=${encodeURIComponent(NAME)}${P.get("append") ? "&append=1" : ""}`);
store.looks.cuts = COVER ? CUTS[CUTS.length - 1] : CUTS[0];   // a cover: the last count's pile                            // the first round starts with its count (a saved one stops at 100)
document.querySelector('[data-mode="chop"]').click();
const started = Date.now();                            // the real clock, for the report
for (const [i, n] of (COVER ? CUTS.slice(-1) : CUTS).entries()) {
  // the first segment has its count already; opening the Looks sheet draws every fruit's thumbnail (a second
  // WebGL picture and 17 fruits' shaders), memory a small server does not have
  if (i) setCuts(n);                                   // also starts a fresh fruit
  title = VS ? cutLabel(n) : `${n} Cuts`; showCount = false;
  zoomFrom = VS && i === 0 && FIRST ? fi : -1;
  say(`${NAME}\n${title}: getting ready`);
  await frames(VS ? (i === 0 ? 0.5 : 0.15) : 0.8);
  const last = COVER || i === CUTS.length - 1;
  if (HOOK && last && LAST) { ring = []; ringOn = true; }
  press("pointerdown");
  let guard = 0;
  const made = () => Number($("chopBig").textContent.split("/")[0].replace(/[^\d]/g, ""));
  while (made() < n) {
    await frame();
    if (LOOP && last && !seam && made() >= Math.ceil(n / 2)) seam = fi;
    if (++guard > FPS * 60) break;                    // never more than a minute of chopping
    if (guard % 10 === 0) say(`${NAME}\n${title}: ${$("chopBig").textContent}  (frame ${fi})`);
  }
  if (LOOP && last && !seam) seam = fi;
  if (store.looks.style === "free") press("pointerup");   // Free style chops while held: let go at n
  showCount = true;
  if (ringOn && ring.length >= HOOK) ringOn = false;  // a short chop: the opening goes on into the fall
  // the fall and the count (a cover waits until the last piece lies still: that takes a real pile 10 s)
  for (let f = 0; f < Math.round((COVER ? +(P.get("settle") || 12) : VS ? 1.8 : 3.2) * FPS); f++) {
    await frame();
    if (ringOn && ring.length >= HOOK) ringOn = false;
  }
  while (ringOn) {                                    // a very short take: the opening still needs all its frames
    await frame();
    if (ring.length >= HOOK) ringOn = false;
  }
  press("pointerup");
}
if (COVER) {
  const saved = await cover();
  window.__recDone = { path: saved[0], stills: saved };
  say(`cover: ${saved.join("\n")}\n(${((Date.now() - started) / 1000).toFixed(0)} s)`);
  await new Promise(() => {});                         // nothing more: no sound, no video
}
if (SAW && !LOOP && P.get("tail") !== "0") await frames(VS ? 1.6 : 0.3);   // the saw's motor idles 2.2 s after its last cut, then runs down: all of it in the clip
if (!LOOP && !VS && P.get("tail") !== "0") { title = ""; await frames(0.4); }  // a loop ends on the pile, like every segment

// the opening: the end of the last segment's frenzy, its sound first, with the VS card
let hookAt = 0;
if (HOOK && LAST) {
  say(`${NAME}
the opening…`);
  hookAt = ring[0].t - 1 / FPS;
  const SERIES = (P.get("series") || CUTS.join(",")).split(",").map(Number);   // a part knows only its own count
  const first = cutLabel(SERIES[0]), top = cutLabel(SERIES[SERIES.length - 1]);
  for (const [k, f] of ring.entries()) {
    const bmp = await createImageBitmap(f.jpg);
    g.drawImage(bmp, 0, 0); bmp.close();
    caption([[first, "#ffffff"], ["VS", "#ffffff"], k < HOOK / 2 ? ["...", "#ffffff"] : [top, "#e82828"]]);
    const jpg = await new Promise(r => out.toBlob(r, "image/jpeg", 0.92));
    await fetch(`/rec/frame?i=${k}&abs=1`, { method: "POST", body: jpg });   // the video's first frames, whatever part this is
  }
}

say(`${NAME}\nrendering the sound…`);
const dur = fi / FPS, SR = 48000;
const oc = new OfflineAudioContext(2, Math.ceil(SR * dur), SR);
S.useOffline(oc);
const hookS = HOOK / FPS, lead = FIRST ? hookS : 0;   // the first part's picture starts after the opening
const inHook = e => HOOK && LAST && e.t >= hookAt && e.t < hookAt + hookS;
for (const e of heard) {
  if (VS && (e.k === "tick" || e.k === "win")) continue;  // the game's menu and new-best sounds
  if (inHook(e) && FIRST) { S.startAt(e.t - hookAt); play[e.k](...e.a); }
  S.startAt(e.t + lead); play[e.k](...e.a);
}
for (let t = 1; t < dur; t++) {                        // the sound's progress, a second at a time: also a heartbeat
  oc.suspend(t).then(() => { window.__recBeat = `sound ${t}`; say(`${NAME}\nrendering the sound… ${t} / ${Math.ceil(dur)} s`); oc.resume(); });
}
const buf = await oc.startRendering();
if (HOOK && LAST && !FIRST) {                          // made in parts: the opening's sound goes to the start of the take
  const hc = new OfflineAudioContext(2, Math.ceil(SR * hookS), SR);
  S.useOffline(hc);
  for (const e of heard) if (inHook(e) && !(e.k === "tick" || e.k === "win")) { S.startAt(e.t - hookAt); play[e.k](...e.a); }
  await post("/rec/audio?hook=1", wav(await hc.startRendering()));
}
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

// cover=1: the picture for a post's cover. The pile lies on the board, the cutter is held up large
// before the camera, and the count is written on its blade (a saw: on its bar), lying in the blade's
// own plane: <name>-cover.jpg. The letters are dark on bright steel and light on dark (cover=etched or
// cover=white forces one). Other options: at (how far down, 0.40), wide (share of the width), tilt, settle (seconds).
async function cover() {
  const THREE = await import("three");
  const { stage, game } = window.CUT_GAME, rig = game.slots[0].knife, cam = stage.cameras[0], kn = rig.group;
  const kind = store.looks.knife, saw = kind === "saw";
  const LEN = saw ? [-0.168, 0.22] : [-0.108, 0.225];   // the whole tool, tip to butt (the rig's frame: tip at -x, edge along y = 0)
  const BOX = saw ? [-0.150, -0.006, 0.0085, 0.0345]     // the flat of the blade the words may take: x0, x1, y0, y1
    : kind === "cleaver" ? [-0.056, 0.094, 0.036, 0.0735] : [-0.048, 0.094, 0.0065, 0.043];   // a cleaver: the forged black above its ground edge
  const mid = new THREE.Vector3((LEN[0] + LEN[1]) / 2, saw ? 0.034 : 0.024, 0);
  rig.stop(); rig.anim = null; rig.away = null; rig.update = () => {};   // it is ours now: the game no longer moves it
  kn.visible = true;
  cam.updateMatrixWorld();
  // flat to the camera, then turned a little: the tip down towards the pile, the handle nearer
  const q = cam.quaternion.clone().multiply(new THREE.Quaternion().setFromEuler(new THREE.Euler(-0.10, 0.20, +(P.get("tilt") || 0.17))));
  const at = +(P.get("at") || 0.40);                    // how far down the picture its middle is
  const dir = new THREE.Vector3(0, 1 - 2 * at, 0.5).unproject(cam).sub(cam.position).normalize();
  const where = cam.position.clone().addScaledVector(dir, cam.position.distanceTo(rig.home) * 0.82);
  const place = s => {
    kn.quaternion.copy(q); kn.scale.setScalar(s);
    kn.position.copy(where).sub(mid.clone().multiplyScalar(s).applyQuaternion(q)); kn.updateMatrixWorld(true);
  };
  const px = (x, y) => { const v = new THREE.Vector3(x, y, 0.0012).applyMatrix4(kn.matrixWorld).project(cam); return [(v.x + 1) / 2 * W, (1 - v.y) / 2 * H]; };
  place(1);
  const a = px(LEN[0], mid.y), b = px(LEN[1], mid.y);
  const s = +(P.get("wide") || (saw ? 0.93 : 0.88)) * W / Math.hypot(b[0] - a[0], b[1] - a[1]);   // as wide as the picture allows (a saw's bar is only half of it)
  place(s);
  const a2 = px(LEN[0], mid.y), b2 = px(LEN[1], mid.y);  // turned, its far end looks shorter: put what is seen in the middle
  where.addScaledVector(new THREE.Vector3(1, 0, 0).applyQuaternion(cam.quaternion), (W / 2 - (a2[0] + b2[0]) / 2) * (LEN[1] - LEN[0]) * s / Math.hypot(b2[0] - a2[0], b2[1] - a2[1]));
  place(s);
  showCount = false;
  await frames(0.2);                                    // the shadows and the light follow

  const n = Number($("chopSub").textContent.replace(/[^\d]/g, "")).toLocaleString("en-US");
  const U = 10000;                                      // lettering units to a metre
  const O = px(BOX[0], BOX[2]), X = px(BOX[1], BOX[2]), Y = px(BOX[0], BOX[3]);
  const bw = (BOX[1] - BOX[0]) * U, bh = (BOX[3] - BOX[2]) * U;
  const ex = [(X[0] - O[0]) / bw, (X[1] - O[1]) / bw], ey = [(Y[0] - O[0]) / bh, (Y[1] - O[1]) / bh];
  g.setTransform(1, 0, 0, 1, 0, 0);
  g.drawImage(shot || gl, 0, 0, W, H); overlay();   // the tiles' picture when the frame is drawn in tiles
  // what the flat looks like where the words go: its colours along the blade (a third of the way up, clear of a saw's line of light)
  const tone = [...Array(9)].map((_, i) => {
    const [x, y] = px(BOX[0] + (BOX[1] - BOX[0]) * (i + 0.5) / 9, BOX[2] + (BOX[3] - BOX[2]) * 0.3);
    return g.getImageData(Math.round(x), Math.round(y), 1, 1).data;
  });
  const lum = tone.reduce((s, d) => s + 0.3 * d[0] + 0.6 * d[1] + 0.1 * d[2], 0) / tone.length;
  const how = COVER === "white" || COVER === "etched" ? COVER : lum < 105 ? "white" : "etched";   // dark steel (a cleaver's forged top) takes light letters

  g.setTransform(ex[0], ex[1], -ey[0], -ey[1], O[0], O[1]);   // x along the blade, y down from the box's lower edge
  const fonts = F => [`900 ${F}px Poppins, sans-serif`, `800 ${F * 0.5}px Poppins, sans-serif`];
  const width = F => { const f = fonts(F); g.font = f[0]; const wn = g.measureText(n).width; g.font = f[1]; return [wn, F * 0.16, g.measureText("PIECES").width]; };
  let F = bh * 0.80 / 0.70;                             // the digits' height fills four fifths of the flat
  F *= Math.min(1, bw * 0.95 / width(F).reduce((s, v) => s + v));
  const [wn, gap] = width(F), all = width(F).reduce((s, v) => s + v), f = fonts(F);
  const x0 = (bw - all) / 2, y = -(bh - F * 0.70) / 2;
  if (saw) {                                            // the bar's line of light stops short of the words: steel over it, in the bar's own tones
    const pad = F * 0.22, G = g.createLinearGradient(0, 0, bw, 0);
    tone.forEach((d, i) => G.addColorStop((i + 0.5) / 9, `rgb(${d[0]},${d[1]},${d[2]})`));
    g.fillStyle = G; g.beginPath();
    g.roundRect(x0 - pad, -(0.0245 - BOX[2]) * U, all + pad * 2, (0.0245 - 0.0187) * U, 14); g.fill();
  }
  const put = (dx, dy, cn, cl) => {
    g.textAlign = "left"; g.textBaseline = "alphabetic";
    g.font = f[0]; g.fillStyle = cn; g.fillText(n, x0 + dx, y + dy);
    g.font = f[1]; g.fillStyle = cl; g.fillText("PIECES", x0 + wn + gap + dx, y + dy);
  };
  if (how === "white") {                                // light letters, a dark rim under them
    put(F * 0.012, F * 0.02, "rgba(0,0,0,0.6)", "rgba(0,0,0,0.6)");
    put(0, 0, "#f6f1e6", "#ff5446");
  } else {                                              // etched into the steel: dark, with the light catching its lower rim
    put(F * 0.012, F * 0.016, "rgba(255,255,255,0.55)", "rgba(255,255,255,0.45)");
    put(0, 0, "rgba(18,26,28,0.9)", "#d3241b");
  }
  g.setTransform(1, 0, 0, 1, 0, 0);
  preview.getContext("2d").drawImage(out, 0, 0, preview.width, preview.height);
  const jpg = await new Promise(r => out.toBlob(r, "image/jpeg", 0.95));
  const saved = [(await post(`/rec/still?name=${encodeURIComponent(`${NAME}-cover`)}`, jpg)).path];
  return saved;
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
