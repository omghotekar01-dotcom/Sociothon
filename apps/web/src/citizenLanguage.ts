import {useEffect,useState} from 'react';
import {citizenLanguage,type CitizenLanguage} from './citizenFormat';

export function storeCitizenLanguage(userId: string, value: string) {
  const language = citizenLanguage(value);
  try {sessionStorage.setItem('civic-language-' + userId, language);} catch {}
  try {localStorage.setItem('civic-interface-language-' + userId, language);} catch {}
  window.dispatchEvent(new CustomEvent('civic-language-change', {detail: {userId, language}}));
}

export function useCitizenLanguage(user: {id: string, settings?: {language?: string}}) {
  const key = 'civic-language-' + user.id;
  const [language, update] = useState<CitizenLanguage>(() => {
    try {return citizenLanguage(sessionStorage.getItem(key) || localStorage.getItem('civic-interface-language-' + user.id) || user.settings?.language);} catch {return citizenLanguage(user.settings?.language);}
  });
  useEffect(() => {
    const changed = (event: Event) => {const detail = (event as CustomEvent).detail;if (detail?.userId === user.id) update(citizenLanguage(detail.language));};
    window.addEventListener('civic-language-change', changed);
    return () => window.removeEventListener('civic-language-change', changed);
  }, [user.id]);
  const setLanguage = (value: string) => {update(citizenLanguage(value));storeCitizenLanguage(user.id, value);};
  return {language, setLanguage, mr: language === 'mr', t: (en: string, mr: string) => language === 'mr' ? mr : en};
}

const statusTranslations: Record<string, string> = {
  needs_review: 'पुनरावलोकन आवश्यक', investigating: 'तपास सुरू आहे', assigned: 'कर्मचारी नेमले आहेत',
  intervention: 'कार्यवाही सुरू आहे', monitoring: 'पाठपुरावा सुरू आहे', resolved: 'निराकरण नोंदवले', closed: 'प्रकरण बंद केले',
  reported: 'अहवाल प्राप्त झाला', report_created: 'अहवाल प्राप्त झाला', report_submitted: 'अहवाल प्राप्त झाला', transition: 'स्थिती बदलली',
  assignment: 'कर्मचारी नेमणूक', inspection: 'स्थळ तपासणी नोंदवली', follow_up: 'पाठपुरावा नोंदवला',
  evidence_added: 'पुरावा जोडला', report_linked: 'अहवाल प्रकरणाशी जोडला', report_corroboration: 'संबंधित निरीक्षण जोडले',
};
export function citizenStatus(value: string, mr: boolean) {
  return mr ? statusTranslations[value] || 'प्रकरण अद्ययावत केले' : value.replaceAll('_', ' ').replace(/^./, c => c.toUpperCase());
}
export const citizenDomains: Record<string, string> = {water:'पाणी', electricity:'वीज', roads:'रस्ते', drainage:'निचरा', waste:'कचरा', streetlights:'पथदिवे', general:'इतर पायाभूत सुविधा'};
