// app.js – Front‑end rhythm game for Smart Drum Pad
// -----------------------------------------------------------
// This script implements the features described in the plan:
//   * Start menu (chart selection, difficulty)
//   * Scrolling note lane using a canvas overlay on the webcam video
//   * Simple hit detection via keyboard (L / R keys) – can be replaced later
//   * Scoring engine with default timing windows (easy/normal/hard)
//   * Score / combo panel on the right
//   * Animated feedback (Perfect / Good / Okay / Bad)
//   * Optional background image & optional music track (played via HTMLAudioElement)
// -----------------------------------------------------------

// ---------- Configuration ------------------------------------------------
const DIFFICULTIES = {
  easy:   { windows: { perfect: 0.060, good: 0.120, okay: 0.200 }, points: { perfect: 80, good: 50, okay: 20, bad: 0 } },
  normal: { windows: { perfect: 0.030, good: 0.070, okay: 0.120 }, points: { perfect: 100, good: 70,  okay: 40,  bad: 0 } },
  hard:   { windows: { perfect: 0.020, good: 0.045, okay: 0.080 }, points: { perfect: 120, good: 90,  okay: 60,  bad: 0 } },
};

// -----------------------------------------------------------
// Global state
let videoStream = null;
let ctx = null;               // Canvas 2D context
let canvas = null;
let animationFrameId = null;
let startTime = null;         // Performance time when song started
let notes = [];               // Loaded chart notes (objects {time, zone, hand, hit})
let pendingNotes = [];        // Subset of notes that haven't been hit yet
let difficulty = DIFFICULTIES.normal;
let score = 0;
let combo = 0;
let maxCombo = 0;
let counters = { perfect: 0, good: 0, okay: 0, bad: 0 };
let feedbackQueue = [];
let music = null;            // HTMLAudioElement (optional)

// UI elements
const menuDiv = document.getElementById('menu');
const chartSelect = document.getElementById('chartSelect');
const difficultySelect = document.getElementById('difficultySelect');
const startBtn = document.getElementById('startBtn');
const scorePanel = document.getElementById('scorePanel');
const scoreValue = document.getElementById('scoreValue');
const comboValue = document.getElementById('comboValue');
const perfectCount = document.getElementById('perfectCount');
const goodCount = document.getElementById('goodCount');
const okayCount = document.getElementById('okayCount');
const badCount = document.getElementById('badCount');

// -----------------------------------------------------------
// Helper: load JSON chart list from the server (assumes ./charts/ folder)
async function loadChartList() {
  try {
    const resp = await fetch('charts/'); // directory listing may not be supported, fallback to static list
    // If the server returns HTML we can't parse; instead we provide a hard‑coded list for now.
    // In a real deployment, you could generate a JSON manifest.
    // For this demo we just load the demo chart.
    const option = document.createElement('option');
    option.value = 'charts/demo.json';
    option.textContent = 'Demo Chart';
    chartSelect.appendChild(option);
  } catch (e) {
    // Fallback – create demo entry manually.
    const option = document.createElement('option');
    option.value = 'charts/demo.json';
    option.textContent = 'Demo Chart';
    chartSelect.appendChild(option);
  }
}

// -----------------------------------------------------------
function initCanvas() {
  canvas = document.getElementById('gameCanvas');
  canvas.width = window.innerWidth;
  canvas.height = window.innerHeight;
  ctx = canvas.getContext('2d');
}

// -----------------------------------------------------------
async function startGame() {
  // Hide menu, show panel & canvas
  menuDiv.style.display = 'none';
  scorePanel.style.display = 'block';

  // Load selected chart
  const chartPath = '/chart'; // always fetch from Flask endpoint
  const chartResp = await fetch(chartPath);
  const rawNotes = await chartResp.json();
  notes = rawNotes.map(n => ({ time: n.time, zone: n.zone, hand: n.hand.toUpperCase(), hit: false }));
  pendingNotes = [...notes];

  // Set difficulty
  const diffKey = difficultySelect.value;
  difficulty = DIFFICULTIES[diffKey];

  // Start webcam video (drawn onto canvas each frame)
  const video = document.createElement('video');
  video.autoplay = true;
  video.playsInline = true;
  try {
    videoStream = await navigator.mediaDevices.getUserMedia({ video: { width: 640, height: 480 }, audio: false });
    video.srcObject = videoStream;
  } catch (err) {
    alert('Unable to access webcam: ' + err.message);
    return;
  }

  // Optional music – try to load track.mp3 from the same directory
  music = new Audio('music/track.mp3');
  music.volume = 0.5; // reasonable default

  // Wait for video to be ready before starting the loop
  video.addEventListener('loadedmetadata', () => {
    startTime = performance.now();
    // Start music at the same moment (if it loads successfully)
    music.play().catch(() => {/* ignore if no track */});
    // Kick off main render loop
    animationFrameId = requestAnimationFrame(() => gameLoop(video));
  });
}

