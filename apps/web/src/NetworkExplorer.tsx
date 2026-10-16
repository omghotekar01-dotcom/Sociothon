import {SavedNetworkScenarios} from './SavedNetworkScenarios';
import {useEffect, useState} from 'react';
import {Download, Network, RotateCcw} from 'lucide-react';
import {api, Bootstrap, CivicCase, date, download, fmt, getDisplayTimezoneLabel} from './api';
import {Badge, Empty, ErrorBox, Loading, SectionHead, statusName} from './components';
import {networkCases} from './networkCases';

type Node = {id:string; name:string; type?:string; kind?:string; zone_id:string; x?:number; y?:number};
type Edge = {id:string; source:string; target:string; length_m:number; open?:boolean};
type Topology = {nodes:Node[]; edges:Edge[];configuration_hash:string};
type Connection = {connected:boolean; path:string[]; path_edges:string[]; reachable:string[]; unreachable:string[]; distance_m:number|null; closed_edges:string[]};

export function NetworkPage({data, select}:{data:Bootstrap; select:(c:CivicCase)=>void}) {
  const [network, setNetwork] = useState<Topology|null>(null);
  const [error, setError] = useState('');
  const [revision, setRevision] = useState(0);
  useEffect(() => {
    const controller = new AbortController();
    setError(''); setNetwork(null);
    api('/network', {signal:controller.signal}).then(setNetwork).catch(error => {
      if (!controller.signal.aborted) setError(error.message);
    });
    return () => controller.abort();
  }, [revision]);
  return <>
    <div className="info-banner"><Network size={20}/><div><strong>Explore a closure. Follow the connections.</strong><p>Synthetic directed topology. Paths show connectivity, not water pressure, delivered volume or customers affected.</p></div><Badge type="cyan">TOPOLOGY ONLY</Badge></div>
    {error ? <ErrorBox error={error} retry={()=>setRevision(revision+1)}/> : !network ? <Loading/> : !network.nodes.length ? <Empty title="No authorized water network" text="Your current service scope contains no network assets."/> : <NetworkSandbox key={revision} network={network} data={data} select={select}/>}
  </>;
}

