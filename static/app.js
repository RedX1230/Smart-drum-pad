/* Smart Drum Pad — rhythm-training front-end.
   Drives the single-drum practice loop from live detector data:
     /config       pad geometry + zone ratios + devices (read-only)
     /metrics      live stick positions, recent strikes, struck BPM
     /set_pattern  register the target L/R sequence with the evaluator
     /score        backend L/R match (surfaced in analysis)
   Timing is paced client-side against a chosen tempo; every judged strike
   comes from the real detector, never simulated. */

const $  = (s) => document.querySelector(s);
const $$ = (s) => Array.from(document.querySelectorAll(s));

const LEFT = '#4b3826', RIGHT = '#a9853f';      // walnut ink / brass
const WAL_RGB = '75,56,38', BRASS_RGB = '169,133,63';
const rgbOf = (h) => (h === 'L' ? WAL_RGB : BRASS_RGB);
const handColor = (h) => (h === 'L' ? LEFT : RIGHT);
const INK = '#2c2419', INK_SOFT = 'rgba(44,36,25,0.55)', RULE = 'rgba(44,36,25,0.14)';
const POINTS = { perfect: 100, good: 70, okay: 40, bad: 0 };
const VERDICT_COL = { perfect: '#7d5f28', good: '#5b5040', okay: '#8a7c64', bad: '#7c3a34', stray: '#7c3a34' };
const LEADIN = 3.0;

/* ---- config / geometry ------------------------------------------------ */
const cfg = {
  camera:      { width: 640, height: 480 },
  calibration: { center_x: 320, center_y: 240, radius: 180, rim_width: 12 },
  zones:       { inner: 0.2, middle: 0.5, outer: 0.8 },
  audio:       {},
};
async function loadConfig() {
  try {
    const d = await (await fetch('/config')).json();
    Object.assign(cfg.camera, d.camera || {});
    Object.assign(cfg.calibration, d.calibration || {});
    Object.assign(cfg.zones, d.zones || {});
    Object.assign(cfg.audio, d.audio || {});
  } catch (_) {}
  renderCalParams();
}
const geom = () => cfg.calibration;
function toNorm(x, y) { const g = geom(); return { nx: (x - g.center_x) / g.radius, ny: (y - g.center_y) / g.radius }; }
function zoneOf(nx, ny) {
  const r = Math.hypot(nx, ny), z = cfg.zones, rimOut = 1 + (geom().rim_width / geom().radius);
  if (r > rimOut) return 'off';
  if (r > 1) return 'rim';
  if (r <= z.inner) return 'centre';
  if (r <= z.middle) return 'inner';
  if (r <= z.outer) return 'mid';
  return 'outer';
}

/* ---- canvas helpers --------------------------------------------------- */
function reg(sel) { const cv = $(sel); return { cv, ctx: cv.getContext('2d'), w: 0, h: 0 }; }
const LANE = reg('#lane'), DRUM = reg('#drum'), CAL = reg('#calDrum'), ATIM = reg('#anaTiming'), ADRUM = reg('#anaDrum');
function fit(c) {
  const r = c.cv.getBoundingClientRect();
  const dpr = Math.min(window.devicePixelRatio || 1, 2);
  c.w = r.width; c.h = r.height;
  c.cv.width = Math.max(1, r.width * dpr); c.cv.height = Math.max(1, r.height * dpr);
  c.ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
}
function rr(ctx, x, y, w, h, r) {
  ctx.beginPath();
  ctx.moveTo(x + r, y); ctx.arcTo(x + w, y, x + w, y + h, r); ctx.arcTo(x + w, y + h, x, y + h, r);
  ctx.arcTo(x, y + h, x, y, r); ctx.arcTo(x, y, x + w, y, r); ctx.closePath();
}

/* a small baked grain tile — warm dark speckle for paper / drumhead coating */
const grainTile = (() => {
  const c = document.createElement('canvas'); c.width = c.height = 120;
  const g = c.getContext('2d'), im = g.createImageData(120, 120);
  for (let i = 0; i < im.data.length; i += 4) {
    const n = Math.random();
    im.data[i] = 60; im.data[i + 1] = 44; im.data[i + 2] = 24;
    im.data[i + 3] = n < 0.55 ? 0 : Math.floor((n - 0.55) * 90);
  }
  g.putImageData(im, 0, 0); return c;
})();
const _pat = new WeakMap();
function grainPattern(ctx) {
  let p = _pat.get(ctx); if (!p) { p = ctx.createPattern(grainTile, 'repeat'); _pat.set(ctx, p); }
  return p;
}
function grainFill(ctx, x, y, w, h, alpha) {
  ctx.save(); ctx.globalAlpha = alpha; ctx.fillStyle = grainPattern(ctx); ctx.fillRect(x, y, w, h); ctx.restore();
}

/* ---- app / view state ------------------------------------------------- */
let view = 'play';
function setView(v) {
  view = v;
  document.body.dataset.view = v;
  $$('#viewnav button').forEach((b) => b.classList.toggle('on', b.dataset.goto === v));
  $('.view-analysis').hidden = v !== 'analysis';
  $('.view-history').hidden = v !== 'history';
  $('.view-calibrate').hidden = v !== 'calibrate';
  layout();
  if (v === 'analysis') renderAnalysis();
  if (v === 'history') renderHistory();
}
function layout() {
  if (view === 'play') { fit(LANE); fit(DRUM); }
  if (view === 'calibrate') fit(CAL);
  if (view === 'analysis') { fit(ATIM); fit(ADRUM); }
}
window.addEventListener('resize', layout);
$('#viewnav').addEventListener('click', (e) => { const b = e.target.closest('button'); if (b) setView(b.dataset.goto); });

