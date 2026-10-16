import assert from 'node:assert/strict';
import test from 'node:test';
import {explainCase} from '../apps/web/src/caseExplanation.ts';

const record = {
  id: 'case-17',
  title: 'Overnight water use increased',
  domain: 'water',
  zone_id: 'river',
  severity: 'high',
  status: 'investigating',
  summary: 'The meter recorded higher overnight flow than its recent baseline.',
  provenance: 'Synthetic',
  evidence: {
    finding_id: 'finding-42',
    estimated_excess: 430,
    unit: 'litres',
    reason_codes: ['persistent_over_baseline'],
    limitations: ['Synthetic evaluation does not establish real-world accuracy.'],
    alternative_explanations: ['A legitimate operating schedule change.'],
    next_action: 'Review the meter interval and operating schedule.',
  },
  corroboration: {reports: 3, unique_reporters: 2},
  evidence_records: [{id: 'evidence-5', kind: 'inspection'}],
};

test('case explanations cite the authorized case, finding, and field record', () => {
  const answer = explainCase(record, 'summary');
  assert.deepEqual(answer.sources.map(source => source.id), ['case-17', 'finding-42', 'evidence-5']);
  assert.match(answer.caveat, /does not diagnose a fault/);
  assert.ok(answer.points.some(point => point.includes('Synthetic')));
});

test('support explanation preserves distinct-reporter counts and does not turn them into proof', () => {
  const answer = explainCase(record, 'support');
  assert.ok(answer.points.some(point => point.includes('3 linked report(s) come from 2 distinct account(s)')));
  assert.ok(answer.points.some(point => point.includes('not proof of a fault')));
  assert.ok(answer.points.some(point => point.includes('finding_id="finding-42"')));
});

test('uncertainty and reviewer guidance retain recorded limits and avoid automatic decisions', () => {
  const unknowns = explainCase(record, 'uncertainty');
  const next = explainCase(record, 'next_checks');
  assert.ok(unknowns.points.some(point => point.includes('does not establish real-world accuracy')));
  assert.ok(unknowns.points.some(point => point.includes('legitimate operating schedule change')));
  assert.ok(next.points.some(point => point.includes('Review the meter interval')));
  assert.ok(next.caveat.includes('replace human review'));
});
