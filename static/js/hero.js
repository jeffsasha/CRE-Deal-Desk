// Opening page: an animated New York skyline drawn on a canvas (no photos) and the
// owner's badge hanging on a lanyard. Everything here is decoration; the page works
// as plain HTML without it.
import { mountLanyard } from './lanyard.js';
import { mountRotatingText } from './rotating-text.js';

const reduceMotion = window.matchMedia('(prefers-reduced-motion: reduce)').matches;

// ---- Skyline photo: slow parallax with the pointer ----------------------------------

function startSkyline(el) {
  if (reduceMotion) return;
  const img = el.querySelector('img');
  const target = { x: 0, y: 0 };
  const now = { x: 0, y: 0 };
  window.addEventListener('pointermove', e => {
    target.x = (e.clientX / window.innerWidth - 0.5) * 2;
    target.y = (e.clientY / window.innerHeight - 0.5) * 2;
  });
  const loop = () => {
    now.x += (target.x - now.x) * 0.05;
    now.y += (target.y - now.y) * 0.05;
    img.style.translate = `${-now.x * 14}px ${-now.y * 8}px`;
    requestAnimationFrame(loop);
  };
  requestAnimationFrame(loop);
}

// ---- Badge artwork (drawn to canvases, handed to the lanyard as images) -------------

const loadImg = src => new Promise(resolve => {
  if (!src) return resolve(null);
  const img = new Image();
  img.onload = () => resolve(img);
  img.onerror = () => resolve(null);
  img.src = src;
});

const SERIF = '"Source Serif 4", Georgia, serif';
const SANS = 'Inter, -apple-system, "Segoe UI", sans-serif';

function roundRect(c, x, y, w, h, r) {
  c.beginPath();
  c.moveTo(x + r, y);
  c.arcTo(x + w, y, x + w, y + h, r);
  c.arcTo(x + w, y + h, x, y + h, r);
  c.arcTo(x, y + h, x, y, r);
  c.arcTo(x, y, x + w, y, r);
  c.closePath();
}

function githubMark(c, x, y, s, color) {
  const p = new Path2D('M8 0c4.42 0 8 3.58 8 8a8.013 8.013 0 0 1-5.45 7.59c-.4.08-.55-.17-.55-.38 0-.27.01-1.13.01-2.2 0-.75-.25-1.23-.54-1.48 1.78-.2 3.65-.88 3.65-3.95 0-.88-.31-1.59-.82-2.15.08-.2.36-1.02-.08-2.12 0 0-.67-.22-2.2.82-.64-.18-1.32-.27-2-.27-.68 0-1.36.09-2 .27-1.53-1.03-2.2-.82-2.2-.82-.44 1.1-.16 1.92-.08 2.12-.51.56-.82 1.28-.82 2.15 0 3.06 1.86 3.75 3.64 3.95-.23.2-.44.55-.51 1.07-.46.21-1.61.55-2.33-.66-.15-.24-.6-.83-1.23-.82-.67.01-.27.38.01.53.34.19.73.9.82 1.13.16.45.68 1.31 2.69.94 0 .67.01 1.3.01 1.49 0 .21-.15.45-.55.38A7.995 7.995 0 0 1 0 8c0-4.42 3.58-8 8-8Z');
  c.save();
  c.translate(x, y);
  c.scale(s / 16, s / 16);
  c.fillStyle = color;
  c.fill(p);
  c.restore();
}

function fitLogo(c, img, cx, cy, maxW, maxH) {
  if (!img) return;
  const k = Math.min(maxW / img.width, maxH / img.height);
  c.drawImage(img, cx - (img.width * k) / 2, cy - (img.height * k) / 2, img.width * k, img.height * k);
}

