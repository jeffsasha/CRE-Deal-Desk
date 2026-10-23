// Main-app background: a slow GradientASCII glow behind the content area, in the
// Harvard palette. Follows the light / dark theme. Purely decorative.
import { mountGradientASCII } from './gradient-ascii.js';

const el = document.querySelector('[data-app-ascii]');
const PALETTES = {
  // Dark: deep crimson at the shadow edge up to warm parchment at the brightest.
  dark: { colors: ['#4a0f1c', '#a51c30', '#d0644f', '#f0c9a0', '#f6ecdc'], lightMode: false,
          gradientOpacity: 0.32, glyphOpacity: 0.55, glow: 0.25 },
  // Light (parchment): a soft crimson wash with characters a shade darker.
  light: { colors: ['#d9a99c', '#e6c1b2', '#efd8c9', '#f5e8dc', '#f8f1e8'], lightMode: true,
           gradientOpacity: 0.55, glyphOpacity: 0.32, glow: 0.08 }
};

function currentTheme() {
  const forced = document.documentElement.getAttribute('data-theme');
  if (forced === 'light' || forced === 'dark') return forced;
  return window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light';
}

if (el) {
  let theme = currentTheme();
  const ascii = mountGradientASCII(el, {
    ...PALETTES[theme],
    shape: 'horizon',
    characters: ' .:-=+*#%@',
    cellSize: 16,
    density: 0.62,
    flicker: 0.15,
    softness: 0.7,
    scale: 1.15,
    flow: 0.6,
    speed: 0.45,
    grain: 0.05,
    scrambleRadius: 0.07,
    clickEffect: 'none',
    fontFamily: '"JetBrains Mono", ui-monospace, "SF Mono", Menlo, monospace'
  });
  if (ascii) {
    el.classList.add('is-on');
    const sync = () => {
      const next = currentTheme();
      if (next !== theme) {
        theme = next;
        ascii.update(PALETTES[theme]);
      }
    };
    new MutationObserver(sync).observe(document.documentElement, { attributes: true, attributeFilter: ['data-theme'] });
    window.matchMedia('(prefers-color-scheme: dark)').addEventListener('change', sync);
  }
}