/* ---- pattern builder + tempo ----------------------------------------- */
let pattern = ['L', 'R', 'L', 'R'];
let bpm = 90;
const PRESETS = { LR: 'Single stroke', LLRR: 'Double stroke', LRRL: 'Paradiddle', LLRLLR: 'Triplet feel' };
function minUnit(arr) {
  const n = arr.length;
  for (let len = 1; len <= n; len++) {
    if (n % len) continue;
    if (arr.every((v, i) => v === arr[i % len])) return arr.slice(0, len).join('');
  }
  return arr.join('');
}
function patternName() {
  if (!pattern.length) return 'No phrase set';
  return PRESETS[minUnit(pattern)] || 'Custom phrase';
}
function drawSeq() {
  $('#seqStrip').innerHTML = pattern.map((h) => `<span class="gem ${h}">${h}</span>`).join('');
  renderNow();
  savePrefs();
}
function renderNow() {
  $('#nowSeq').innerHTML = pattern.length
    ? pattern.map((h) => `<span class="gem ${h}">${h}</span>`).join('')
    : '<span class="now-meta">—</span>';
  $('#nowMeta').textContent = `${patternName()} · ${bpm} bpm`;
}

/* remember the player's setup between visits */
function loadPrefs() {
  try {
    const p = JSON.parse(localStorage.getItem('sdp_prefs') || '{}');
    if (Array.isArray(p.pattern) && p.pattern.length && p.pattern.every((x) => x === 'L' || x === 'R')) pattern = p.pattern;
    if (typeof p.bpm === 'number') bpm = Math.max(30, Math.min(240, p.bpm));
    if (typeof p.loop === 'boolean') $('#loopChk').checked = p.loop;
    if (typeof p.metro === 'boolean') $('#metroChk').checked = p.metro;
  } catch (_) {}
}
function savePrefs() {
  try {
    localStorage.setItem('sdp_prefs', JSON.stringify({
      pattern, bpm, loop: $('#loopChk').checked, metro: $('#metroChk').checked,
    }));
  } catch (_) {}
}
$('.handpad').addEventListener('click', (e) => {
  const b = e.target.closest('button'); if (!b) return;
  if (b.dataset.append) pattern.push(b.dataset.append);
  else if (b.dataset.seq === 'back') pattern.pop();
  else if (b.dataset.seq === 'clear') pattern = [];
  drawSeq();
});
$('.presets').addEventListener('click', (e) => {
  const b = e.target.closest('button'); if (!b) return;
  pattern = b.dataset.preset.split(''); drawSeq();
});
$('.tempo').addEventListener('click', (e) => {
  const b = e.target.closest('button'); if (!b) return;
  bpm = Math.max(30, Math.min(240, bpm + parseInt(b.dataset.bpm, 10)));
  $('#bpmVal').textContent = bpm; renderNow(); savePrefs();
});
$('#loopChk').addEventListener('change', savePrefs);

/* ---- session model ---------------------------------------------------- */
const session = {
  running: false, start: 0, beat: 0.66, loop: true,
  notes: [], nextIdx: 0, nextTime: LEADIN, cyclesDone: 0,
  score: 0, combo: 0, maxCombo: 0,
  counters: { perfect: 0, good: 0, okay: 0, bad: 0 },
  events: [],   // {kind:'hit'|'miss'|'extra', ...}
  ripples: [],  // drum feedback (also live outside sessions)
};
function windows() {
  const b = session.beat;
  return { p: Math.min(0.05, b * 0.12), g: Math.min(0.11, b * 0.25), o: Math.min(0.2, b * 0.42) };
}
function extendNotes(t) {
  const need = t + 3.2;
  const cap = session.loop ? Infinity : 1;
  while (session.cyclesDone < cap && (session.notes.length === 0 || session.notes[session.notes.length - 1].time < need)) {
    if (pattern.length === 0) break;
    for (let i = 0; i < pattern.length; i++) {
      session.notes.push({ idx: session.nextIdx++, time: session.nextTime + i * session.beat, hand: pattern[i], judged: false, missed: false, result: null });
    }
    session.nextTime += pattern.length * session.beat;
    session.cyclesDone++;
  }
}
async function startSession() {
  if (pattern.length === 0) { flash('stray', 'add a pattern first'); return; }
  try { await fetch('/set_pattern', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ pattern: pattern.join('') }) }); } catch (_) {}
  Object.assign(session, {
    running: true, start: performance.now(), beat: 60 / bpm, loop: $('#loopChk').checked,
    notes: [], nextIdx: 0, nextTime: LEADIN, cyclesDone: 0,
    score: 0, combo: 0, maxCombo: 0, counters: { perfect: 0, good: 0, okay: 0, bad: 0 }, events: [],
  });
  extendNotes(0);
  const t = $('#transport'); t.textContent = 'Stop practice'; t.classList.add('live');
  if ($('#metroChk').checked) startMetro();
  updateReadouts();
}
function stopSession() {
  session.running = false;
  session.durationMs = performance.now() - session.start;
  stopMetro();
  const t = $('#transport'); t.textContent = 'Begin practice'; t.classList.remove('live');
  if (session.events.length) { saveSession(); setView('analysis'); }
}
$('#transport').addEventListener('click', () => (session.running ? stopSession() : startSession()));
$('#metroChk').addEventListener('change', () => {
  savePrefs();
  if (!session.running) return;
  $('#metroChk').checked ? startMetro() : stopMetro();
});

/* ---- strike ingestion (live detector) --------------------------------- */
const seen = new Set();
let liveTips = { L: null, R: null };
async function poll() {
  try {
    const d = await (await fetch('/metrics')).json();
    $('#link').classList.add('on');
    liveTips = { L: d.left_pos || null, R: d.right_pos || null };
    if (typeof d.bpm === 'number' && d.bpm > 0) $('#roBpm').textContent = Math.round(d.bpm);
    (d.recent_strikes || []).forEach((s) => {
      const sig = `${s.timestamp}|${s.x}|${s.y}|${s.stick}`;
      if (seen.has(sig)) return;
      seen.add(sig); if (seen.size > 400) seen.clear();
      handleStrike(s);
    });
  } catch (_) { $('#link').classList.remove('on'); }
}
function handleStrike(s) {
  if (!s || s.x == null || s.y == null) return;
  const hand = s.stick === 'R' ? 'R' : 'L';
  const { nx, ny } = toNorm(s.x, s.y);
  const zone = zoneOf(nx, ny);
  const type = s.label || 'strike';
  session.ripples.push({ nx, ny, hand, born: performance.now() });
  showHud(hand, type, zone);
  if (session.running) judge({ hand, nx, ny, zone, type });
}

