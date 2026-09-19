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

const LEFT = '#33d6c1', RIGHT = '#ff9c3c';
const handColor = (h) => (h === 'L' ? LEFT : RIGHT);
const POINTS = { perfect: 100, good: 70, okay: 40, bad: 0 };
const VERDICT_COL = { perfect: '#eafff6', good: '#b7f0c2', okay: '#ecd08a', bad: '#e97f6f', stray: '#e97f6f' };
const LEADIN = 2.2;

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

/* ---- app / view state ------------------------------------------------- */
let view = 'play';
function setView(v) {
  view = v;
  document.body.dataset.view = v;
  $$('#viewnav button').forEach((b) => b.classList.toggle('on', b.dataset.goto === v));
  $$('.view-analysis, .view-calibrate').forEach((s) => { });
  $('.view-analysis').hidden = v !== 'analysis';
  $('.view-calibrate').hidden = v !== 'calibrate';
  layout();
  if (v === 'analysis') renderAnalysis();
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
function drawSeq() {
  $('#seqStrip').innerHTML = pattern.map((h) => `<span class="gem ${h}">${h}</span>`).join('');
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
$('.bpm').addEventListener('click', (e) => {
  const b = e.target.closest('button'); if (!b) return;
  bpm = Math.max(30, Math.min(240, bpm + parseInt(b.dataset.bpm, 10)));
  $('#bpmVal').textContent = bpm;
});

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
  if (pattern.length === 0) { flash('stray', 'ADD A PATTERN'); return; }
  try { await fetch('/set_pattern', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ pattern: pattern.join('') }) }); } catch (_) {}
  Object.assign(session, {
    running: true, start: performance.now(), beat: 60 / bpm, loop: $('#loopChk').checked,
    notes: [], nextIdx: 0, nextTime: LEADIN, cyclesDone: 0,
    score: 0, combo: 0, maxCombo: 0, counters: { perfect: 0, good: 0, okay: 0, bad: 0 }, events: [],
  });
  extendNotes(0);
  const t = $('#transport'); t.textContent = 'Stop session'; t.classList.add('live');
  updateReadouts();
}
function stopSession() {
  session.running = false;
  const t = $('#transport'); t.textContent = 'Start session'; t.classList.remove('live');
  if (session.events.length) setView('analysis');
}
$('#transport').addEventListener('click', () => (session.running ? stopSession() : startSession()));

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
    if (correct) { session.score += POINTS[cls]; session.counters[cls]++; session.combo++; session.maxCombo = Math.max(session.maxCombo, session.combo); flash(cls, cls.toUpperCase()); }
    else { session.counters.bad++; session.combo = 0; flash('bad', 'WRONG HAND'); }
  } else {
    session.events.push({ kind: 'extra', actual: st.hand, nx: st.nx, ny: st.ny, zone: st.zone, type: st.type });
    session.counters.bad++; session.combo = 0; flash('stray', 'STRAY');
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
  const el = $('#hudHand'); el.textContent = hand; el.style.color = handColor(hand);
  $('#hudType').textContent = type; $('#hudZone').textContent = zone === 'off' ? '' : zone + ' zone';
}
function flash(kind, text) {
  const v = $('#verdict'); v.textContent = text; v.style.color = VERDICT_COL[kind] || '#fff';
  v.classList.remove('show'); void v.offsetWidth; v.classList.add('show');
}

