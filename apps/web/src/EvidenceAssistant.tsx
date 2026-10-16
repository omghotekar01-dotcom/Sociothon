import {useState} from 'react';
import {Sparkles} from 'lucide-react';
import {Badge} from './components';
import {evidenceQuestions, explainCase, type EvidenceQuestion} from './caseExplanation';
import {waterInvestigation} from './waterInvestigation';
import {useInterfaceLanguage} from './uiLanguage';

export function EvidenceAssistant({detail}:{detail:any}) {
  const [question,setQuestion]=useState<EvidenceQuestion>('summary');
  const answer=explainCase(detail,question);
  const mr=useInterfaceLanguage()==='mr';
  const checks=waterInvestigation(detail,mr);

  return <section className="evidence-assistant" aria-labelledby="evidence-assistant-title">
    <div className="assistant-intro">
      <span className="assistant-mark"><Sparkles size={17}/></span>
      <div><h3 id="evidence-assistant-title">Evidence assistant</h3><p>Choose a review question. Answers use only this case’s authorized records.</p></div>
      <Badge type="violet">Deterministic</Badge>
    </div>
    <div className="assistant-questions" role="group" aria-label="Evidence review questions">
      {evidenceQuestions.map(item=><button key={item.id} className={question===item.id?'active':''} aria-pressed={question===item.id} onClick={()=>setQuestion(item.id)}>{item.label}</button>)}
    </div>
    {checks.length>0&&<details><summary>{mr?'पाणी तपासणीतील पुराव्याची उणीव':'Water investigation: evidence gaps and next checks'}</summary><div className="table-scroll"><table><thead><tr><th>{mr?'विषय':'Topic'}</th><th>{mr?'उपलब्ध पुरावा':'Available evidence'}</th><th>{mr?'पुढील तपासणी':'Next check'}</th><th>{mr?'स्रोत':'Sources'}</th></tr></thead><tbody>{checks.map(check=><tr key={check.topic}><td>{check.topic}</td><td>{check.available}</td><td>{check.next}</td><td>{check.sources.map(id=><code key={id}>{id} </code>)}</td></tr>)}</tbody></table></div></details>}
    <div className="assistant-answer" aria-live="polite">
      <h4>{answer.title}</h4>
      <ul>{answer.points.map((point,index)=><li key={index}>{point}</li>)}</ul>
      <div className="assistant-sources"><strong>Source IDs</strong>{answer.sources.map(source=><span key={source.id}><code>{source.id}</code> {source.label}</span>)}</div>
      <p className="helper">{answer.caveat}</p>
    </div>
  </section>;
}