/* keyboard practice — play without the camera/mic rig (F = left, J = right) */
function localStrike(hand) {
  const nx = (Math.random() - 0.5) * 0.5, ny = (Math.random() - 0.5) * 0.5;
  const zone = zoneOf(nx, ny);
  session.ripples.push({ nx, ny, hand, born: performance.now() });
  showHud(hand, 'tap', zone);
  if (session.running) judge({ hand, nx, ny, zone, type: 'normal' });
}
window.addEventListener('keydown', (e) => {
  if (e.repeat || view !== 'play') return;
  if (e.target && /^(INPUT|TEXTAREA|SELECT)$/.test(e.target.tagName)) return;
  let hand = null;
  const k = e.key.toLowerCase();
  if (k === 'f' || e.key === 'ArrowLeft') hand = 'L';
  else if (k === 'j' || e.key === 'ArrowRight') hand = 'R';
  else if (k === ' ') { e.preventDefault(); (session.running ? stopSession : startSession)(); return; }
  if (!hand) return;
  e.preventDefault();
  localStrike(hand);
});
function judge(st) {
  const t = (performance.now() - session.start) / 1000;
  const w = windows();
  let best = null, bd = 1e9;
  for (const n of session.notes) {
    if (n.judged || n.missed) continue;
    const d = Math.abs(n.time - t);
    if (d < bd) { bd = d; best = n; }
  }
  if (best && bd <= w.o) {
    const delta = t - best.time;
    const correct = st.hand === best.hand;
    const cls = bd <= w.p ? 'perfect' : bd <= w.g ? 'good' : 'okay';
    best.judged = true; best.result = { cls, delta, correct, st };
    session.events.push({ kind: 'hit', idx: best.idx, target: best.hand, actual: st.hand, delta, correct, cls, nx: st.nx, ny: st.ny, zone: st.zone, type: st.type });
    if (correct) { session.score += POINTS[cls]; session.counters[cls]++; session.combo++; session.maxCombo = Math.max(session.maxCombo, session.combo); flash(cls, cls); }
    else { session.counters.bad++; session.combo = 0; flash('bad', 'other hand'); }
  } else {
    session.events.push({ kind: 'extra', actual: st.hand, nx: st.nx, ny: st.ny, zone: st.zone, type: st.type });
    session.counters.bad++; session.combo = 0; flash('stray', 'off pattern');
  }
  updateReadouts();
}
function sweepMisses(t) {
  const w = windows();
  for (const n of session.notes) {
    if (!n.judged && !n.missed && n.time < t - w.o) {
      n.missed = true;
      session.events.push({ kind: 'miss', idx: n.idx, target: n.hand });
      session.counters.bad++; session.combo = 0; updateReadouts();
    }
  }
}
function updateReadouts() {
  $('#roScore').textContent = session.score;
  $('#roCombo').textContent = session.combo;
  const c = session.counters, good = c.perfect + c.good + c.okay, tot = good + c.bad;
  $('#roAcc').textContent = tot ? Math.round((good / tot) * 100) + '%' : '—';
}
function showHud(hand, type, zone) {
  const el = $('#hudHand');
  el.textContent = hand === 'L' ? 'left' : 'right';
  el.style.color = handColor(hand);
  $('#hudType').textContent = type;
  $('#hudZone').textContent = zone === 'off' ? '' : zone;
}
function flash(kind, text) {
  const v = $('#verdict'); v.textContent = text; v.style.color = VERDICT_COL[kind] || '#fff';
  v.classList.remove('show'); void v.offsetWidth; v.classList.add('show');
}

