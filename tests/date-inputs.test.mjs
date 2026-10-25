import assert from 'node:assert/strict';
import {test} from 'node:test';
import {parseDateInput} from '../static/js/date-inputs.js';

test('ISO dates stay exact, including leap days and years below 100', () => {
  for (const [text, year, month, day] of [['2024-02-29',2024,2,29], ['2026-10-15',2026,10,15], ['0099-01-02',99,1,2]]) {
    const result = parseDateInput(text, 'date');
    assert.ok(result);
    assert.deepEqual([result.getFullYear(),result.getMonth()+1,result.getDate()], [year,month,day]);
  }
});

test('invalid or ambiguous dates are rejected instead of rolling into another day', () => {
  for (const text of ['2026-02-29','2026-02-31','2026-13-01','2026-00-10','2026-04-31','2026-01-00','0000-01-01','10/15/2026','2026-1-2','']) {
    assert.equal(parseDateInput(text, 'date'), null, text);
  }
});

test('date-time and 24 hour time preserve minutes and reject invalid values', () => {
  const date = parseDateInput('2026-10-15T17:32','datetime-local');
  assert.deepEqual([date.getFullYear(),date.getMonth()+1,date.getDate(),date.getHours(),date.getMinutes()], [2026,10,15,17,32]);
  const time = parseDateInput('09:05','time');
  assert.deepEqual([time.getHours(),time.getMinutes()], [9,5]);
  for (const text of ['24:00','12:60','9:00','上午09:00']) assert.equal(parseDateInput(text,'time'),null,text);
  for (const text of ['2026-02-31T10:00','2026-10-15T25:00','2026-10-15']) assert.equal(parseDateInput(text,'datetime-local'),null,text);
});
