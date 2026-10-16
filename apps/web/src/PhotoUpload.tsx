import {useEffect,useRef,useState} from 'react';
import {api,ApiError,upload} from './api';
import {parsePhotoReference,photoHash,type PhotoReference} from './photoRecovery';
import {citizenRequestError} from './citizenFormat';

type Receipt={id:string;url:string};
type Props={userId:string;caseId:string;t:(english:string,marathi:string)=>string};

export function PhotoUpload({userId,caseId,t}:Props) {
  const storageKey='civic-photo-pending-'+userId+'-'+caseId;
  const [initial]=useState(()=>{
    try {const raw=localStorage.getItem(storageKey);return {reference:raw?parsePhotoReference(raw):null,failed:false};}
    catch {return {reference:null,failed:true};}
  });
  const [pending,setPending]=useState<PhotoReference|null>(initial.reference);
  const [consent,setConsent]=useState(!!initial.reference);
  const [storageError,setStorageError]=useState(initial.failed);
  const [photo,setPhoto]=useState<File|null>(null);
  const [busy,setBusy]=useState(false);
  const [online,setOnline]=useState(navigator.onLine);
  const [error,setError]=useState('');
  const [checked,setChecked]=useState(false);
  const [receipt,setReceipt]=useState<Receipt|null>(null);
  const input=useRef<HTMLInputElement>(null);
  useEffect(()=>{
    const changed=()=>setOnline(navigator.onLine);
    window.addEventListener('online',changed);window.addEventListener('offline',changed);
    return()=>{window.removeEventListener('online',changed);window.removeEventListener('offline',changed);};
  },[]);
  const save=(value:PhotoReference)=>{
    try{localStorage.setItem(storageKey,JSON.stringify(value));setStorageError(false);}
    catch{setStorageError(true);}
  };
  const remove=()=>{
    try{localStorage.removeItem(storageKey);setStorageError(false);return true;}
    catch{setStorageError(true);return false;}
  };
  const confirmed=(value:Receipt)=>{
    setReceipt(value);setPending(null);setPhoto(null);setChecked(false);setError('');
    if(input.current)input.current.value='';
    if(consent)remove();
  };
  const lookup=async(reference:PhotoReference)=>{
    const result=await api('/cases/'+caseId+'/evidence/submissions/'+encodeURIComponent(reference.key));
    if(result.evidence){confirmed(result.evidence);return true;}
    setChecked(true);return false;
  };
  const check=async()=>{
    if(!pending)return;
    setBusy(true);setError('');
    try{await lookup(pending);}
    catch{setError(t('Cannot check this upload yet. Keep its reference and try again when connected and signed in.','सध्या अपलोड तपासता येत नाही. संदर्भ जतन ठेवा; जोडणी आणि प्रवेश मिळाल्यावर पुन्हा तपासा.'));}
    finally{setBusy(false);}
  };
  const select=async(file:File|null)=>{
    if(!file)return;
    setBusy(true);setError('');
    try{
      if(file.size>5*1024*1024||!(/\.(png|jpe?g)$/i.test(file.name))){
        setError(t('Choose a PNG or JPEG photograph of at most 5 MB.','कमाल ५ MB चे PNG किंवा JPEG छायाचित्र निवडा.'));return;
      }
      if(pending && await photoHash(file)!==pending.hash){
        setError(t('This is a different file. Select the exact original photograph to retry this pending upload.','ही वेगळी फाइल आहे. प्रलंबित अपलोड पुन्हा पाठवण्यासाठी मूळ छायाचित्राची तीच फाइल निवडा.'));return;
      }
      setPhoto(file);setReceipt(null);
    }catch{setError(t('The photograph could not be read. Select it again.','छायाचित्र वाचता आले नाही. ते पुन्हा निवडा.'));}
    finally{if(input.current)input.current.value='';setBusy(false);}
  };
  const submit=async()=>{
    if(!photo||!online)return;
    setBusy(true);setError('');
    try{
      if(pending && await lookup(pending))return;
      const reference=pending||{schema:1 as const,key:crypto.randomUUID(),hash:await photoHash(photo)};
      setPending(reference);setChecked(false);if(consent)save(reference);
      confirmed(await upload('/cases/'+caseId+'/evidence',photo,'Citizen observation',reference.key));
    }catch(error){
      if(error instanceof ApiError && [400,413,415,422,429].includes(error.status)){
        setPending(null);if(consent)remove();
        setError(t(citizenRequestError(error.status,'en','photo'),citizenRequestError(error.status,'mr','photo')));
      }else if(error instanceof ApiError&&[401,403,409].includes(error.status))setError(t(citizenRequestError(error.status,'en','photo'),citizenRequestError(error.status,'mr','photo')));
      else setError(t('Upload not confirmed. Check its status or retry the same photograph; nothing is sent automatically.','अपलोडची पुष्टी मिळाली नाही. स्थिती तपासा किंवा तेच छायाचित्र पुन्हा पाठवा; काहीही आपोआप पाठवले जात नाही.'));
    }finally{setBusy(false);}
  };
  return <div className="photo-upload form-fields" data-testid="photo-upload">
    <h3>{t('Private photograph','खाजगी छायाचित्र')}</h3>
    <p className="helper" role="status">{online?t('Connected. Uploading requires your action.','जोडणी उपलब्ध आहे. आपल्या कृतीनंतरच अपलोड होते.'):t('Offline. Keep this page open to retain the selected photograph. Reconnect before uploading.','जोडणी नाही. निवडलेले छायाचित्र ठेवण्यासाठी हे पृष्ठ उघडे ठेवा. अपलोड करण्यापूर्वी पुन्हा जोडणी करा.')}</p>
    {storageError&&<p role="alert" className="field-note-error">{t('The recovery reference could not be read, saved or removed on this device. Keep this page open. An existing unreadable copy is retained until you clear it.','या उपकरणावरील पुनर्प्राप्ती संदर्भ वाचता, जतन करता किंवा काढता आला नाही. हे पृष्ठ उघडे ठेवा. न वाचता येणारी जुनी प्रत आपण काढेपर्यंत तशीच राहते.')}</p>}
    {pending&&<div className="info-banner" data-testid="pending-photo"><div>
      <strong>{t('Photograph awaiting confirmation','छायाचित्राची पुष्टी प्रलंबित')}</strong>
      <p>{t('Check the server first. After reopening tracking, select the exact original file only if an upload retry is needed.','प्रथम सर्व्हरवर तपासा. पाठपुरावा पुन्हा उघडल्यानंतर अपलोडची गरज असेल तरच मूळ फाइल पुन्हा निवडा.')}</p>
      <button className="button secondary" disabled={busy||!online} onClick={check}>{t('Check photograph status','छायाचित्राची स्थिती तपासा')}</button>
      {checked&&<p>{t('No saved photograph was found for this upload. Select the original file and retry.','या अपलोडचे जतन केलेले छायाचित्र सापडले नाही. मूळ फाइल निवडून पुन्हा प्रयत्न करा.')}</p>}
    </div></div>}
    <label>{t('Add a private photograph','खाजगी छायाचित्र जोडा')}<input ref={input} type="file" accept="image/png,image/jpeg" disabled={busy||initial.failed&&storageError} onChange={e=>void select(e.target.files?.[0]||null)}/></label>
    {photo&&<p className="helper">{t('Selected: ','निवडले: ')}{photo.name}</p>}
    <p className="helper">{t('PNG or JPEG, up to 5 MB. Photos stay private; image metadata is removed. Only capture evidence from a safe position.','PNG किंवा JPEG, कमाल ५ MB. छायाचित्र खाजगी राहते; त्यातील मेटाडेटा काढला जातो. सुरक्षित ठिकाणाहूनच छायाचित्र घ्या.')}</p>
    <label className="checkbox-label"><input type="checkbox" disabled={busy||initial.failed&&storageError} checked={consent} onChange={e=>{setConsent(e.target.checked);if(e.target.checked&&pending)save(pending);else if(!e.target.checked)remove();}}/>{t('Keep an upload recovery reference on this device','या उपकरणावर अपलोडचा पुनर्प्राप्ती संदर्भ ठेवा')}</label>
    <p className="helper">{t('Only an upload identifier and file fingerprint are saved with your consent. The image and filename are never saved in browser storage. Closing tracking discards the selected file; a saved reference lets you check the server after reopening.','आपल्या संमतीने फक्त अपलोड क्रमांक आणि फाइलचा डिजिटल ठसा जतन होतो. छायाचित्र आणि फाइलचे नाव ब्राउझरमध्ये जतन होत नाही. पाठपुरावा बंद केल्यावर निवडलेली फाइल निघून जाते; संदर्भ जतन असल्यास पुन्हा उघडल्यावर सर्व्हरवर तपासता येते.')}</p>
    {error&&<p role="alert" className="field-note-error">{error}</p>}
    <button className="button secondary" disabled={!photo||busy||!online} onClick={submit}>{busy?t('Checking / uploading…','तपासत / अपलोड करत आहे…'):pending?t('Retry same photograph','तेच छायाचित्र पुन्हा पाठवा'):t('Submit private photograph','खाजगी छायाचित्र पाठवा')}</button>
    {receipt&&<div role="status"><p>{t('Photograph synchronized with server.','छायाचित्र सर्व्हरवर जतन झाले.')}</p><a className="text-button" href={receipt.url} target="_blank" rel="noreferrer">{t('View saved photograph','जतन केलेले छायाचित्र पहा')}</a></div>}
    {(pending||storageError)&&<div><p className="helper">{t('Clearing the reference does not delete a photograph from the server. Check its status before starting a new upload.','संदर्भ काढल्याने सर्व्हरवरील छायाचित्र काढले जात नाही. नवीन अपलोडपूर्वी त्याची स्थिती तपासा.')}</p><button className="text-button" disabled={busy} onClick={()=>{if(remove()){setPending(null);setPhoto(null);setConsent(false);setChecked(false);setError('');}}}>{t('Clear device upload reference','उपकरणावरील अपलोड संदर्भ काढा')}</button></div>}
  </div>;
}
