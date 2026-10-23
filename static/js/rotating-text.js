// RotatingText — cycles through words, letter by letter, optionally on a colored
// block that resizes to fit each word. Ported from the React Bits <RotatingText />
// component (JavaScript + CSS variant) to a plain ES module using the Web Animations
// API instead of React and Motion. Effects, stagger order, highlight sizing and the
// readable-text color follow the original.

const segmenter =
  typeof Intl !== 'undefined' && Intl.Segmenter ? new Intl.Segmenter('en', { granularity: 'grapheme' }) : null;
const splitIntoCharacters = text =>
  segmenter ? Array.from(segmenter.segment(text), segment => segment.segment) : Array.from(text);

// Springs from the original, approximated with eased tweens of similar feel.
const SPRING = { duration: 520, easing: 'cubic-bezier(0.22, 1.2, 0.36, 1)' };
const EFFECTS = {
  slide: up => ({
    from: { transform: `translateY(${up ? '100%' : '-100%'})`, opacity: 0 },
    to: { transform: 'translateY(0)', opacity: 1 },
    leave: { transform: `translateY(${up ? '-120%' : '120%'})`, opacity: 0 },
    enter: SPRING,
    exit: { duration: 260, easing: 'cubic-bezier(0.5, 0, 0.75, 0)' }
  }),
  flip: up => ({
    from: { transform: `perspective(480px) rotateX(${up ? -90 : 90}deg)`, opacity: 0 },
    to: { transform: 'perspective(480px) rotateX(0deg)', opacity: 1 },
    leave: { transform: `perspective(480px) rotateX(${up ? 90 : -90}deg)`, opacity: 0 },
    enter: { duration: 600, easing: 'cubic-bezier(0.34, 1.4, 0.64, 1)' },
    exit: { duration: 320, easing: 'cubic-bezier(0.5, 0, 0.75, 0)' }
  }),
  blur: up => ({
    from: { transform: `translateY(${up ? '45%' : '-45%'})`, opacity: 0, filter: 'blur(10px)' },
    to: { transform: 'translateY(0)', opacity: 1, filter: 'blur(0px)' },
    leave: { transform: `translateY(${up ? '-45%' : '45%'})`, opacity: 0, filter: 'blur(10px)' },
    enter: { duration: 550, easing: 'cubic-bezier(0.22, 1, 0.36, 1)' },
    exit: { duration: 300, easing: 'cubic-bezier(0.22, 1, 0.36, 1)' }
  }),
  scale: up => ({
    from: { transform: `scale(${up ? 0.35 : 1.7})`, opacity: 0 },
    to: { transform: 'scale(1)', opacity: 1 },
    leave: { transform: `scale(${up ? 1.7 : 0.35})`, opacity: 0 },
    enter: { duration: 560, easing: 'cubic-bezier(0.34, 1.5, 0.64, 1)' },
    exit: { duration: 260, easing: 'ease-in' }
  }),
  drop: () => ({
    from: { transform: 'translateY(-110%)', opacity: 0 },
    to: { transform: 'translateY(0)', opacity: 1 },
    leave: { transform: 'translateY(110%)', opacity: 0 },
    enter: { duration: 560, easing: 'cubic-bezier(0.34, 1.56, 0.64, 1)' },
    exit: { duration: 300, easing: 'cubic-bezier(0.55, 0, 1, 0.45)' }
  })
};

