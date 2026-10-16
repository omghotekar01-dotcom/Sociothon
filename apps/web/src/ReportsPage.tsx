import {useCallback,useEffect,useRef,useState} from 'react';
import {BookOpen,ChevronRight,Download,MapPin,Plus,RefreshCw,Users,X} from 'lucide-react';
import {api,ApiError,type Bootstrap,type CivicCase,download,getDisplayTimezone,getDisplayTimezoneLabel} from './api';
import {Badge,DomainIcon,Empty,KeyValue,SectionHead,Stat,domainInfo} from './components';
import {citizenDomains,citizenStatus,useCitizenLanguage} from './citizenLanguage';
import {citizenDate,citizenNumber,citizenRequestError,isReportReceipt} from './citizenFormat';
import {PhotoUpload} from './PhotoUpload';

type Report = {id:string;case_id:string;receipt:string;title:string;description:string;location:string;domain:string;status:string;created_at:string;timeline?:{action:string;created_at:string;status?:string}[]};
type ReadFailure = {status?:number};
function isReport(value:unknown):value is Report {
  if(!isReportReceipt(value))return false;
  const item=value as Record<string,unknown>;
  return ['title','description','location'].every(key=>typeof item[key]==='string');
}

export function ReportsPage({go,user}:{user:Bootstrap['user'];select?:(item:CivicCase)=>void;go:(path:string)=>void}) {
  const {mr,t,language,setLanguage}=useCitizenLanguage(user);
  const [reports,setReports]=useState<Report[]|null>(null);
  const [detail,setDetail]=useState<Report|null>(null);
  const [loading,setLoading]=useState(false);
  const [opening,setOpening]=useState<string|null>(null);
  const [listError,setListError]=useState<ReadFailure|null>(null);
  const [detailError,setDetailError]=useState<ReadFailure|null>(null);
  const tracking=useRef<HTMLElement>(null);
  const lastTrigger=useRef<HTMLButtonElement|null>(null);
  const load=useCallback(async(signal?:AbortSignal)=>{
    setLoading(true);setListError(null);
    try {
      const result=await api('/reports',{signal});
      const items=Array.isArray(result)?result:result.reports;
      if(!Array.isArray(items)||!items.every(isReport))throw new Error('Unreadable reports');
      if(!signal?.aborted)setReports(items);
    }catch(error){if(!signal?.aborted)setListError({status:error instanceof ApiError?error.status:undefined});}
    finally{if(!signal?.aborted)setLoading(false);}
  },[user.id]);
  useEffect(()=>{const controller=new AbortController();void load(controller.signal);return()=>controller.abort();},[load]);
  useEffect(()=>{if(detail)tracking.current?.focus();},[detail]);
  const open=async(report:Report,trigger:HTMLButtonElement)=>{
    setOpening(report.id);setDetailError(null);lastTrigger.current=trigger;
    try{const result=await api('/reports/'+encodeURIComponent(report.id));if(!isReport(result))throw new Error('Unreadable report');if(!Array.isArray(result.timeline))throw new Error('Unreadable timeline');setDetail(result);}
    catch(error){setDetailError({status:error instanceof ApiError?error.status:undefined});}
    finally{setOpening(null);}
  };
  const formattedDate=(value:string)=>citizenDate(value,language,getDisplayTimezone())+' · '+getDisplayTimezoneLabel();
  return <div className="panel" lang={language}>
    <button className="button secondary" onClick={()=>setLanguage(mr?'en':'mr')} aria-label={t('Switch reporting language to Marathi','अहवालाची भाषा इंग्रजी करा')}>{mr?'English':'मराठी'}</button>
    <SectionHead title={t('Your reports, with a clear next step','आपले अहवाल आणि पुढील पाऊल')}>
      <button className="button secondary" disabled={loading} onClick={()=>void load()}><RefreshCw size={15}/>{t('Refresh reports','अहवाल पुन्हा मिळवा')}</button>
      <button className="button primary" onClick={()=>go('/report')}><Plus size={15}/>{t('New report','नवीन अहवाल')}</button>
    </SectionHead>
    {listError&&<div className="error" role="alert"><span>{citizenRequestError(listError.status,language,'read')}</span><button className="text-button" disabled={loading} onClick={()=>void load()}>{t('Try again','पुन्हा प्रयत्न करा')}</button></div>}
    {detailError&&<div className="error" role="alert"><span>{citizenRequestError(detailError.status,language,'read')}</span><span>{t('Select the report again to retry tracking.','पाठपुरावा पुन्हा मिळवण्यासाठी अहवाल पुन्हा निवडा.')}</span></div>}
    {loading&&<p className="helper" role="status">{t('Loading your reports…','आपले अहवाल मिळवत आहे…')}</p>}
    {reports&&reports.length===0&&!listError&&<Empty title={t('Your first observation can make a difference','आपले पहिले निरीक्षण बदल घडवू शकते')} text={t('Report a local infrastructure issue and track its review here.','स्थानिक सुविधेची समस्या नोंदवा आणि तिचा पाठपुरावा येथे पहा.')}/>}
    {reports&&reports.length>0&&<div className="report-list" aria-label={t('Your reports','आपले अहवाल')}>
      {reports.map(report=><button key={report.id} disabled={opening!==null} aria-expanded={detail?.id===report.id} aria-controls={detail?.id===report.id?'report-tracking':undefined} onClick={event=>void open(report,event.currentTarget)}>
        <span className="report-icon"><DomainIcon id={report.domain} size={23}/></span>
        <div><strong>{report.title}</strong><p>{report.description}</p><small>{report.receipt} · {t('Submitted','पाठवले')} {formattedDate(report.created_at)}</small>{opening===report.id&&<span role="status">{t('Loading tracking…','पाठपुरावा मिळवत आहे…')}</span>}</div>
        <Badge type="cyan">{citizenStatus(report.status,mr)}</Badge><ChevronRight size={17}/>
      </button>)}
    </div>}
    {detail&&<section id="report-tracking" ref={tracking} tabIndex={-1} aria-label={t('Report tracking','अहवालाचा पाठपुरावा')} className="panel spaced report-tracking">
      <SectionHead title={detail.title}><button className="button secondary" onClick={()=>{setDetail(null);lastTrigger.current?.focus();}}>{t('Close tracking','पाठपुरावा बंद करा')}<X size={14}/></button></SectionHead>
      <Badge type="cyan">{detail.receipt}</Badge><p>{detail.description}</p>
      <KeyValue label={t('Category','प्रकार')} value={mr?citizenDomains[detail.domain]:domainInfo(detail.domain).name}/>
      <KeyValue label={t('Current status','सध्याची स्थिती')} value={citizenStatus(detail.status,mr)}/>
      <KeyValue label={t('Submitted','पाठवले')} value={formattedDate(detail.created_at)}/>
      <KeyValue label={t('Submitted location','नोंदवलेले ठिकाण')} value={detail.location}/>
      <p className="helper">{t('Your observation remains as written. A report does not confirm a fault or promise a repair deadline.','आपले निरीक्षण जसे लिहिले आहे तसेच ठेवले आहे. अहवालामुळे दोष सिद्ध होत नाही किंवा दुरुस्तीची मुदत निश्चित होत नाही.')}</p>
      <div className="audit-timeline">{detail.timeline?.map((event,index)=><div key={index}><small>{formattedDate(event.created_at)}</small><h3>{citizenStatus(event.action,mr)}</h3>{event.status&&<Badge>{citizenStatus(event.status,mr)}</Badge>}</div>)}</div>
      <button className="text-button" onClick={()=>download({...detail,language,status_label:citizenStatus(detail.status,mr),submitted_label:formattedDate(detail.created_at),display_timezone:getDisplayTimezone()},'civicsignal-report-receipt.json')}><Download size={14}/>{t('Download receipt','पावती डाउनलोड करा')}</button>
      <PhotoUpload key={user.id+'-'+detail.case_id} userId={user.id} caseId={detail.case_id} t={t}/>
    </section>}
  </div>;
}

