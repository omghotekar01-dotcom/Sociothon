import type {CivicCase} from './api';

/**
 * Deterministic administrative review guidance for authorised synthetic demo cases.
 * A score is NOT a public-safety forecast, repair verification or automated dispatch.
 */
export type ReviewBand='High priority review'|'Review next'|'Routine follow-up';
export type ReviewSuggestion={case:CivicCase;score:number;band:ReviewBand;reasons:string[]};

const finalStatuses=new Set(['resolved','closed']);

export function rankCasesForReview(cases:readonly CivicCase[],nowMs=Date.now()):ReviewSuggestion[]{
  return cases.filter(c=>!finalStatuses.has(c.status.toLowerCase())).map(c=>{
    let score=0;
    const reasons:string[]=[];
    const severity=c.severity.toLowerCase();
    if(severity==='critical'){score+=5;reasons.push('Critical severity flag')}
    else if(severity==='high'){score+=3;reasons.push('High severity flag')}
    else if(severity==='medium')score+=1;

    const due=c.deadline_at?Date.parse(c.deadline_at):NaN;
    if(Number.isFinite(due)&&Number.isFinite(nowMs)){
      if(due<nowMs){score+=3;reasons.push('Administrative review target overdue')}
      else if(due-nowMs<=86_400_000){score+=1;reasons.push('Review target within 24 hours')}
    }

    const created=Date.parse(c.created_at);
    if(Number.isFinite(created)&&nowMs>created){
      const ageDays=(nowMs-created)/86_400_000;
      if(ageDays>=7){score+=2;reasons.push('Open for at least 7 days')}
      else if(ageDays>=2){score+=1;reasons.push('Open for at least 2 days')}
    }

    if(c.status.toLowerCase().includes('reopen')){score+=2;reasons.push('Previously reopened')}
    if(!c.assigned_to){score+=1;reasons.push('No assigned reviewer')}
    if(reasons.length===0)reasons.push('Standard human review');

    const band:ReviewBand=score>=7?'High priority review':score>=4?'Review next':'Routine follow-up';
    return {case:c,score,band,reasons};
  }).sort((a,b)=>b.score-a.score||a.case.id.localeCompare(b.case.id));
}