export const readableText = color => {
  const value = String(color ?? '').trim();
  let rgb = null;
  const hex = value.match(/^#([0-9a-f]{3}|[0-9a-f]{4}|[0-9a-f]{6}|[0-9a-f]{8})$/i);
  if (hex) {
    const digits = hex[1].length < 6 ? [...hex[1].slice(0, 3)].map(c => c + c).join('') : hex[1].slice(0, 6);
    rgb = [0, 2, 4].map(i => parseInt(digits.slice(i, i + 2), 16));
  } else {
    const fn = value.match(/^rgba?\(\s*([\d.]+)[\s,]+([\d.]+)[\s,]+([\d.]+)/i);
    if (fn) rgb = fn.slice(1, 4).map(Number);
  }
  if (!rgb) return undefined;
  const [r, g, b] = rgb.map(channel => {
    const c = Math.min(Math.max(channel / 255, 0), 1);
    return c <= 0.04045 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4;
  });
  return 0.2126 * r + 0.7152 * g + 0.0722 * b > 0.3 ? '#0b0b0c' : '#ffffff';
};

// Mounts into `el` (its text is replaced). Returns { next, previous, jumpTo, reset, destroy }.
export function mountRotatingText(el, options = {}) {
  const o = {
    texts: [],
    effect: 'slide',
    direction: 'up',
    highlight: false,
    highlightColor: '#a855f7',
    rotationInterval: 2000,
    staggerDuration: 0,
    staggerFrom: 'first',
    loop: true,
    auto: true,
    pauseOnHover: false,
    onNext: undefined,
    ...options
  };
  const texts = o.texts.length ? o.texts : [el.textContent.trim()];
  const reduce = window.matchMedia?.('(prefers-reduced-motion: reduce)').matches ?? false;
  const preset = (EFFECTS[o.effect] ?? EFFECTS.slide)(o.direction !== 'down');

  el.textContent = '';
  el.classList.add('text-rotate');
  const sr = document.createElement('span');
  sr.className = 'text-rotate-sr-only';
  el.appendChild(sr);
  let stage = el;
  if (o.highlight) {
    el.classList.add('text-rotate-highlight');
    el.style.backgroundColor = o.highlightColor;
    const ink = readableText(o.highlightColor);
    if (ink) el.style.color = ink;
    stage = document.createElement('span');
    stage.className = 'text-rotate-highlight-content';
    el.appendChild(stage);
  }

  let index = 0;
  let current = null;
  let timer = 0;
  let busy = Promise.resolve();
  let hovered = false;
  let alive = true;

  const delayFor = (i, total) => {
    const step = o.staggerDuration * 1000;
    if (o.staggerFrom === 'first') return i * step;
    if (o.staggerFrom === 'last') return (total - 1 - i) * step;
    if (o.staggerFrom === 'center') return Math.abs(Math.floor(total / 2) - i) * step;
    if (o.staggerFrom === 'random') return Math.floor(Math.random() * total) * step;
    return Math.abs(Number(o.staggerFrom) - i) * step;
  };

  const build = text => {
    const word = document.createElement('span');
    word.className = 'text-rotate-line';
    word.setAttribute('aria-hidden', 'true');
    const chars = [];
    const words = text.split(' ');
    words.forEach((w, wi) => {
      const group = document.createElement('span');
      group.className = 'text-rotate-word';
      splitIntoCharacters(w).forEach(ch => {
        const span = document.createElement('span');
        span.className = 'text-rotate-element';
        span.textContent = ch;
        group.appendChild(span);
        chars.push(span);
      });
      if (wi !== words.length - 1) {
        const space = document.createElement('span');
        space.className = 'text-rotate-space';
        space.textContent = ' ';
        group.appendChild(space);
      }
      word.appendChild(group);
    });
    return { word, chars };
  };

  const fitWidth = () => {
    // Skip the empty moment between one word leaving and the next arriving.
    if (!o.highlight || !stage.offsetWidth) return;
    el.style.width = `${stage.offsetWidth + 1}px`;
  };

  const show = (i, first) => {
    sr.textContent = texts[i];
    const leaving = current;
    busy = busy.then(async () => {
      if (leaving) {
        if (!reduce) {
          const total = leaving.chars.length;
          const finished = Promise.all(leaving.chars.map((c, k) =>
            c.animate([preset.to, preset.leave], { ...preset.exit, delay: delayFor(k, total), fill: 'forwards' }).finished
          )).catch(() => {});
          // Don't wait forever if the browser throttles animations (background tab):
          // move on once the exit should have finished.
          const longest = preset.exit.duration + o.staggerDuration * 1000 * total + 80;
          await Promise.race([finished, new Promise(resolve => setTimeout(resolve, longest))]);
        }
        leaving.word.remove();
      }
      if (!alive) return;
      const next = build(texts[i]);
      stage.appendChild(next.word);
      current = next;
      fitWidth();
      if (!reduce && !first) {
        const total = next.chars.length;
        next.chars.forEach((c, k) =>
          c.animate([preset.from, preset.to], { ...preset.enter, delay: delayFor(k, total), fill: 'backwards' })
        );
      }
    });
  };

  const schedule = () => {
    clearTimeout(timer);
    if (!o.auto || !alive) return;
    timer = setTimeout(() => {
      if (document.hidden || (o.pauseOnHover && hovered)) return schedule();
      api.next();
    }, o.rotationInterval);
  };

  const goTo = i => {
    if (i === index) return;
    index = i;
    show(i, false);
    o.onNext?.(i);
    schedule();
  };

  const api = {
    next: () => goTo(index < texts.length - 1 ? index + 1 : o.loop ? 0 : index),
    previous: () => goTo(index > 0 ? index - 1 : o.loop ? texts.length - 1 : index),
    jumpTo: i => goTo(Math.max(0, Math.min(i, texts.length - 1))),
    reset: () => goTo(0),
    destroy: () => {
      alive = false;
      clearTimeout(timer);
    }
  };

  if (o.pauseOnHover) {
    el.addEventListener('mouseenter', () => { hovered = true; });
    el.addEventListener('mouseleave', () => { hovered = false; });
  }
  if (o.highlight && typeof ResizeObserver !== 'undefined') {
    // Keep the block fitted when fonts load or the text size changes.
    new ResizeObserver(fitWidth).observe(stage);
  }
  show(0, true);
  schedule();
  return api;
}
