import type {CivicCase} from './api';

type NetworkAsset = {id:string; zone_id:string};
export type NetworkCases = {all:CivicCase[]; open:CivicCase[]; severity:string|null};
const severityRank:Record<string, number> = {critical:4, high:3, medium:2, low:1};
export const isOpenNetworkCase = (item:CivicCase) => !['closed', 'resolved'].includes(item.status);

// Only attach supplied, authorized cases with an exact water-asset/zone match.
// Nearby reports without an asset link are not evidence against a network node.
export function networkCases(nodes:NetworkAsset[], cases:CivicCase[]):Map<string, NetworkCases> {
  const zones = new Map(nodes.map(node=>[node.id, node.zone_id]));
  const grouped = new Map<string, NetworkCases>(nodes.map(node=>[node.id, {all:[], open:[], severity:null}]));
  const seen = new Set<string>();
  for (const item of cases) {
    if (seen.has(item.id) || item.domain!=='water' || !item.asset_id || zones.get(item.asset_id)!==item.zone_id) continue;
    const group = grouped.get(item.asset_id);
    if (!group) continue;
    seen.add(item.id);
    group.all.push(item);
    if (isOpenNetworkCase(item)) group.open.push(item);
  }
  for (const group of grouped.values()) {
    const compare = (a:CivicCase, b:CivicCase) => (severityRank[b.severity] || 0)-(severityRank[a.severity] || 0) || a.id.localeCompare(b.id);
    group.all.sort(compare); group.open.sort(compare);
    group.severity = group.open.length ? (severityRank[group.open[0].severity] ? group.open[0].severity : 'unrated') : null;
  }
  return grouped;
}
