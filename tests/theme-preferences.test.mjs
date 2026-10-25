import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {runInNewContext} from 'node:vm';
import {test} from 'node:test';

const startup = readFileSync(new URL('../templates/partials/theme_head.html', import.meta.url), 'utf8').match(/<script>([\s\S]*?)<\/script>/)[1];
function firstPaint(values, unavailable = false) {
  const attributes = {};
  runInNewContext(startup, {
    document: {documentElement: {setAttribute(name, value) { attributes[name] = value; }, classList: {add() {}}}},
    localStorage: {getItem(key) { if (unavailable) throw Error('Storage disabled'); return values[key] || null; }},
    sessionStorage: {getItem() { return '1'; }, removeItem() {}}, location: {pathname: '/'},
    window: {matchMedia() { return {matches: false}; }},
  });
  return attributes;
}
test('saved palette and independent appearance mode apply before first paint', () => {
  for (const palette of ['blue-grey', 'ultraviolet', 'sunset', 'indigo', 'minimal', 'ocean', 'teal-gold', 'lemon', 'rose', 'ice-orange', 'mint-violet', 'mecha']) {
    assert.deepEqual(firstPaint({'dd-palette': palette, 'dd-theme': 'dark'}), {'data-theme': 'dark', 'data-palette': palette});
  }
});
test('invalid preferences and unavailable storage fall back safely', () => {
  assert.deepEqual(firstPaint({'dd-palette': 'unexpected', 'dd-theme': 'unexpected'}), {});
  assert.deepEqual(firstPaint({}, true), {});
  assert.deepEqual(firstPaint({'dd-palette': 'sunset', 'dd-theme': 'system'}), {'data-palette': 'sunset'});
});
