export type EvidenceQuestion = 'summary' | 'support' | 'uncertainty' | 'next_checks';

export const evidenceQuestions: Array<{id: EvidenceQuestion; label: string}> = [
  {id: 'summary', label: 'Summarize this case'},
  {id: 'support', label: 'Which records support it?'},
  {id: 'uncertainty', label: 'What remains uncertain?'},
  {id: 'next_checks', label: 'What should a reviewer check next?'},
];

type Source = {id: string; label: string};
type Explanation = {title: string; points: string[]; sources: Source[]; caveat: string};
type CaseRecord = {
  id: string;
  title?: string;
  domain?: string;
  zone_id?: string;
  severity?: string;
  status?: string;
  summary?: string;
  provenance?: string;
  evidence?: Record<string, unknown>;
  corroboration?: {reports?: number; unique_reporters?: number};
  evidence_records?: Array<{id?: string; kind?: string}>;
};

export function explainCase(record: CaseRecord, question: EvidenceQuestion): Explanation {
  const evidence = record.evidence || {};
  const fieldRecords = record.evidence_records || [];
  const hasAnalysis = Object.keys(evidence).some(key => !['limitations', 'alternative_explanations'].includes(key));
  const findingId = typeof evidence.finding_id === 'string' ? evidence.finding_id : null;
  const sources: Source[] = [{id: record.id, label: 'Authorized case record'}];
  if (findingId) sources.push({id: findingId, label: 'Analytical finding'});
  for (const item of fieldRecords) {
    if (item.id) sources.push({id: item.id, label: `Recorded ${item.kind || 'evidence'}`});
  }

  let title: string;
  let points: string[];
  if (question === 'summary') {
    title = 'Case summary';
    points = [
      `${record.title || 'Untitled case'} is recorded as ${record.severity || 'unrated'} severity and ${record.status || 'unknown'} status in ${record.zone_id || 'an unspecified zone'}.`,
      `Recorded description: ${record.summary || 'No case description is available.'}`,
      `Provenance: ${record.provenance || 'not stated'}. ${hasAnalysis ? 'Structured analytical fields are attached.' : 'No structured analytical fields are attached.'}`,
    ];
  } else if (question === 'support') {
    title = 'Records supporting this case';
    const fields = Object.entries(evidence).filter(([key]) => !['limitations', 'alternative_explanations'].includes(key));
    points = fields.length
      ? [`The case contains these structured analytical fields: ${fields.map(([key, value]) => `${key}=${JSON.stringify(value)}`).join('; ')}.`]
      : ['No structured analytical reading is attached to this case. Review its recorded description as a report or observation, not as a confirmed fault.'];
    const reports = record.corroboration?.reports || 0;
    const reporters = record.corroboration?.unique_reporters || 0;
    points.push(`${reports} linked report(s) come from ${reporters} distinct account(s). Distinct accounts are observation sources, not proof of a fault.`);
    points.push(`${fieldRecords.length} evidence record(s) are attached${fieldRecords.length ? ` (${fieldRecords.map(item => item.kind || 'evidence').join(', ')})` : ''}.`);
  } else if (question === 'uncertainty') {
    title = 'What remains uncertain';
    const limitations = Array.isArray(evidence.limitations) ? evidence.limitations.filter((value): value is string => typeof value === 'string') : [];
    const alternatives = Array.isArray(evidence.alternative_explanations) ? evidence.alternative_explanations.filter((value): value is string => typeof value === 'string') : Array.isArray(evidence.alternatives) ? evidence.alternatives.filter((value): value is string => typeof value === 'string') : [];
    points = [
      ...limitations.map(value => `Recorded limitation: ${value}`),
      ...alternatives.map(value => `Alternative to check: ${value}`),
    ];
    if (!hasAnalysis) points.push('No structured analytical readings are attached; the report alone does not establish a physical cause.');
    if (!points.length) points.push('No specific limitation or alternative explanation is recorded in the attached fields. The case still does not independently verify a physical cause or repair.');
  } else {
    title = 'Suggested reviewer checks';
    const nextAction = evidence.next_action;
    points = [
      ...(typeof nextAction === 'string' && nextAction.trim() ? [`Recorded suggested next step: ${nextAction}`] : []),
      'Compare the original observation with its source record, operating context, and sensor/data quality before attributing a cause.',
      fieldRecords.some(item => item.kind === 'intervention') && !fieldRecords.some(item => item.kind === 'follow_up')
        ? 'An intervention is recorded without a later follow-up record; an authorized human review is still needed.'
        : 'Use an authorized inspection or follow-up record to document any decision. This assistant does not change case status.',
    ];
  }

  return {
    title,
    points,
    sources,
    caveat: 'Deterministic summary of this authorized API record only. It does not diagnose a fault, verify a repair, establish causation, or replace human review.',
  };
}