// -----------------------------------------------------------
function gameLoop(video) {
  const now = performance.now();
  const elapsed = (now - startTime) / 1000; // seconds since start

  // ---- Draw background (optional static image) ----
  ctx.clearRect(0, 0, canvas.width, canvas.height);
  // If you have a background image, draw it here. For now we keep it dark.

  // ---- Draw webcam frame ----
  ctx.drawImage(video, 0, 0, canvas.width, canvas.height);

  // ---- Draw scrolling notes ----
  // Settings
  const visibleWindow = 3.0; // seconds ahead of current time that are visible
  const speedPxPerSec = canvas.height / visibleWindow; // notes travel full height in visibleWindow seconds
  const hitLineY = canvas.height * 0.85;

  // Helper to map zone -> x coordinate (simple mapping)
  const zoneToX = zone => {
    const w = canvas.width;
    const map = {
      center: w * 0.5,
      inner: w * 0.35,
      outer: w * 0.65,
      rim: w * 0.85,
    };
    return map[zone] || w * 0.5;
  };

  // Draw each pending note that is within the visible window
  pendingNotes.forEach(note => {
    const timeDelta = note.time - elapsed; // positive = in future
    if (timeDelta < -0.5) {
      // Past and missed – mark as bad automatically
      if (!note.hit) {
        note.hit = true;
        registerHit('bad');
      }
      return;
    }
    if (timeDelta > visibleWindow) return; // not yet visible
    const y = hitLineY - timeDelta * speedPxPerSec;
    const x = zoneToX(note.zone);
    const color = note.hand === 'L' ? 'rgba(0,255,0,0.8)' : 'rgba(255,0,0,0.8)';
    ctx.beginPath();
    ctx.arc(x, y, 12, 0, Math.PI * 2);
    ctx.fillStyle = color;
    ctx.fill();
    ctx.strokeStyle = 'black';
    ctx.lineWidth = 2;
    ctx.stroke();
  });

  // ---- Draw hit line ----
  ctx.strokeStyle = 'white';
  ctx.lineWidth = 3;
  ctx.beginPath();
  ctx.moveTo(0, hitLineY);
  ctx.lineTo(canvas.width, hitLineY);
  ctx.stroke();

  // ---- Draw feedback messages (fade out) ----
  const nowMs = now;
  feedbackQueue = feedbackQueue.filter(fb => {
    const age = nowMs - fb.time;
    if (age > 800) return false;
    const alpha = 1 - age / 800;
    ctx.globalAlpha = alpha;
    ctx.font = '48px Arial';
    ctx.fillStyle = fb.color;
    ctx.textAlign = 'center';
    ctx.fillText(fb.text, canvas.width / 2, canvas.height * 0.4);
    ctx.globalAlpha = 1.0;
    return true;
  });

  // ---- Update UI panel ----
  scoreValue.textContent = score;
  comboValue.textContent = combo;
  perfectCount.textContent = counters.perfect;
  goodCount.textContent = counters.good;
  okayCount.textContent = counters.okay;
  badCount.textContent = counters.bad;

  // Continue loop
  if (pendingNotes.every(n => n.hit)) {
    // Song finished – stop music and show final stats
    music.pause();
    // Simple end screen (could be expanded)
    ctx.fillStyle = 'rgba(0,0,0,0.7)';
    ctx.fillRect(0, 0, canvas.width, canvas.height);
    ctx.fillStyle = 'white';
    ctx.font = '48px Arial';
    ctx.textAlign = 'center';
    ctx.fillText('Song Complete!', canvas.width / 2, canvas.height / 2 - 30);
    ctx.font = '36px Arial';
    ctx.fillText(`Score: ${score}`, canvas.width / 2, canvas.height / 2 + 10);
    ctx.fillText(`Max Combo: ${maxCombo}`, canvas.width / 2, canvas.height / 2 + 50);
    // No further animation frames.
    return;
  }

  animationFrameId = requestAnimationFrame(() => gameLoop(video));
}

// -----------------------------------------------------------
function registerHit(classification) {
  const pts = difficulty.points[classification] || 0;
  score += pts;
  counters[classification] += 1;
  if (classification !== 'bad') {
    combo += 1;
    maxCombo = Math.max(maxCombo, combo);
  } else {
    combo = 0;
  }
  // Add visual feedback
  const colors = { perfect: '#00ff00', good: '#aaff00', okay: '#ffff00', bad: '#ff4444' };
  feedbackQueue.push({ text: classification.toUpperCase(), color: colors[classification] || '#fff', time: performance.now() });
}

// -----------------------------------------------------------
// Keyboard based hit simulation (replace with real sensor data later)
window.addEventListener('keydown', e => {
  if (!startTime) return; // ignore before game start
  const nowSec = (performance.now() - startTime) / 1000;
  const hand = e.key === 'l' ? 'L' : e.key === 'r' ? 'R' : null;
  if (!hand) return;

  // Find the first pending note matching this hand (zone will be ignored for simplicity)
  const candidate = pendingNotes.find(n => !n.hit && n.hand === hand);
  if (!candidate) return;

  const delta = Math.abs(candidate.time - nowSec);
  const win = difficulty.windows;
  let classification = 'bad';
  if (delta <= win.perfect) classification = 'perfect';
  else if (delta <= win.good) classification = 'good';
  else if (delta <= win.okay) classification = 'okay';

  candidate.hit = true;
  registerHit(classification);
});

// -----------------------------------------------------------
// UI wiring
startBtn.addEventListener('click', () => {
  startGame();
});

// Initialize on page load
initCanvas();
loadChartList();