/* ---- render: lane (a ruled practice sheet the pattern descends) ------- */
function drawLane() {
  const { ctx, w, h } = LANE; if (!w) return;
  ctx.clearRect(0, 0, w, h);
  const t = session.running ? (performance.now() - session.start) / 1000 : 0;
  if (session.running) { extendNotes(t); sweepMisses(t); }
  const hitY = h - 2, travel = 2.4, pps = h / travel;   // strike line at the very foot
  const cxc = w / 2, off = Math.min(w * 0.2, 92);

  // sheet-music surface: a lighter leaf than the page, gently lit, with grain
  const sheet = ctx.createLinearGradient(0, 0, 0, h);
  sheet.addColorStop(0, '#f2ecd8'); sheet.addColorStop(1, '#ebe2cb');
  ctx.fillStyle = sheet; ctx.fillRect(0, 0, w, h);
  ctx.save();
  const vig = ctx.createRadialGradient(w / 2, h * 0.4, h * 0.2, w / 2, h * 0.5, h * 0.9);
  vig.addColorStop(0, 'rgba(0,0,0,0)'); vig.addColorStop(1, 'rgba(90,66,30,0.06)');
  ctx.fillStyle = vig; ctx.fillRect(0, 0, w, h);
  ctx.restore();
  grainFill(ctx, 0, 0, w, h, 0.34);
  // shadow where the masthead paper overlaps the sheet
  const topSh = ctx.createLinearGradient(0, 0, 0, 14);
  topSh.addColorStop(0, 'rgba(44,30,14,0.16)'); topSh.addColorStop(1, 'rgba(44,30,14,0)');
  ctx.fillStyle = topSh; ctx.fillRect(0, 0, w, 14);

  // scrolling beat rules — rhythm read through motion, not labels
  ctx.lineWidth = 1;
  for (let k = -1; k < travel + 2; k++) {
    const bt = Math.ceil(t) + k;
    const yy = hitY - (bt - t) * pps;
    if (yy < -2 || yy > h) continue;
    const bar = bt % 4 === 0;
    ctx.strokeStyle = bar ? 'rgba(44,36,25,0.16)' : 'rgba(44,36,25,0.07)';
    ctx.beginPath(); ctx.moveTo(0, yy); ctx.lineTo(w, yy); ctx.stroke();
  }
  // two faint hand rails
  ctx.strokeStyle = 'rgba(44,36,25,0.08)';
  [cxc - off, cxc + off].forEach((x) => { ctx.beginPath(); ctx.moveTo(x, 0); ctx.lineTo(x, hitY); ctx.stroke(); });

  // brass strike line
  ctx.strokeStyle = 'rgba(125,95,40,0.85)'; ctx.lineWidth = 2;
  ctx.beginPath(); ctx.moveTo(0, hitY - 1); ctx.lineTo(w, hitY - 1); ctx.stroke();
  [cxc - off, cxc + off].forEach((x) => {
    ctx.strokeStyle = 'rgba(125,95,40,0.5)'; ctx.lineWidth = 1.5;
    ctx.beginPath(); ctx.arc(x, hitY - 1, 15, Math.PI, 0); ctx.stroke();
  });

  // notes — small warm discs; hand read by tone + rail, no shouting letters
  for (const n of session.notes) {
    const dt = n.time - t;
    if (dt > travel + 0.3 || dt < -0.5) continue;
    const y = hitY - dt * pps;
    const x = n.hand === 'L' ? cxc - off : cxc + off;
    const rgb = rgbOf(n.hand);
    let a = 1, r = 11;
    if (n.judged && n.result) { const age = t - n.time; a = Math.max(0, 1 - age * 2.2); r = 11 + Math.min(7, Math.max(0, age) * 26); }
    if (n.missed) { a = 0.4; }
    ctx.globalAlpha = a;
    if (n.missed) {
      ctx.strokeStyle = `rgba(${rgb},0.7)`; ctx.lineWidth = 1.5;
      ctx.beginPath(); ctx.arc(x, y, 10, 0, Math.PI * 2); ctx.stroke();
    } else {
      ctx.fillStyle = `rgb(${rgb})`;
      ctx.beginPath(); ctx.arc(x, y, r, 0, Math.PI * 2); ctx.fill();
      ctx.strokeStyle = n.hand === 'L' ? 'rgba(28,20,10,0.5)' : 'rgba(90,66,20,0.5)';
      ctx.lineWidth = 1; ctx.beginPath(); ctx.arc(x, y, r, 0, Math.PI * 2); ctx.stroke();
      // faint inner mark for the brass (right) so tone difference is unmistakable up close
      if (n.hand === 'R') { ctx.fillStyle = 'rgba(233,223,202,0.5)'; ctx.beginPath(); ctx.arc(x, y, r * 0.32, 0, Math.PI * 2); ctx.fill(); }
    }
    ctx.globalAlpha = 1;
  }

  // count-in over the lead-in bars, before the first note lands
  if (session.running) {
    const remain = LEADIN - t;
    if (remain > 0) {
      const n = Math.ceil(remain);
      ctx.save();
      ctx.globalAlpha = Math.max(0.12, remain - (n - 1));
      ctx.fillStyle = 'rgba(44,26,10,0.55)';
      ctx.font = '600 88px Georgia, "Times New Roman", serif';
      ctx.textAlign = 'center'; ctx.textBaseline = 'middle';
      ctx.fillText(String(n), w / 2, h * 0.4);
      ctx.restore();
    }
  }
}

/* ---- render: the drum (the instrument — warm, matte, tactile) --------- */
function blot(ctx, x, y, r, rgb, a) {
  const g = ctx.createRadialGradient(x, y, 0, x, y, r);
  g.addColorStop(0, `rgba(${rgb},${a})`); g.addColorStop(0.55, `rgba(${rgb},${a * 0.45})`); g.addColorStop(1, `rgba(${rgb},0)`);
  ctx.fillStyle = g; ctx.beginPath(); ctx.arc(x, y, r, 0, Math.PI * 2); ctx.fill();
}
function drawDrum(target, big) {
  const { ctx, w, h } = target; if (!w) return;
  ctx.clearRect(0, 0, w, h);
  const cx = w / 2, cy = h * (big ? 0.48 : 0.5), R = big ? Math.min(w * 0.42, h * 0.44) : Math.min(w, h) * 0.44;
  const z = cfg.zones, now = performance.now();
  const rimR = R * (1 + geom().rim_width / geom().radius) + (big ? 14 : 8);

  // wooden shell / rim with soft physical depth
  ctx.save();
  ctx.shadowColor = 'rgba(40,28,14,0.28)'; ctx.shadowBlur = big ? 26 : 14; ctx.shadowOffsetY = big ? 8 : 4;
  const rim = ctx.createRadialGradient(cx, cy - rimR * 0.3, rimR * 0.6, cx, cy, rimR);
  rim.addColorStop(0, '#5a4127'); rim.addColorStop(0.7, '#3f2c19'); rim.addColorStop(1, '#291b0e');
  ctx.fillStyle = rim; ctx.beginPath(); ctx.arc(cx, cy, rimR, 0, Math.PI * 2); ctx.fill();
  ctx.restore();
  // walnut grain — restrained concentric growth rings within the rim band
  ctx.save();
  ctx.beginPath(); ctx.arc(cx, cy, rimR, 0, Math.PI * 2); ctx.arc(cx, cy, R, 0, Math.PI * 2, true); ctx.clip('evenodd');
  for (let i = 0; i < 7; i++) {
    const rr2 = R + (rimR - R) * ((i + 0.35) / 7);
    ctx.strokeStyle = i % 2 ? 'rgba(30,18,6,0.22)' : 'rgba(120,88,48,0.16)';
    ctx.lineWidth = i % 2 ? 1.4 : 1;
    ctx.beginPath(); ctx.arc(cx + (big ? 3 : 2), cy + (big ? 2 : 1), rr2, 0, Math.PI * 2); ctx.stroke();
  }
  ctx.restore();
  ctx.strokeStyle = 'rgba(20,12,4,0.55)'; ctx.lineWidth = 1; ctx.beginPath(); ctx.arc(cx, cy, rimR, 0, Math.PI * 2); ctx.stroke();

  // drumhead — warm coated skin, matte, lit gently from upper-left
  const head = ctx.createRadialGradient(cx - R * 0.28, cy - R * 0.32, R * 0.15, cx, cy, R);
  head.addColorStop(0, '#e7d4ac'); head.addColorStop(0.7, '#d8c199'); head.addColorStop(1, '#c3a97e');
  ctx.fillStyle = head; ctx.beginPath(); ctx.arc(cx, cy, R, 0, Math.PI * 2); ctx.fill();
  // coating texture + faint mottle, clipped to the head
  ctx.save();
  ctx.beginPath(); ctx.arc(cx, cy, R, 0, Math.PI * 2); ctx.clip();
  blot(ctx, cx + R * 0.34, cy + R * 0.26, R * 0.6, '150,120,74', 0.12);
  blot(ctx, cx - R * 0.4, cy + R * 0.34, R * 0.5, '120,92,52', 0.1);
  grainFill(ctx, cx - R, cy - R, R * 2, R * 2, 0.4);
  // gentle sheen from the upper-left
  const sheen = ctx.createRadialGradient(cx - R * 0.3, cy - R * 0.34, 0, cx - R * 0.3, cy - R * 0.34, R * 0.9);
  sheen.addColorStop(0, 'rgba(255,248,228,0.22)'); sheen.addColorStop(1, 'rgba(255,248,228,0)');
  ctx.fillStyle = sheen; ctx.fillRect(cx - R, cy - R, R * 2, R * 2);
  ctx.restore();
  // seam where head meets rim
  ctx.strokeStyle = 'rgba(90,66,32,0.5)'; ctx.lineWidth = big ? 3 : 2; ctx.beginPath(); ctx.arc(cx, cy, R, 0, Math.PI * 2); ctx.stroke();
  ctx.strokeStyle = 'rgba(255,248,228,0.25)'; ctx.lineWidth = 1; ctx.beginPath(); ctx.arc(cx, cy, R - 2, Math.PI * 1.05, Math.PI * 1.75); ctx.stroke();

  // restrained concentric practice zones, pencilled
  ctx.strokeStyle = 'rgba(70,52,28,0.16)'; ctx.lineWidth = 1;
  [z.inner, z.middle, z.outer].forEach((rr2) => { ctx.beginPath(); ctx.arc(cx, cy, R * rr2, 0, Math.PI * 2); ctx.stroke(); });
  // small maker's mark at centre
  ctx.strokeStyle = 'rgba(70,52,28,0.3)'; ctx.lineWidth = 1;
  ctx.beginPath(); ctx.arc(cx, cy, R * 0.05, 0, Math.PI * 2); ctx.stroke();

  // strike marks — soft ink (left) / brass (right) blotches that settle and fade
  session.ripples = session.ripples.filter((rp) => now - rp.born < 1400);
  for (const rp of session.ripples) {
    const age = (now - rp.born) / 1400;
    const px = cx + rp.nx * R, py = cy + rp.ny * R, rgb = rgbOf(rp.hand);
    blot(ctx, px, py, (big ? 26 : 18) * (0.6 + age * 0.7), rgb, (1 - age) * 0.5);
    ctx.globalAlpha = (1 - age) * 0.85;
    ctx.fillStyle = `rgb(${rgb})`;
    ctx.beginPath(); ctx.arc(px, py, big ? 5 : 3.5, 0, Math.PI * 2); ctx.fill();
    ctx.globalAlpha = (1 - age) * 0.35; ctx.strokeStyle = `rgb(${rgb})`; ctx.lineWidth = 1;
    ctx.beginPath(); ctx.arc(px, py, (big ? 10 : 7) + age * (big ? 30 : 18), 0, Math.PI * 2); ctx.stroke();
    ctx.globalAlpha = 1;
  }
}