export function CitizenHome({data,go}:{data:Bootstrap;go:(path:string)=>void}) {
  const {t,language}=useCitizenLanguage(data.user);
  return <div lang={language}>
    <div className="domain-hero"><div className="domain-hero-icon"><Users size={30}/></div><div>
      <span className="eyebrow">{t('YOUR NEIGHBOURHOOD. YOUR OBSERVATIONS.','आपला परिसर. आपले निरीक्षण.')}</span>
      <h2>{t('Hello, ','नमस्कार, ')}{data.user.name?.split(' ')[0]}.</h2>
      <p>{t('Report what you safely observe, follow its progress, and help your local team understand the issue.','सुरक्षितपणे पाहिलेली माहिती नोंदवा, तिचा पाठपुरावा करा आणि स्थानिक विभागाला समस्या समजण्यास मदत करा.')}</p>
    </div><button className="button primary" onClick={()=>go('/report')}>{t('Report a problem','समस्या नोंदवा')}<Plus size={16}/></button></div>
    <div className="metrics-strip"><Stat label={t('Your reports','आपले अहवाल')} value={citizenNumber(data.metrics.reports??0,language)} note={t('Private to your account and authorized staff','फक्त आपले खाते आणि अधिकृत कर्मचाऱ्यांना उपलब्ध')} icon={BookOpen}/><Stat label={t('Service zones','सेवा क्षेत्रे')} value={citizenNumber(data.zones.length,language)} note={t('Synthetic local demonstration city','स्थानिक प्रात्यक्षिकासाठी कृत्रिम शहर')} icon={MapPin}/></div>
    <ReportsPage user={data.user} go={go}/>
  </div>;
}