async function badgeImages(el) {
  const d = el.dataset;
  const [photo, logo, logoWhite] = await Promise.all([loadImg(d.photo), loadImg(d.logo), loadImg(d.logoWhite)]);
  try { await document.fonts.ready; } catch (e) { /* fonts optional */ }
  const W = 1024, H = 1440;
  const CARD = '#f3f3f2';
  const MONO = '"JetBrains Mono", ui-monospace, "SF Mono", Menlo, monospace';

  // Front: white card, faint logo watermark, handle, black-and-white cut-out portrait.
  const f = document.createElement('canvas');
  f.width = W; f.height = H;
  const c = f.getContext('2d');
  c.fillStyle = CARD;
  c.fillRect(0, 0, W, H);
  if (logo) {
    c.globalAlpha = 0.07;
    fitLogo(c, logo, 190, 205, 230, 120);
    c.globalAlpha = 1;
  }
  c.fillStyle = '#5c5c5c';
  c.font = `500 52px ${MONO}`;
  c.textAlign = 'right';
  c.textBaseline = 'middle';
  c.fillText(d.handle, W - 70, 120);
  if (photo) {
    if (d.cutout) {
      // Cut-out sticker: as wide as the card, sitting on the bottom edge.
      const k = Math.max((W * 1.02) / photo.width, (H * 0.8) / photo.height);
      const w = photo.width * k, h = photo.height * k;
      c.drawImage(photo, (W - w) / 2, H - h + 20, w, h);
    } else {
      // Original photo: grayscale portrait panel.
      c.save();
      c.filter = 'grayscale(1) contrast(1.15)';
      roundRect(c, 110, 300, W - 220, H - 420, 28);
      c.clip();
      const k = Math.max((W - 220) / photo.width, (H - 420) / photo.height);
      c.drawImage(photo, W / 2 - (photo.width * k) / 2, 300, photo.width * k, photo.height * k);
      c.restore();
    }
  } else {
    c.fillStyle = '#d9d9d6';
    c.font = `700 300px ${SERIF}`;
    c.textAlign = 'center';
    c.fillText(d.name.split(' ').map(s => s[0]).join(''), W / 2, H * 0.6);
  }
  // Soft sheen toward the bottom, like a printed card.
  const sheen = c.createLinearGradient(0, H * 0.55, 0, H);
  sheen.addColorStop(0, 'rgba(255,255,255,0)');
  sheen.addColorStop(1, 'rgba(255,255,255,0.10)');
  c.fillStyle = sheen;
  c.fillRect(0, 0, W, H);

  // Back: name, firm, logo and GitHub on the same white card.
  const b = document.createElement('canvas');
  b.width = W; b.height = H;
  const k = b.getContext('2d');
  k.fillStyle = CARD;
  k.fillRect(0, 0, W, H);
  if (logo) {
    k.globalAlpha = 0.9;
    fitLogo(k, logo, W / 2, 520, 460, 220);
    k.globalAlpha = 1;
  }
  k.textAlign = 'center';
  k.fillStyle = '#1d1d1f';
  k.font = `700 104px ${SERIF}`;
  k.fillText(d.name, W / 2, 830);
  // The printed badge uses dark ink on white in every UI theme.
  k.fillStyle = '#293352';
  k.font = `600 44px ${SANS}`;
  k.fillText(d.line1.toUpperCase(), W / 2, 910);
  k.fillStyle = '#6a6a6a';
  k.font = `500 40px ${SANS}`;
  k.fillText(d.line2, W / 2, 970);
  githubMark(k, W / 2 - 34, 1130, 68, '#1d1d1f');
  k.fillStyle = '#3a3a3a';
  k.font = `500 42px ${MONO}`;
  k.fillText(d.github, W / 2, 1270);

  // Strap: black band with the white logo at intervals.
  const s = document.createElement('canvas');
  s.width = 900; s.height = 120;
  const t = s.getContext('2d');
  t.fillStyle = '#0d0d0f';
  t.fillRect(0, 0, s.width, s.height);
  if (logoWhite) fitLogo(t, logoWhite, 150, 60, 150, 56);
  t.fillStyle = 'rgba(255,255,255,0.55)';
  t.font = `600 30px ${SANS}`;
  t.textBaseline = 'middle';
  t.fillText('DEALDESK', 420, 62);
  return { front: f.toDataURL('image/png'), back: b.toDataURL('image/png'), strap: s.toDataURL('image/png') };
}

async function startBadge(el) {
  const images = await badgeImages(el);
  const narrow = window.matchMedia('(max-width: 900px)').matches;
  const lanyard = mountLanyard(el, {
    frontImage: images.front,
    backImage: images.back,
    strapImage: images.strap,
    cardColor: '#f3f3f2',
    finish: 'glossy',
    metal: 'silver',
    strapColor: '#0d0d0f',
    size: narrow ? 0.62 : 0.56,
    anchor: narrow ? 'center' : 'right',
    strapLength: 0.42,
    strapWidth: 0.7,
    breeze: 0.4
  });
  if (!lanyard) {
    const img = document.createElement('img');
    img.src = images.front;
    img.alt = el.getAttribute('aria-label') || '';
    img.className = 'badge-fallback';
    el.appendChild(img);
  }
}

const sky = document.querySelector('[data-skyline]');
if (sky) startSkyline(sky);
const badge = document.querySelector('[data-badge]');
if (badge) startBadge(badge);

const rotating = document.querySelector('[data-rotating]');
if (rotating) {
  const words = [...rotating.querySelectorAll('[data-word]')].map(w => w.textContent.trim()).filter(Boolean);
  mountRotatingText(rotating, {
    texts: words,
    effect: 'slide',
    direction: 'up',
    highlight: true,
    highlightColor: 'var(--accent)',
    staggerFrom: 'last',
    staggerDuration: 0.025,
    rotationInterval: 2400
  });
}
