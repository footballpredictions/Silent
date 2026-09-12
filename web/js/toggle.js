/** VPN toggle — same geometry as PC VpnToggle.tsx / Android MainScreen.kt */

export const THUMB_SIZE = 48;
export const TRACK_W = 120;
export const TRACK_H = 60;
export const THUMB_TRAVEL = 64;
export const SNAKE_STROKE = 4;
export const SNAKE_ROTATION_MS = 2200;
export const SNAKE_MIN_VISIBLE_MS = Math.round(SNAKE_ROTATION_MS * 1.5);
export const SNAKE_TAIL_START = 0.02;
export const SNAKE_HEAD_POS = 0.875;

export function snakeRadius(size = THUMB_SIZE, stroke = SNAKE_STROKE) {
  return (size - stroke) / 2;
}

function parseColor(hex) {
  const h = String(hex || "").replace("#", "").trim();
  if (h.length === 6) {
    const n = parseInt(h, 16);
    return { r: (n >> 16) & 255, g: (n >> 8) & 255, b: n & 255 };
  }
  return { r: 0, g: 0, b: 0 };
}

function rgba(hex, alpha) {
  const { r, g, b } = parseColor(hex);
  return `rgba(${r},${g},${b},${alpha})`;
}

export function paintSnakeRing(ctx, color, size = THUMB_SIZE) {
  const cx = size / 2;
  const cy = size / 2;
  const r = snakeRadius(size, SNAKE_STROKE);
  const span = SNAKE_HEAD_POS - SNAKE_TAIL_START;
  const steps = 56;
  ctx.clearRect(0, 0, size, size);
  for (let i = 0; i < steps; i++) {
    const t0 = i / steps;
    const t1 = (i + 1) / steps;
    if (t1 < SNAKE_TAIL_START || t0 > SNAKE_HEAD_POS) continue;
    const mid = (t0 + t1) / 2;
    const alpha = Math.pow(Math.max(0, (mid - SNAKE_TAIL_START) / span), 4.4) * 0.98;
    if (alpha < 0.03) continue;
    const a0 = -Math.PI / 2 + t0 * Math.PI * 2;
    const a1 = -Math.PI / 2 + t1 * Math.PI * 2;
    ctx.beginPath();
    ctx.arc(cx, cy, r, a0, a1);
    ctx.strokeStyle = rgba(color, alpha);
    ctx.lineWidth = SNAKE_STROKE;
    ctx.lineCap = "round";
    ctx.stroke();
  }
}

export function mountToggleSnake(canvas, color) {
  if (!canvas) return () => {};
  const dpr = Math.min(window.devicePixelRatio || 1, 2);
  canvas.width = Math.round(THUMB_SIZE * dpr);
  canvas.height = Math.round(THUMB_SIZE * dpr);
  const ctx = canvas.getContext("2d");
  if (!ctx) return () => {};
  const started = performance.now();
  let frame = 0;
  const tick = (now) => {
    const deg = ((now - started) / SNAKE_ROTATION_MS) * 360;
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    ctx.clearRect(0, 0, THUMB_SIZE, THUMB_SIZE);
    ctx.save();
    ctx.translate(THUMB_SIZE / 2, THUMB_SIZE / 2);
    ctx.rotate((deg * Math.PI) / 180);
    ctx.translate(-THUMB_SIZE / 2, -THUMB_SIZE / 2);
    paintSnakeRing(ctx, color, THUMB_SIZE);
    ctx.restore();
    frame = requestAnimationFrame(tick);
  };
  paintSnakeRing(ctx, color, THUMB_SIZE);
  frame = requestAnimationFrame(tick);
  return () => cancelAnimationFrame(frame);
}

export function toggleMarkup({ visualOn, showSnake, pressed }) {
  const cls = [
    "toggle",
    visualOn ? "on" : "",
    showSnake ? "busy" : "",
    pressed ? "pressed" : "",
  ].filter(Boolean).join(" ");
  return `
    <div class="toggle-wrap">
      <div class="${cls}" role="button" tabindex="0" data-act="toggle" aria-pressed="${visualOn}" aria-busy="${showSnake}">
        ${visualOn ? `<span class="toggle-glow" aria-hidden="true"></span>` : ""}
        <span class="toggle-track" aria-hidden="true"></span>
        <span class="toggle-knob">
          <span class="toggle-knob-pulse${showSnake ? " pulse" : ""}">
            <span class="toggle-face"></span>
            ${showSnake ? `<canvas class="thumb-snake" width="${THUMB_SIZE}" height="${THUMB_SIZE}" aria-hidden="true"></canvas>` : ""}
          </span>
        </span>
      </div>
    </div>`;
}