/* ---- render: calibrate preview --------------------------------------- */
function drawCalPreview() {
  const { ctx, w, h } = CAL; if (!w) return;
  ctx.clearRect(0, 0, w, h);
  const cw = cfg.camera.width || 640, ch = cfg.camera.height || 480;
  const s = Math.min(w / cw, h / ch), ox = (w - cw * s) / 2, oy = (h - ch * s) / 2;
  const fx = (x) => ox + x * s, fy = (y) => oy + y * s;
  // camera frame
  ctx.fillStyle = '#2a1f16'; ctx.fillRect(ox, oy, cw * s, ch * s);
  ctx.strokeStyle = 'rgba(44,36,25,0.3)'; ctx.strokeRect(ox, oy, cw * s, ch * s);
  const g = geom(), z = cfg.zones;
  // pad surface + zones
  const head = ctx.createRadialGradient(fx(g.center_x) - g.radius * s * 0.3, fy(g.center_y) - g.radius * s * 0.3, g.radius * s * 0.15, fx(g.center_x), fy(g.center_y), g.radius * s);
  head.addColorStop(0, '#e0cca2'); head.addColorStop(1, '#bda070');
  ctx.fillStyle = head; ctx.beginPath(); ctx.arc(fx(g.center_x), fy(g.center_y), g.radius * s, 0, Math.PI * 2); ctx.fill();
  ctx.save(); ctx.beginPath(); ctx.arc(fx(g.center_x), fy(g.center_y), g.radius * s, 0, Math.PI * 2); ctx.clip();
  grainFill(ctx, fx(g.center_x) - g.radius * s, fy(g.center_y) - g.radius * s, g.radius * s * 2, g.radius * s * 2, 0.5); ctx.restore();
  ctx.strokeStyle = 'rgba(90,66,32,0.7)'; ctx.lineWidth = 2;
  ctx.beginPath(); ctx.arc(fx(g.center_x), fy(g.center_y), g.radius * s, 0, Math.PI * 2); ctx.stroke();
  ctx.strokeStyle = 'rgba(70,52,28,0.28)'; ctx.lineWidth = 1;
  [z.inner, z.middle, z.outer].forEach((r) => { ctx.beginPath(); ctx.arc(fx(g.center_x), fy(g.center_y), g.radius * r * s, 0, Math.PI * 2); ctx.stroke(); });
  ctx.strokeStyle = 'rgba(90,66,32,0.4)'; ctx.setLineDash([4, 4]);
  ctx.beginPath(); ctx.arc(fx(g.center_x), fy(g.center_y), (g.radius + g.rim_width) * s, 0, Math.PI * 2); ctx.stroke(); ctx.setLineDash([]);
  // live tracked tips
  [['L', LEFT], ['R', RIGHT]].forEach(([k, col]) => {
    const p = liveTips[k], out = $(k === 'L' ? '#calL' : '#calR');
    if (p && p.length >= 2) {
      out.textContent = `${Math.round(p[0])}, ${Math.round(p[1])}`;
      ctx.fillStyle = col;
      ctx.beginPath(); ctx.arc(fx(p[0]), fy(p[1]), 7, 0, Math.PI * 2); ctx.fill();
      ctx.strokeStyle = 'rgba(233,223,202,0.85)'; ctx.lineWidth = 1.5;
      ctx.beginPath(); ctx.arc(fx(p[0]), fy(p[1]), 7, 0, Math.PI * 2); ctx.stroke();
    } else { out.textContent = 'no track'; }
  });
}
function renderCalParams() {
  const g = cfg.calibration, a = cfg.audio, c = cfg.camera, z = cfg.zones;
  const pin = (group, key, label, val, step) =>
    `<div class="prow"><label>${label}</label><input class="pin" data-g="${group}" data-k="${key}" type="number" step="${step}" value="${val ?? ''}" /></div>`;
  $('#calParams').innerHTML = `
    <div class="pgroup"><h4>Camera</h4>${pin('camera', 'index', 'index', c.index, 1)}${pin('camera', 'width', 'width', c.width, 1)}${pin('camera', 'height', 'height', c.height, 1)}</div>
    <div class="pgroup"><h4>Pad boundary</h4>${pin('calibration', 'center_x', 'centre x', g.center_x, 1)}${pin('calibration', 'center_y', 'centre y', g.center_y, 1)}${pin('calibration', 'radius', 'radius', g.radius, 1)}${pin('calibration', 'rim_width', 'rim width', g.rim_width, 1)}</div>
    <div class="pgroup"><h4>Zones (× radius)</h4>${pin('zones', 'inner', 'inner', z.inner, 0.05)}${pin('zones', 'middle', 'middle', z.middle, 0.05)}${pin('zones', 'outer', 'outer', z.outer, 0.05)}</div>
    <div class="pgroup"><h4>Audio detection</h4>${pin('audio', 'threshold', 'threshold', a.threshold, 0.01)}${pin('audio', 'sample_rate', 'sample rate', a.sample_rate, 1)}${pin('audio', 'device_index', 'device index', a.device_index, 1)}</div>
    <div class="cal-actions"><button id="calSave" class="begin begin-sm">Save settings</button><span class="cal-status" id="calStatus"></span></div>`;
}
async function saveCalParams() {
  const body = {};
  $$('#calParams .pin').forEach((inp) => {
    if (inp.value === '') return;
    (body[inp.dataset.g] = body[inp.dataset.g] || {})[inp.dataset.k] = parseFloat(inp.value);
  });
  const status = $('#calStatus');
  try {
    const r = await fetch('/config', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) });
    const j = await r.json();
    if (j.ok && j.config) {
      ['camera', 'calibration', 'zones', 'audio'].forEach((k) => Object.assign(cfg[k], j.config[k] || {}));
      renderCalParams();
      $('#calStatus').textContent = 'Saved · applies on next detector start';
    } else { status.textContent = 'Could not save'; }
  } catch (_) { status.textContent = 'Could not save'; }
}

