import assert from 'node:assert/strict';
import test from 'node:test';
import {
  date,
  dateTimeLocalToIso,
  dateTimeLocalValue,
  getDisplayTimezoneLabel,
  getDisplayTimezone,
  setDisplayTimezone,
} from '../apps/web/src/api.ts';

const instant = '2026-10-15T04:00:00.000Z';

test('IST display and date-time input round-trip preserve the instant', () => {
  setDisplayTimezone('Asia/Kolkata');
  const localValue = dateTimeLocalValue(instant);
  assert.equal(localValue, '2026-10-15T09:30');
  assert.equal(dateTimeLocalToIso(localValue), instant);
  assert.equal(getDisplayTimezoneLabel(), 'IST');
  assert.match(date(instant), /09:30/);
});

test('UTC display and date-time input round-trip preserve the instant', () => {
  setDisplayTimezone('UTC');
  const localValue = dateTimeLocalValue(instant);
  assert.equal(localValue, '2026-10-15T04:00');
  assert.equal(dateTimeLocalToIso(localValue), instant);
  assert.equal(getDisplayTimezoneLabel(), 'UTC');
  assert.match(date(instant), /04:00/);
});

test('invalid local times are rejected and unsupported zones fall back safely', () => {
  setDisplayTimezone('UTC');
  assert.throws(() => dateTimeLocalToIso('2026-02-31T10:00'), /valid date and time/);
  assert.throws(() => dateTimeLocalToIso('not-a-date'), /valid date and time/);
  setDisplayTimezone('Europe/Paris');
  assert.equal(getDisplayTimezone(), 'Asia/Kolkata');
  setDisplayTimezone('Asia/Kolkata');
});