/* ---- render: lane ----------------------------------------------------- */
function drawLane() {
  const { ctx, w, h } = LANE; if (!w) return;
  ctx.clearRect(0, 0, w, h);
  const t = session.running ? (performance.now() - session.start) / 1000 : 0;
  if (session.running) { extendNotes(t); sweepMisses(t); }
  const hitY = h * 0.8, travel = 2.4, pps = hitY / travel;
  const cxc = w / 2, off = w * 0.22;

  // rails
  ctx.strokeStyle = 'rgba(255,238,210,0.05)'; ctx.lineWidth = 1;
  [cxc - off, cxc + off].forEach((x) => { ctx.beginPath(); ctx.moveTo(x, 0); ctx.lineTo(x, hitY); ctx.stroke(); });

  // beat pulse on the hit line
  let pulse = 0;
  if (session.running) { const ph = ((t) % session.beat) / session.beat; pulse = Math.max(0, 1 - ph * 3); }
  ctx.fillStyle = `rgba(255,238,210,${0.05 + pulse * 0.12})`;
  ctx.fillRect(0, hitY - 3, w, 6);
  // hand targets at the line
  [['L', cxc - off, LEFT], ['R', cxc + off, RIGHT]].forEach(([lab, x, col]) => {
    ctx.strokeStyle = col; ctx.globalAlpha = 0.55; ctx.lineWidth = 2;
    ctx.beginPath(); ctx.arc(x, hitY, 20, 0, Math.PI * 2); ctx.stroke(); ctx.globalAlpha = 1;
    ctx.fillStyle = col; ctx.globalAlpha = 0.25; ctx.font = '700 13px var(--mono, monospace)';
  });
  ctx.globalAlpha = 1;

  // notes
  for (const n of session.notes) {
    const dt = n.time - t;
    if (dt > travel + 0.3 || dt < -0.6) continue;
    const y = hitY - dt * pps;
    const x = n.hand === 'L' ? cxc - off : cxc + off;
    const col = handColor(n.hand);
    let a = 1, sc = 1;
    if (n.judged && n.result) { const age = t - n.time; a = Math.max(0, 1 - age * 2.5); sc = 1 + Math.min(0.5, Math.max(0, age) * 2); }
    if (n.missed) { a = 0.22; }
    ctx.globalAlpha = a;
    const s = 26 * sc;
    ctx.shadowColor = col; ctx.shadowBlur = n.missed ? 0 : 16;
    ctx.fillStyle = n.missed ? '#2a2319' : col;
    rr(ctx, x - s / 2, y - s / 2, s, s, 8); ctx.fill();
    ctx.shadowBlur = 0;
    ctx.fillStyle = n.missed ? col : '#15120d';
    ctx.font = '800 15px var(--mono, monospace)'; ctx.textAlign = 'center'; ctx.textBaseline = 'middle';
    ctx.fillText(n.hand, x, y + 1);
    ctx.globalAlpha = 1;
  }
}