/* ---- kpi helper (shared by review + history) ------------------------- */
function kpi(label, value, sub, warn) {
  return `<div class="kpi"><span class="eyebrow">${label}</span><div class="kpi-n${warn ? ' warn' : ''}">${value}</div><div class="kpi-sub">${sub || ''}</div></div>`;
}

/* ---- session summary + persistence ----------------------------------- */
function computeSummary() {
  const ev = session.events;
  const hits = ev.filter((e) => e.kind === 'hit');
  const c = session.counters, clean = c.perfect + c.good + c.okay, total = clean + c.bad;
  const deltas = hits.map((e) => e.delta * 1000);
  const mean = deltas.length ? deltas.reduce((a, b) => a + b, 0) / deltas.length : 0;
  const spread = deltas.length ? Math.sqrt(deltas.reduce((a, d) => a + (d - mean) ** 2, 0) / deltas.length) : 0;
  return {
    pattern: patternName(), bpm, duration_s: +((session.durationMs || 0) / 1000).toFixed(1),
    strikes: ev.length, accuracy: total ? Math.round((clean / total) * 100) : 0, clean, total,
    mean_ms: Math.round(mean), spread_ms: Math.round(spread), best_streak: session.maxCombo,
    left: ev.filter((e) => e.actual === 'L').length, right: ev.filter((e) => e.actual === 'R').length,
    wrong_hand: hits.filter((e) => !e.correct).length,
    missed: ev.filter((e) => e.kind === 'miss').length, extra: ev.filter((e) => e.kind === 'extra').length,
    perfect: c.perfect, good: c.good, okay: c.okay,
  };
}
function saveSession() {
  if (!session.events.length) return;
  try {
    fetch('/session', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(computeSummary()) });
  } catch (_) {}
}

/* ---- metronome (Web Audio click at the practice tempo) ---------------- */
let audioCtx = null, metroTimer = null, metroNext = 0, metroBeat = 0;
function startMetro() {
  try {
    audioCtx = audioCtx || new (window.AudioContext || window.webkitAudioContext)();
    if (audioCtx.state === 'suspended') audioCtx.resume();
  } catch (_) { return; }
  metroBeat = 0; metroNext = audioCtx.currentTime + 0.12;
  clearInterval(metroTimer);
  metroTimer = setInterval(() => {
    while (metroNext < audioCtx.currentTime + 0.15) {
      const accent = pattern.length ? (metroBeat % pattern.length === 0) : (metroBeat % 4 === 0);
      const osc = audioCtx.createOscillator(), g = audioCtx.createGain();
      osc.frequency.value = accent ? 1600 : 1050;
      g.gain.setValueAtTime(0.0001, metroNext);
      g.gain.exponentialRampToValueAtTime(accent ? 0.5 : 0.28, metroNext + 0.001);
      g.gain.exponentialRampToValueAtTime(0.0001, metroNext + 0.05);
      osc.connect(g).connect(audioCtx.destination);
      osc.start(metroNext); osc.stop(metroNext + 0.06);
      metroNext += 60 / bpm; metroBeat++;
    }
  }, 25);
}
function stopMetro() { clearInterval(metroTimer); metroTimer = null; }

