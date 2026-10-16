import type {CivicCase} from './api';

export const HOUR = 3_600_000;
export type TimeWindow = {start: number, end: number};
export type TimelineSelection = {end: number, hours: number};
export type TimedReading = {timestamp?: string, interval_minutes?: number, zone_id?: string, [key: string]: unknown};
const timestamp = (value: unknown) => typeof value === 'string' ? Date.parse(value) : NaN;

export function caseInterval(item: CivicCase): TimeWindow | null {
  const observed = timestamp(item.evidence?.start);
  const start = Number.isFinite(observed) ? observed : timestamp(item.created_at);
  if (!Number.isFinite(start)) return null;
  const end = timestamp(item.evidence?.end);
  // A report is a point observation; analytical event ends are exclusive.
  return {start, end: Number.isFinite(observed) && Number.isFinite(end) && end > start ? end : start + 1};
}

export function readingInterval(row: TimedReading): TimeWindow | null {
  const start = timestamp(row.timestamp);
  if (!Number.isFinite(start)) return null;
  const minutes = typeof row.interval_minutes === 'number' && Number.isFinite(row.interval_minutes) && row.interval_minutes > 0 ? row.interval_minutes : 60;
  return {start, end: start + minutes * 60_000};
}

export function overlaps(interval: TimeWindow | null, window: TimeWindow | null) {
  return !window || !!interval && interval.start < window.end && interval.end > window.start;
}

export function timelineBounds(cases: CivicCase[], readings: TimedReading[]): TimeWindow | null {
  const intervals = [...cases.map(caseInterval), ...readings.map(readingInterval)].filter((x): x is TimeWindow => x !== null);
  if (!intervals.length) return null;
  const start = Math.floor(Math.min(...intervals.map(x => x.start)) / HOUR) * HOUR;
  const end = Math.ceil(Math.max(...intervals.map(x => x.end)) / HOUR) * HOUR;
  return {start, end: Math.max(start + HOUR, end)};
}

export function parseTimeline(search: string): TimelineSelection | null {
  const query = new URLSearchParams(search);
  const end = timestamp(query.get('at'));
  const hours = Number(query.get('hours') || 24);
  return Number.isFinite(end) && [6,24,72,168,720].includes(hours) ? {end, hours} : null;
}

export function selectionWindow(selection: TimelineSelection | null): TimeWindow | null {
  return selection ? {start: selection.end - selection.hours * HOUR, end: selection.end} : null;
}

export function resolveWindow(selection: TimelineSelection | null, period: string, end: number): TimeWindow | null {
  return selectionWindow(selection) || (['1','7','30'].includes(period) ? {start: end - Number(period) * 24 * HOUR, end} : null);
}

export function filterReadings(rows: TimedReading[], zone: string, domain: string, window: TimeWindow | null) {
  // Bootstrap carries water telemetry only. Do not relabel it as another domain.
  return ['all','water'].includes(domain) ? rows.filter(row => (zone === 'all' || row.zone_id === zone) && overlaps(readingInterval(row), window)) : [];
}

export function domainReadings(rows:TimedReading[], domain:string, assets:Array<{id:string;domain:string;zone_id:string}>, zone:string, window:TimeWindow|null) {
  const registry=new Map(assets.map(asset=>[asset.id,asset]));
  return rows.filter(row=>{
    const asset=typeof row.asset_id==='string'?registry.get(row.asset_id):undefined;
    if(row.domain&&row.domain!==domain||asset&&asset.domain!==domain)return false;
    if(asset&&row.zone_id&&asset.zone_id!==row.zone_id)return false;
    const actualZone=row.zone_id||asset?.zone_id;
    return (zone==='all'||actualZone===zone)&&overlaps(readingInterval(row),window);
  });
}