/* ---- render: drum ----------------------------------------------------- */
function drawDrum(target, big) {
  const { ctx, w, h } = target; if (!w) return;
  ctx.clearRect(0, 0, w, h);
  const cx = w / 2, cy = h / 2, R = Math.min(w, h) * (big ? 0.4 : 0.44);
  const z = cfg.zones, now = performance.now();

  // rim band
  const rimR = R * (1 + geom().rim_width / geom().radius);
  ctx.fillStyle = '#0e0b07'; ctx.beginPath(); ctx.arc(cx, cy, rimR, 0, Math.PI * 2); ctx.fill();
  ctx.strokeStyle = 'rgba(255,238,210,0.14)'; ctx.lineWidth = big ? 5 : 3;
  ctx.beginPath(); ctx.arc(cx, cy, rimR, 0, Math.PI * 2); ctx.stroke();

  // pad surface
  const g = ctx.createRadialGradient(cx, cy - R * 0.2, R * 0.1, cx, cy, R);
  g.addColorStop(0, '#241d15'); g.addColorStop(1, '#181309');
  ctx.fillStyle = g; ctx.beginPath(); ctx.arc(cx, cy, R, 0, Math.PI * 2); ctx.fill();

  // zone rings
  ctx.strokeStyle = 'rgba(255,238,210,0.08)'; ctx.lineWidth = 1;
  [z.inner, z.middle, z.outer].forEach((rr2) => { ctx.beginPath(); ctx.arc(cx, cy, R * rr2, 0, Math.PI * 2); ctx.stroke(); });
  ctx.strokeStyle = 'rgba(255,238,210,0.05)';
  ctx.beginPath(); ctx.moveTo(cx - 6, cy); ctx.lineTo(cx + 6, cy); ctx.moveTo(cx, cy - 6); ctx.lineTo(cx, cy + 6); ctx.stroke();

  // ripples
  session.ripples = session.ripples.filter((rp) => now - rp.born < 900);
  for (const rp of session.ripples) {
    const age = (now - rp.born) / 900;
    const px = cx + rp.nx * R, py = cy + rp.ny * R, col = handColor(rp.hand);
    ctx.globalAlpha = (1 - age) * 0.8; ctx.strokeStyle = col; ctx.lineWidth = 2;
    ctx.beginPath(); ctx.arc(px, py, 6 + age * (big ? 60 : 40), 0, Math.PI * 2); ctx.stroke();
    ctx.globalAlpha = 1 - age; ctx.fillStyle = col; ctx.shadowColor = col; ctx.shadowBlur = 14;
    ctx.beginPath(); ctx.arc(px, py, big ? 8 : 5, 0, Math.PI * 2); ctx.fill(); ctx.shadowBlur = 0;
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
  // frame
  ctx.fillStyle = '#0e0b07'; ctx.fillRect(ox, oy, cw * s, ch * s);
  ctx.strokeStyle = 'rgba(255,238,210,0.12)'; ctx.strokeRect(ox, oy, cw * s, ch * s);
  const g = geom(), z = cfg.zones;
  // pad + zones
  ctx.strokeStyle = 'rgba(255,238,210,0.5)'; ctx.lineWidth = 2;
  ctx.beginPath(); ctx.arc(fx(g.center_x), fy(g.center_y), g.radius * s, 0, Math.PI * 2); ctx.stroke();
  ctx.strokeStyle = 'rgba(255,238,210,0.18)'; ctx.lineWidth = 1;
  [z.inner, z.middle, z.outer].forEach((r) => { ctx.beginPath(); ctx.arc(fx(g.center_x), fy(g.center_y), g.radius * r * s, 0, Math.PI * 2); ctx.stroke(); });
  ctx.strokeStyle = 'rgba(255,238,210,0.3)'; ctx.setLineDash([4, 4]);
  ctx.beginPath(); ctx.arc(fx(g.center_x), fy(g.center_y), (g.radius + g.rim_width) * s, 0, Math.PI * 2); ctx.stroke(); ctx.setLineDash([]);
  // live tips
  [['L', LEFT], ['R', RIGHT]].forEach(([k, col]) => {
    const p = liveTips[k], out = $(k === 'L' ? '#calL' : '#calR');
    if (p && p.length >= 2) {
      out.textContent = `${Math.round(p[0])}, ${Math.round(p[1])}`;
      ctx.fillStyle = col; ctx.shadowColor = col; ctx.shadowBlur = 12;
      ctx.beginPath(); ctx.arc(fx(p[0]), fy(p[1]), 7, 0, Math.PI * 2); ctx.fill(); ctx.shadowBlur = 0;
      ctx.fillStyle = '#15120d'; ctx.font = '800 10px var(--mono, monospace)'; ctx.textAlign = 'center'; ctx.textBaseline = 'middle';
      ctx.fillText(k, fx(p[0]), fy(p[1]) + 1);
    } else { out.textContent = 'no track'; }
  });
}
function renderCalParams() {
  const g = cfg.calibration, a = cfg.audio, c = cfg.camera, z = cfg.zones;
  const row = (k, v) => `<div class="prow"><span>${k}</span><b>${v}</b></div>`;
  $('#calParams').innerHTML = `
    <div class="pgroup"><h4>Camera</h4>${row('index', c.index ?? '—')}${row('resolution', `${c.width}×${c.height}`)}</div>
    <div class="pgroup"><h4>Pad boundary</h4>${row('centre', `${g.center_x}, ${g.center_y}`)}${row('radius', g.radius + ' px')}${row('rim width', g.rim_width + ' px')}</div>
    <div class="pgroup"><h4>Zones (× radius)</h4>${row('inner', z.inner)}${row('middle', z.middle)}${row('outer', z.outer)}</div>
    <div class="pgroup"><h4>Audio detection</h4>${row('device', a.device_index ?? 'default')}${row('sample rate', (a.sample_rate ?? '—') + ' Hz')}${row('threshold', a.threshold ?? '—')}${row('latency', (a.latency_ms ?? 0) + ' ms')}</div>`;
}

/* ---- render: analysis ------------------------------------------------- */
async function renderAnalysis() {
  const ev = session.events;
  $('#anaEmpty').style.display = ev.length ? 'none' : 'block';
  $('#anaCards').style.display = ev.length ? 'grid' : 'none';
  if (!ev.length) return;

  // presented notes in order (judged or missed)
  const notes = session.notes.filter((n) => n.judged || n.missed).sort((a, b) => a.idx - b.idx).slice(0, 48);
  // target vs actual
  const trow = notes.map((n) => `<span class="gem ${n.hand}">${n.hand}</span>`).join('');
  const arow = notes.map((n) => {
    if (n.missed) return `<span class="gem miss">·</span>`;
    const st = n.result.st; const wrong = !n.result.correct ? ' wrong' : '';
    return `<span class="gem ${st.hand}${wrong}">${st.hand}</span>`;
  }).join('');
  $('#anaSeq').innerHTML =
    `<div class="seqrow"><span class="tag">target</span>${trow}</div>` +
    `<div class="seqrow"><span class="tag">you</span>${arow}</div>`;

  // hand accuracy
  const grp = (hand) => { const pn = notes.filter((n) => n.hand === hand); const ok = pn.filter((n) => n.judged && n.result.correct).length; return { tot: pn.length, ok }; };
  const L = grp('L'), R = grp('R');
  const bar = (lab, col, ok, tot) => {
    const p = tot ? Math.round((ok / tot) * 100) : 0;
    return `<div class="bar"><div class="bar-top"><span>${lab}</span><b>${ok}/${tot} · ${p}%</b></div><div class="track"><div class="fill" style="width:${p}%;background:${col}"></div></div></div>`;
  };
  let sc = 0; try { sc = (await (await fetch('/score')).json()).score || 0; } catch (_) {}
  $('#anaHands').innerHTML = bar('Left hand', LEFT, L.ok, L.tot) + bar('Right hand', RIGHT, R.ok, R.tot) +
    `<div class="bar"><div class="bar-top"><span>Backend L/R match</span><b>${Math.round(sc * 100)}%</b></div><div class="track"><div class="fill" style="width:${Math.round(sc * 100)}%;background:#cdbfa4"></div></div></div>`;

  // hit types
  const types = {}; ev.forEach((e) => { if (e.type) types[e.type] = (types[e.type] || 0) + 1; });
  const tmax = Math.max(1, ...Object.values(types));
  $('#anaTypes').innerHTML = Object.keys(types).length
    ? Object.entries(types).map(([k, v]) => `<div class="bar"><div class="bar-top"><span>${k}</span><b>${v}</b></div><div class="track"><div class="fill" style="width:${(v / tmax) * 100}%;background:#cdbfa4"></div></div></div>`).join('')
    : '<div class="bar"><div class="bar-top"><span>no hit-type data</span></div></div>';

  // mistakes
  const m = [];
  notes.forEach((n) => {
    if (n.missed) m.push(`Beat ${n.idx + 1} — missed (expected ${n.hand})`);
    else if (!n.result.correct) m.push(`Beat ${n.idx + 1} — expected ${n.hand}, struck ${n.result.st.hand}`);
  });
  ev.filter((e) => e.kind === 'extra').forEach(() => m.push('Stray strike outside the pattern'));
  $('#anaMistakes').innerHTML = m.length ? m.slice(0, 24).map((x) => `<li>${x}</li>`).join('') : '<li class="clean">Clean run — every note matched hand and timing.</li>';

  drawTiming(); drawPlacement();
}
function drawTiming() {
  fit(ATIM); const { ctx, w, h } = ATIM; ctx.clearRect(0, 0, w, h);
  const hits = session.events.filter((e) => e.kind === 'hit');
  const cx = w / 2, scale = w * 0.42 / Math.max(0.12, windows().o);
  ctx.strokeStyle = 'rgba(255,238,210,0.25)'; ctx.lineWidth = 2;
  ctx.beginPath(); ctx.moveTo(cx, 8); ctx.lineTo(cx, h - 8); ctx.stroke();
  ctx.strokeStyle = 'rgba(255,238,210,0.06)';
  [-1, 1].forEach((s) => { const x = cx + s * windows().g * scale; ctx.beginPath(); ctx.moveTo(x, 10); ctx.lineTo(x, h - 10); ctx.stroke(); });
  hits.forEach((e, i) => {
    const x = Math.max(6, Math.min(w - 6, cx + e.delta * scale));
    const y = 14 + ((i * 37) % (h - 28));
    ctx.fillStyle = handColor(e.actual); ctx.globalAlpha = e.correct ? 0.9 : 0.4;
    ctx.beginPath(); ctx.arc(x, y, 4, 0, Math.PI * 2); ctx.fill(); ctx.globalAlpha = 1;
  });
}
function drawPlacement() {
  fit(ADRUM); const { ctx, w, h } = ADRUM; ctx.clearRect(0, 0, w, h);
  const cx = w / 2, cy = h / 2, R = Math.min(w, h) * 0.42, z = cfg.zones;
  ctx.fillStyle = '#181309'; ctx.beginPath(); ctx.arc(cx, cy, R, 0, Math.PI * 2); ctx.fill();
  ctx.strokeStyle = 'rgba(255,238,210,0.12)';
  [z.inner, z.middle, z.outer, 1].forEach((r) => { ctx.beginPath(); ctx.arc(cx, cy, R * r, 0, Math.PI * 2); ctx.stroke(); });
  session.events.filter((e) => e.nx != null).forEach((e) => {
    ctx.fillStyle = handColor(e.actual); ctx.globalAlpha = 0.75;
    ctx.beginPath(); ctx.arc(cx + e.nx * R, cy + e.ny * R, 4, 0, Math.PI * 2); ctx.fill(); ctx.globalAlpha = 1;
  });
}

/* ---- master loop ------------------------------------------------------ */
function frame() {
  if (view === 'play') { drawLane(); drawDrum(DRUM, true); }
  else if (view === 'calibrate') drawCalPreview();
  requestAnimationFrame(frame);
}

/* ---- boot ------------------------------------------------------------- */
drawSeq();
$('#bpmVal').textContent = bpm;
loadConfig();
layout();
setInterval(poll, 60);
requestAnimationFrame(frame);
