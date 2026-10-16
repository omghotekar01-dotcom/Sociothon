import type {CivicCase} from './api';

export type CaseAging = {
  ageLabel: string;
  deadlineLabel: string | null;
  overdue: boolean;
};

function duration(hours: number, mode: 'age' | 'remaining' | 'overdue') {
  const round = mode === 'age' ? Math.floor : Math.ceil;
  if (hours < 1) return `${Math.max(1, round(hours * 60))}m`;
  if (hours < 24) return `${Math.max(1, round(hours))}h`;
  let days = Math.floor(hours / 24);
  let rest = round(hours % 24);
  if (rest >= 24) { days += 1; rest = 0; }
  return rest ? `${days}d ${rest}h` : `${days}d`;
}

export function caseAging(item: Pick<CivicCase, 'created_at' | 'deadline_at' | 'status'>, now = Date.now()): CaseAging | null {
  if (['resolved', 'closed'].includes(item.status)) return null;
  const created = Date.parse(item.created_at);
  if (!Number.isFinite(created)) return null;

  const ageLabel = duration(Math.max(0, (now - created) / 3_600_000), 'age');
  const deadline = item.deadline_at ? Date.parse(item.deadline_at) : Number.NaN;
  if (!Number.isFinite(deadline)) return {ageLabel, deadlineLabel: null, overdue: false};

  const delta = (deadline - now) / 3_600_000;
  if (delta < 0) return {ageLabel, deadlineLabel: `Overdue by ${duration(-delta, 'overdue')}`, overdue: true};
  if (delta === 0) return {ageLabel, deadlineLabel: 'Due now', overdue: false};
  return {ageLabel, deadlineLabel: delta < 1 ? `Due in ${duration(delta, 'remaining')}` : `Due in ${duration(delta, 'age')}`, overdue: false};
}
