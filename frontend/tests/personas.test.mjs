import test from 'node:test';
import assert from 'node:assert/strict';
import { personas, normalizePersona } from '../src/personas.mjs';
test('exactly three fictional personas share one operations application', () => {
  assert.deepEqual(Object.keys(personas), ['maya', 'sarah', 'robert']);
  assert.equal(personas.maya.name, 'Maya Tremblay');
  assert.equal(personas.sarah.role, 'Director of Revenue Operations');
  assert.equal(personas.robert.role, 'Chief Financial Officer');
});
test('invalid saved persona falls back to the operational workspace', () => {
  for (const value of [null, '', 'admin', '__proto__', 'toString', 'Maya'])
    assert.equal(normalizePersona(value), 'maya');
  for (const value of ['maya', 'sarah', 'robert']) assert.equal(normalizePersona(value), value);
});