function NetworkSandbox({network, data, select}:{network:Topology; data:Bootstrap; select:(c:CivicCase)=>void}) {
  const [zone, setZone] = useState('');
  const [source, setSource] = useState(network.nodes[0].id);
  const [target, setTarget] = useState(network.nodes.at(-1)!.id);
  const [selected, setSelected] = useState<string|null>(null);
  const [closed, setClosed] = useState<string[]>([]);
  const [showInvestigations, setShowInvestigations] = useState(true);
  const [includeFinished, setIncludeFinished] = useState(false);
  const [zoom, setZoom] = useState(1);
  const [requestRevision, setRequestRevision] = useState(0);
  const [response, setResponse] = useState<{key:string; result?:Connection; error?:string}|null>(null);
  const nodes = network.nodes.filter(n=>!zone || n.zone_id === zone);
  const nodeIds = new Set(nodes.map(n=>n.id));
  const edges = network.edges.filter(e=>nodeIds.has(e.source) && nodeIds.has(e.target));
  const query = JSON.stringify({source, target, closed_edges:closed, zone_id:zone || null});
  const result = response?.key === query ? response.result : undefined;
  const error = response?.key === query ? response.error : undefined;
  useEffect(() => {
    const controller = new AbortController();
    api('/network/path', {method:'POST', body:query, signal:controller.signal})
      .then(result=>setResponse({key:query, result}))
      .catch(error=>{if (!controller.signal.aborted) setResponse({key:query, error:error.message});});
    return () => controller.abort();
  }, [query, requestRevision]);
  const isClosed = (edge:Edge) => edge.open === false || closed.includes(edge.id);
  const toggle = (edge:Edge) => {
    if (edge.open === false) return;
    setClosed(previous=>previous.includes(edge.id) ? previous.filter(id=>id!==edge.id) : [...previous, edge.id].sort());
  };
  const chooseZone = (value:string) => {
    const visible = network.nodes.filter(n=>!value || n.zone_id === value);
    setZone(value); setSource(visible[0].id); setTarget(visible.at(-1)!.id); setClosed([]); setSelected(null);
  };
  const label = (id:string) => network.nodes.find(n=>n.id===id)?.name || id;
  const positions = new Map(nodes.map((n,i)=>[n.id, {x:40+(n.x ?? (15+i*12))*7, y:30+(n.y ?? 50)*4}]));
  const selectedNode = nodes.find(n=>n.id===selected);
  const investigations = networkCases(nodes, data.cases);
  const selectedGroup = selected ? investigations.get(selected) : undefined;
  const selectedCases = (includeFinished ? selectedGroup?.all : selectedGroup?.open) || [];
  const openCount = [...investigations.values()].reduce((total, group)=>total+group.open.length, 0);
  const flaggedAssets = [...investigations.values()].filter(group=>group.open.length).length;
  return <>
    <div className="panel-toolbar topology-toolbar">
      <label>Network zone<select aria-label="Network zone" value={zone} onChange={e=>chooseZone(e.target.value)}><option value="">All authorized zones</option>{[...new Set(network.nodes.map(n=>n.zone_id))].map(id=><option key={id} value={id}>{data.zones.find(z=>z.id===id)?.name || id}</option>)}</select></label>
      <p className="helper">Unsaved closures belong to this page. Save a named scenario below to reopen it later. Zone changes and reset restore the configured network.</p>
      <button className="button secondary" onClick={()=>chooseZone('')}><RotateCcw size={15}/>Reset network scenario</button>
    </div>
    <div className="network-layout topology-layout">
      <section className="panel topology-panel">
        <SectionHead eyebrow="DIRECTED CONNECTIONS" title="Water network sandbox"><Badge>{edges.filter(isClosed).length} closed</Badge></SectionHead>
        <p className="helper pad">Select an asset to inspect it. Select a pipe to close or reopen it; arrows show direction. Equivalent controls are in the registers below.</p>
        <div className="network-investigation-toolbar"><label className="checkbox-label"><input type="checkbox" checked={showInvestigations} onChange={e=>setShowInvestigations(e.target.checked)}/>Show investigation markers</label><p aria-live="polite" data-testid="network-investigation-summary">{openCount} open investigations · {flaggedAssets} of {nodes.length} visible assets</p></div>
        <div className="network-zoom-controls"><button className="button secondary" aria-label="Zoom out network" disabled={zoom<=1} onClick={()=>setZoom(value=>Math.max(1,value-.5))}>−</button><span aria-live="polite">{zoom*100}%</span><button className="button secondary" aria-label="Zoom in network" disabled={zoom>=3} onClick={()=>setZoom(value=>Math.min(3,value+.5))}>+</button><button className="text-button" onClick={()=>setZoom(1)}>Fit network diagram</button><span className="helper">Zoom for detail; scroll the diagram to pan.</span></div>
        <div className="network-map-viewport" tabIndex={0} role="region" aria-label="Scrollable network diagram">
        <svg className="topology-map" style={{width:`${zoom*100}%`}} viewBox="0 0 800 450" role="group" aria-label="Interactive water network">
          <defs><marker id="pipe-arrow" viewBox="0 0 10 10" refX="22" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse"><path d="M 0 0 L 10 5 L 0 10 z" fill="context-stroke"/></marker></defs>
          {edges.map(edge=>{
            const a=positions.get(edge.source)!, b=positions.get(edge.target)!;
            const shut=isClosed(edge), onPath=result?.path_edges.includes(edge.id);
            return <g key={edge.id} role="button" tabIndex={edge.open===false?-1:0} aria-label={`${shut?'Open':'Close'} ${edge.id}`} aria-disabled={edge.open===false} onClick={()=>toggle(edge)} onKeyDown={e=>{if(e.key==='Enter'||e.key===' '){e.preventDefault();toggle(edge);}}} className={`topology-edge ${shut?'closed':onPath?'on-path':''}`} data-edge-id={edge.id} data-on-path={!!onPath}>
              <title>{edge.id}: {label(edge.source)} → {label(edge.target)}, {edge.length_m} m. {shut?'Closed':'Open'}</title>
              <line className="edge-hit" x1={a.x} y1={a.y} x2={b.x} y2={b.y}/>
              <line className="edge-line" x1={a.x} y1={a.y} x2={b.x} y2={b.y} markerEnd="url(#pipe-arrow)"/>
              <text x={(a.x+b.x)/2} y={(a.y+b.y)/2-10} textAnchor="middle">{edge.id}{shut?' ×':''}</text>
            </g>;
          })}
          {nodes.map(node=>{
            const p=positions.get(node.id)!;
            const group=investigations.get(node.id)!;
            const description=group.open.length ? `${group.open.length} open investigations; highest recorded severity ${group.severity}.` : 'No open linked investigations. This does not confirm normal service.';
            return <g key={node.id} role="button" tabIndex={0} aria-label={`Inspect ${node.name}`} aria-describedby={`network-cases-${node.id}`} aria-pressed={selected===node.id} onClick={()=>setSelected(node.id)} onKeyDown={e=>{if(e.key==='Enter'||e.key===' '){e.preventDefault();setSelected(node.id);}}} className={`topology-node ${result?.reachable.includes(node.id)?'reachable':''} ${source===node.id?'source':''} ${selected===node.id?'selected':''}`} data-node-id={node.id} data-open-cases={group.open.length}>
              <title>{node.name}. {description}</title><desc id={`network-cases-${node.id}`}>{description}</desc>
              {showInvestigations && group.open.length>0 && <circle className={`investigation-ring ${group.severity}`} cx={p.x} cy={p.y} r={24} data-case-marker={node.id}/>}
              <circle cx={p.x} cy={p.y} r={17}/><text x={p.x} y={p.y+4} textAnchor="middle">{source===node.id?'S':target===node.id?'T':'•'}</text><text className="node-caption" x={p.x} y={p.y+35} textAnchor="middle">{node.id}</text>
              {showInvestigations && group.open.length>0 && <g aria-hidden="true"><rect className="investigation-count-bg" x={p.x+12} y={p.y-33} width={32} height={20} rx={6}/><text className="investigation-count" x={p.x+28} y={p.y-19} textAnchor="middle">{group.open.length>99?'99+':group.open.length}</text></g>}
            </g>;
          })}
        </svg>
        </div>
        <div className="topology-legend"><span>→ Directed pipe</span><span className="path-key">Cyan: shortest path</span><span className="closed-key">Dashed ×: closed</span><span>Filled node: reachable · S: source · T: target</span><span>Numbered ring: open investigations · red: critical/high · amber: medium · blue: low · grey: unrated</span></div>
        <p className="helper pad">Markers use linked, authorized water cases and their recorded severity. No marker does not confirm normal service. Hydraulic result unavailable.</p>
        <div className="network-summary"><span><b>{nodes.length}</b> assets</span><span><b>{edges.length}</b> connections</span><span><b>Synthetic</b> schematic</span></div>
      </section>
      <section className="panel path-panel">
        <SectionHead eyebrow="CLOSURE SCENARIO" title="Can these assets connect?"/>
        <div className="form-fields">
          <label>From asset<select aria-label="From asset" value={source} onChange={e=>setSource(e.target.value)}>{nodes.map(n=><option key={n.id} value={n.id}>{n.name}</option>)}</select></label>
          <label>To asset<select aria-label="To asset" value={target} onChange={e=>setTarget(e.target.value)}>{nodes.map(n=><option key={n.id} value={n.id}>{n.name}</option>)}</select></label>
          <p className="helper">Results recalculate after each change. A zone filter limits traversal to that zone; hidden zones cannot provide a bypass.</p>
          <div aria-live="polite" data-testid="network-result">
            {error ? <ErrorBox error={error} retry={()=>{setResponse(null);setRequestRevision(value=>value+1);}}/> : !result ? <p>Calculating connection…</p> : <>
              <Badge type={result.connected?'teal':'amber'}>{result.connected?'Connected':'No directed connection'}</Badge>
              <h3>{result.distance_m===null?'Target is unreachable':`${fmt(result.distance_m)} m configured path`}</h3>
              <p>{result.path.length?result.path.map(label).join(' → '):'No open directed path exists in this authorized view.'}</p>
              <p><strong>{result.reachable.length} other assets reachable</strong> from {label(source)}.</p>
              <ul>{result.reachable.map(id=><li key={id}>{label(id)}</li>)}</ul>
              {result.unreachable.length>0 && <p className="helper">Unreachable in this view: {result.unreachable.map(label).join(', ')}.</p>}
              <button className="text-button" onClick={()=>download({inputs:JSON.parse(query), result, provenance:'Synthetic topology', limitation:'Connectivity only; no hydraulic or customer impact inference'},'civicsignal-network-scenario.json')}><Download size={14}/>Export network scenario</button>
            </>}
          </div>
        </div>
      </section>
    </div>
    <section className="panel spaced topology-selection" aria-label="Selected network asset" data-testid="network-asset-details">
      <SectionHead title={selectedNode?.name || 'Select a network asset'}/>
      {selectedNode ? <><p>{selectedNode.type || selectedNode.kind} · {selectedNode.zone_id} · {selectedNode.id}</p><div className="topology-actions"><button className="button secondary" onClick={()=>setSource(selectedNode.id)}>Use as source</button><button className="button secondary" onClick={()=>setTarget(selectedNode.id)}>Use as target</button></div><div className="network-case-list"><label className="checkbox-label"><input type="checkbox" checked={includeFinished} onChange={e=>setIncludeFinished(e.target.checked)}/>Include resolved and closed cases</label><p>{selectedGroup?.open.length || 0} open · {selectedGroup?.all.length || 0} total authorized linked cases</p>{selectedCases.map(c=><button className="network-case-card" key={c.id} data-network-case-id={c.id} onClick={()=>select(c)}><strong>{c.title}</strong><span><Badge type={['critical','high'].includes(c.severity)?'red':c.severity==='medium'?'amber':'neutral'}>{statusName(c.severity)}</Badge><Badge>{statusName(c.status)}</Badge><span>{c.provenance} · Updated {date(c.updated_at)} {getDisplayTimezoneLabel()}</span></span><span>{c.summary}</span><span className="text-button">Open evidence passport →</span></button>)}{!selectedCases.length&&<p className="helper">{includeFinished?'No authorized cases are linked to this asset.':'No open linked investigations. This does not confirm normal service.'}</p>}</div><p className="helper">A closure scenario does not change case evidence, severity, workflow status or physical infrastructure.</p></> : <p className="helper">Choose a node on the schematic or an asset in the register.</p>}
    </section>
    <SavedNetworkScenarios inputs={{source,target,closed_edges:closed,zone_id:zone||null}} configurationHash={network.configuration_hash} onLoad={inputs=>{setZone(inputs.zone_id||'');setSource(inputs.source);setTarget(inputs.target);setClosed(inputs.closed_edges);setSelected(null)}}/>
    <section className="panel spaced"><SectionHead title="Pipe closure register"/><div className="table-scroll"><table><thead><tr><th>Pipe</th><th>Directed connection</th><th>Length</th><th>Scenario state</th></tr></thead><tbody>{edges.map(edge=><tr key={edge.id}><td>{edge.id}</td><td>{label(edge.source)} → {label(edge.target)}</td><td>{fmt(edge.length_m)} m</td><td><label className="checkbox-label"><input type="checkbox" aria-label={`Close ${edge.id} in scenario`} checked={isClosed(edge)} disabled={edge.open===false} onChange={()=>toggle(edge)}/>{edge.open===false?'Closed in configuration':isClosed(edge)?'Closed in scenario':'Open'}</label></td></tr>)}</tbody></table></div>{!edges.length&&<p className="helper pad">No connections exist inside this zone.</p>}</section>
    <section className="panel spaced"><SectionHead title="Network asset register"/><div className="table-scroll"><table><thead><tr><th>Asset</th><th>Type</th><th>Zone</th><th>Open investigations</th></tr></thead><tbody>{nodes.map(n=><tr key={n.id}><td><button className="text-button" onClick={()=>setSelected(n.id)}>{n.name}</button><small>{n.id}</small></td><td>{n.type || n.kind}</td><td>{n.zone_id}</td><td>{investigations.get(n.id)!.open.length}<small>{investigations.get(n.id)!.severity ? `Highest: ${statusName(investigations.get(n.id)!.severity!)}` : 'No open linked cases'}</small></td></tr>)}</tbody></table></div></section>
  </>;
}