/* ---- render: history -------------------------------------------------- */
async function renderHistory() {
  let sessions = [];
  try { sessions = await (await fetch('/sessions')).json(); } catch (_) {}
  const has = Array.isArray(sessions) && sessions.length > 0;
  $('#histEmpty').hidden = has;
  $('#histBody').hidden = !has;
  $('#histActions').hidden = !has;
  if (!has) {
    $('#histSummary').textContent = '';
    $('#histKey').innerHTML = ''; $('#histTrend').innerHTML = ''; $('#histList').innerHTML = '';
    return;
  }

  const n = sessions.length;
  const avgAcc = Math.round(sessions.reduce((a, s) => a + (s.accuracy || 0), 0) / n);
  const totalStrikes = sessions.reduce((a, s) => a + (s.strikes || 0), 0);
  const best = Math.max(0, ...sessions.map((s) => s.best_streak || 0));
  $('#histSummary').textContent = `${n} session${n > 1 ? 's' : ''} · ${totalStrikes} strikes logged`;
  $('#histKey').innerHTML =
    kpi('Sessions', n, 'logged') +
    kpi('Average accuracy', avgAcc + '%', 'across all', avgAcc < 60) +
    kpi('Best streak', best, 'all-time');

  const chron = [...sessions].reverse().slice(-30);
  $('#histTrend').innerHTML = chron.map((s) => {
    const a = Math.round(s.accuracy || 0);
    return `<span class="tbar" title="${s.pattern || ''} · ${a}%"><i style="height:${Math.max(3, a)}%"></i></span>`;
  }).join('');

  $('#histList').innerHTML = sessions.map((s) => {
    const d = new Date((s.recorded_at || 0) * 1000);
    const when = d.toLocaleString(undefined, { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' });
    const tim = s.mean_ms != null ? `${s.mean_ms > 0 ? '+' : ''}${s.mean_ms} ms` : '—';
    return `<div class="hist-row"><span>${when}</span><span>${s.pattern || '—'}</span><span>${s.bpm || '—'} bpm</span><span>${s.accuracy ?? 0}%</span><span>${tim}</span><span>×${s.best_streak || 0}</span></div>`;
  }).join('');
}

/* ---- render: review --------------------------------------------------- */
function mmss(ms) {
  const s = Math.max(0, Math.round(ms / 1000));
  return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, '0')}`;
}
async function renderAnalysis() {
  const ev = session.events;
  const has = ev.length > 0;
  $('#anaEmpty').hidden = has;
  $('#anaBody').hidden = !has;
  $('#revTitle').textContent = has ? patternName() : 'The session';
  if (!has) { $('#revSummary').textContent = ''; return; }

  const notes = session.notes.filter((n) => n.judged || n.missed).sort((a, b) => a.idx - b.idx);
  const hits = ev.filter((e) => e.kind === 'hit');
  const c = session.counters, clean = c.perfect + c.good + c.okay, total = clean + c.bad;
  const acc = total ? Math.round((clean / total) * 100) : 0;
  const wrong = hits.filter((e) => !e.correct).length;
  const missCount = ev.filter((e) => e.kind === 'miss').length;
  const extraCount = ev.filter((e) => e.kind === 'extra').length;
  const Lc = ev.filter((e) => e.actual === 'L').length, Rc = ev.filter((e) => e.actual === 'R').length;

  // timing statistics (ms)
  const deltas = hits.map((e) => e.delta * 1000);
  const mean = deltas.length ? deltas.reduce((a, b) => a + b, 0) / deltas.length : 0;
  const spread = deltas.length ? Math.round(Math.sqrt(deltas.reduce((a, d) => a + (d - mean) ** 2, 0) / deltas.length)) : 0;
  const meanR = Math.round(mean);
  const tend = meanR > 8 ? 'dragging' : meanR < -8 ? 'rushing' : 'on the beat';
  const signed = `${meanR > 0 ? '+' : ''}${meanR}`;

  let sc = 0; try { sc = (await (await fetch('/score')).json()).score || 0; } catch (_) {}

  // summary line
  $('#revSummary').textContent = `${bpm} bpm · ${ev.length} strikes · ${mmss(session.durationMs || 0)}`;

  // KEY PERFORMANCE band
  $('#revKey').innerHTML =
    kpi('Accuracy', acc + '%', `${clean} of ${total} clean`, acc < 60) +
    kpi('Timing', `${signed}<span style="font-size:22px">ms</span>`, tend, Math.abs(meanR) > 25) +
    kpi('Best streak', session.maxCombo, 'notes in a row') +
    kpi('Steadiness', `±${spread}<span style="font-size:22px">ms</span>`, 'timing spread', spread > 45);

  // timing note
  $('#timingNote').textContent = deltas.length
    ? `On average you played ${tend}${meanR ? `, about ${Math.abs(meanR)} ms ${meanR > 0 ? 'behind' : 'ahead of'} the beat` : ''}, with a spread of ±${spread} ms.`
    : 'No in-window strikes to measure.';

  // PATTERN — target vs actual
  const trow = notes.map((n) => `<span class="gem ${n.hand}">${n.hand}</span>`).join('');
  const arow = notes.map((n) => {
    if (n.missed) return `<span class="gem miss">·</span>`;
    const st = n.result.st;
    return `<span class="gem ${st.hand}${n.result.correct ? '' : ' wrong'}">${st.hand}</span>`;
  }).join('');
  $('#anaSeq').innerHTML =
    `<div class="seqrow"><span class="tag">asked</span>${trow}</div>` +
    `<div class="seqrow"><span class="tag">played</span>${arow}</div>`;

  const m = [];
  notes.forEach((n) => {
    if (n.missed) m.push(`Beat ${n.idx + 1} — missed (expected ${n.hand === 'L' ? 'left' : 'right'})`);
    else if (!n.result.correct) m.push(`Beat ${n.idx + 1} — asked ${n.hand === 'L' ? 'left' : 'right'}, played ${n.result.st.hand === 'L' ? 'left' : 'right'}`);
  });
  if (extraCount) m.push(`${extraCount} stray strike${extraCount > 1 ? 's' : ''} outside the phrase`);
  $('#anaMistakes').innerHTML = m.length
    ? m.slice(0, 12).map((x) => `<li>${x}</li>`).join('')
    : '<li class="clean">A clean run — every note matched hand and timing.</li>';

  // STRIKE CHARACTER
  const order = ['ghost', 'normal', 'accent', 'rimshot'];
  const types = {}; ev.forEach((e) => { if (e.type) types[e.type] = (types[e.type] || 0) + 1; });
  const keys = Object.keys(types).sort((a, b) => order.indexOf(a) - order.indexOf(b));
  const tmax = Math.max(1, ...Object.values(types));
  $('#anaTypes').innerHTML = keys.length
    ? keys.map((k) => `<div class="bar"><div class="bar-top"><span>${k}</span><b>${types[k]}</b></div><div class="track"><div class="fill" style="width:${(types[k] / tmax) * 100}%;background:var(--brass)"></div></div></div>`).join('')
    : '<p class="rev-note">No hit-type data was recorded for this session.</p>';

  // DETAILED METRICS
  const rowT = (k, v) => `<div><dt>${k}</dt><dd>${v}</dd></div>`;
  $('#anaTable').innerHTML =
    rowT('Perfect', c.perfect) + rowT('Good', c.good) + rowT('Okay', c.okay) +
    rowT('Missed notes', missCount) + rowT('Wrong hand', wrong) + rowT('Off-pattern strikes', extraCount) +
    rowT('Left / right strikes', `${Lc} / ${Rc}`) +
    rowT('Mean timing', `${signed} ms`) + rowT('Timing spread', `±${spread} ms`) +
    rowT('Sequence match', `${Math.round(sc * 100)}%`);

  drawTiming(); drawPlacement();
}
function drawTiming() {
  fit(ATIM); const { ctx, w, h } = ATIM; ctx.clearRect(0, 0, w, h);
  const hits = session.events.filter((e) => e.kind === 'hit');
  const cx = w / 2, midY = h / 2, half = w * 0.45, maxD = Math.max(0.12, windows().o), scale = half / maxD;

  // good-timing band around the beat
  const gw = windows().g * scale;
  ctx.fillStyle = 'rgba(125,95,40,0.08)'; ctx.fillRect(cx - gw, 6, gw * 2, h - 12);
  // baseline
  ctx.strokeStyle = 'rgba(44,36,25,0.2)'; ctx.lineWidth = 1;
  ctx.beginPath(); ctx.moveTo(cx - half, midY); ctx.lineTo(cx + half, midY); ctx.stroke();
  // on-beat line
  ctx.strokeStyle = 'rgba(44,36,25,0.5)'; ctx.lineWidth = 1.5;
  ctx.beginPath(); ctx.moveTo(cx, 6); ctx.lineTo(cx, h - 6); ctx.stroke();

  // one dot per strike, spread vertically around the line, placed by earliness/lateness
  hits.forEach((e, i) => {
    const x = Math.max(6, Math.min(w - 6, cx + e.delta * scale));
    const lane = (i % 6) - 2.5;
    const y = midY + lane * (h / 15);
    ctx.fillStyle = handColor(e.actual); ctx.globalAlpha = e.correct ? 0.85 : 0.4;
    ctx.beginPath(); ctx.arc(x, y, 4.5, 0, Math.PI * 2); ctx.fill(); ctx.globalAlpha = 1;
  });

  // mean marker
  if (hits.length) {
    const mean = hits.reduce((a, e) => a + e.delta, 0) / hits.length;
    const mx = Math.max(6, Math.min(w - 6, cx + mean * scale));
    ctx.strokeStyle = Math.abs(mean) > 0.02 ? 'rgba(124,58,52,0.85)' : 'rgba(95,122,78,0.9)';
    ctx.lineWidth = 2; ctx.beginPath(); ctx.moveTo(mx, 2); ctx.lineTo(mx, h - 2); ctx.stroke();
  }
}
function drawPlacement() {
  fit(ADRUM); const { ctx, w, h } = ADRUM; ctx.clearRect(0, 0, w, h);
  const cx = w / 2, cy = h / 2, R = Math.min(w, h) * 0.42, z = cfg.zones;
  const head = ctx.createRadialGradient(cx - R * 0.3, cy - R * 0.3, R * 0.15, cx, cy, R);
  head.addColorStop(0, '#e7d4ac'); head.addColorStop(1, '#c3a97e');
  ctx.fillStyle = head; ctx.beginPath(); ctx.arc(cx, cy, R, 0, Math.PI * 2); ctx.fill();
  ctx.save(); ctx.beginPath(); ctx.arc(cx, cy, R, 0, Math.PI * 2); ctx.clip(); grainFill(ctx, cx - R, cy - R, R * 2, R * 2, 0.5); ctx.restore();
  ctx.strokeStyle = 'rgba(90,66,32,0.5)'; ctx.lineWidth = 2; ctx.beginPath(); ctx.arc(cx, cy, R, 0, Math.PI * 2); ctx.stroke();
  ctx.strokeStyle = 'rgba(70,52,28,0.16)'; ctx.lineWidth = 1;
  [z.inner, z.middle, z.outer].forEach((r) => { ctx.beginPath(); ctx.arc(cx, cy, R * r, 0, Math.PI * 2); ctx.stroke(); });
  session.events.filter((e) => e.nx != null).forEach((e) => {
    ctx.fillStyle = `rgba(${rgbOf(e.actual)},0.8)`;
    ctx.beginPath(); ctx.arc(cx + e.nx * R, cy + e.ny * R, 4, 0, Math.PI * 2); ctx.fill();
  });
}

/* ---- master loop ------------------------------------------------------ */
function frame() {
  if (view === 'play') { drawLane(); drawDrum(DRUM, true); }
  else if (view === 'calibrate') drawCalPreview();
  requestAnimationFrame(frame);
}

/* ---- boot ------------------------------------------------------------- */
loadPrefs();
$('#bpmVal').textContent = bpm;
drawSeq();
renderNow();
loadConfig();
layout();
$('#calParams').addEventListener('click', (e) => { if (e.target.closest('#calSave')) saveCalParams(); });
$('#histClear').addEventListener('click', async () => {
  if (!window.confirm('Clear all saved sessions?')) return;
  try { await fetch('/sessions', { method: 'DELETE' }); } catch (_) {}
  renderHistory();
});
setInterval(poll, 60);
requestAnimationFrame(frame);
