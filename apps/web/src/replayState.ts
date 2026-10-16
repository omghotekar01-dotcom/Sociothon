export type PlaybackRow = {timestamp?: string, [key: string]: unknown};
export const PLAYBACK_SPEEDS = [0.5, 1, 2, 4];

export type PlaybackClock = {job_id:string,version:number,cursor:number,updated_at:string};

/** A delayed poll must not overwrite a newer pause, seek or selected run. */
export function reconcilePlayback<T extends PlaybackClock>(current:T|null,incoming:T,jobId:string):T|null {
  if(incoming.job_id!==jobId)return current;
  if(!current||current.job_id!==jobId)return incoming;
  if(incoming.version!==current.version)return incoming.version>current.version?incoming:current;
  if(incoming.cursor<current.cursor)return current;
  if(incoming.cursor===current.cursor&&Date.parse(incoming.updated_at)<Date.parse(current.updated_at))return current;
  return incoming;
}

/** Return only timestamps present in the persisted scenario branches. */
export function playbackFrames(baseline: PlaybackRow[], modified: PlaybackRow[], clock?: string): number[] {
  const values = [...baseline, ...modified].map(row => typeof row.timestamp === 'string' ? Date.parse(row.timestamp) : NaN).filter(Number.isFinite);
  if (!values.length && clock && Number.isFinite(Date.parse(clock))) values.push(Date.parse(clock));
  return [...new Set(values)].sort((a,b)=>a-b);
}

/** Reveal recorded samples through the server-selected clock without filling gaps. */
export function visiblePlaybackRows(rows: PlaybackRow[], cutoff: number | undefined) {
  return cutoff === undefined ? [] : rows.filter(row => typeof row.timestamp === 'string' && Date.parse(row.timestamp) <= cutoff);
}
