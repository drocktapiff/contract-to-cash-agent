import test from 'node:test';
import assert from 'node:assert/strict';
import {
  isActive,
  statusLabel,
  findingCategory,
  findingAmount,
  exportAllowed,
  mergeEvents,
  stageFor,
} from '../src/mapping.mjs';
test('incomplete and interrupted never map to completed', () => {
  assert.equal(statusLabel('incomplete'), 'Incomplete');
  assert.equal(isActive('incomplete'), false);
  assert.equal(statusLabel('interrupted'), 'Interrupted');
});
test('ambiguous duplicates/conflicts have no claimed payable amount', () => {
  for (const status of ['duplicate_invoice', 'conflict']) {
    const f = {
      state: 'verified',
      evidence_verified: true,
      comparisons: [{ status, difference_cad: null }],
    };
    assert.equal(findingAmount(f), null);
    assert.notEqual(findingCategory(f), 'Potential receivable');
  }
});
test('proposed hypothesis never becomes a financial finding', () => {
  assert.equal(
    findingAmount({
      state: 'proposed',
      evidence_verified: false,
      comparisons: [{ difference_cad: '500' }],
    }),
    null,
  );
});
test('pending review and ordinary review approval cannot authorize export', () => {
  const f = { state: 'verified', evidence_verified: true, version: 2, data_revision: 'rev' };
  const run = { status: 'incomplete', mode: 'live', data_revision: 'rev' };
  const review = { status: 'pending', action: 'export', finding_version: 2, data_revision: 'rev' };
  assert.equal(exportAllowed(run, f, review), false);
  review.status = 'approved';
  assert.equal(exportAllowed(run, f, review), true);
  review.action = 'review';
  assert.equal(exportAllowed(run, f, review), false);
  review.action = 'export';
  assert.equal(exportAllowed({ ...run, mode: 'recorded' }, f, review), false);
  assert.equal(exportAllowed({ ...run, data_revision: 'changed' }, f, review), false);
});
test('reconnection deduplicates original event sequences', () => {
  assert.deepEqual(
    mergeEvents([{ sequence: 2 }, { sequence: 1 }], [{ sequence: 2 }, { sequence: 3 }]).map(
      (e) => e.sequence,
    ),
    [1, 2, 3],
  );
});
test('real event types map to meaningful stages', () => {
  assert.equal(stageFor('screening.completed'), 'Screen');
  assert.equal(stageFor('finding.retracted'), 'Findings');
  assert.equal(stageFor('human_review.decided'), 'Review');
  assert.equal(stageFor('evidence.updated'), 'Evidence');
});
