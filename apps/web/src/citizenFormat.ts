export type CitizenLanguage = 'en' | 'mr';

export function citizenLanguage(value: unknown): CitizenLanguage {
  return value === 'mr' ? 'mr' : 'en';
}

export function citizenNumber(value: number, language: string): string {
  return new Intl.NumberFormat(language === 'mr' ? 'mr-IN-u-nu-deva' : 'en-IN').format(value);
}

export function citizenDate(value: string | undefined, language: string, timeZone = 'Asia/Kolkata'): string {
  const instant = value ? new Date(value) : null;
  if (!instant || !Number.isFinite(instant.getTime())) return language === 'mr' ? 'नोंद उपलब्ध नाही' : 'Not recorded';
  return new Intl.DateTimeFormat(language === 'mr' ? 'mr-IN-u-nu-deva' : 'en-IN', {
    timeZone: timeZone === 'UTC' ? 'UTC' : 'Asia/Kolkata',
    day: 'numeric', month: 'short', year: 'numeric', hour: '2-digit', minute: '2-digit',
  }).format(instant);
}

export function citizenRequestError(status: number | undefined, language: string, operation: 'report' | 'photo' | 'read' = 'report'): string {
  const messages: Record<number, [string, string]> = {
    400: ['Some details could not be accepted. Review the form and try again.', 'काही तपशील स्वीकारता आले नाहीत. माहिती तपासून पुन्हा प्रयत्न करा.'],
    401: ['Your sign-in has expired. Save your draft or recovery reference on this device, sign in again, then check its status before retrying.', 'आपला प्रवेश कालबाह्य झाला आहे. उपकरणावर मसुदा किंवा पुनर्प्राप्ती संदर्भ जतन करा, पुन्हा प्रवेश करा आणि पुन्हा पाठवण्यापूर्वी स्थिती तपासा.'],
    403: ['This account cannot access this report or action. Sign in with the account that submitted the report.', 'या खात्याला हा अहवाल किंवा कृती उपलब्ध नाही. अहवाल पाठवलेल्या खात्याने प्रवेश करा.'],
    404: ['This report could not be found. Refresh your report list and try again.', 'हा अहवाल सापडला नाही. अहवालांची यादी पुन्हा मिळवा आणि प्रयत्न करा.'],
    409: ['This submission reference already has different content. Check its status to recover the original receipt.', 'या संदर्भाने आधीच वेगळी माहिती पाठवली आहे. मूळ पावती मिळवण्यासाठी स्थिती तपासा.'],
    413: ['This photograph is too large. Choose a PNG or JPEG of at most 5 MB.', 'हे छायाचित्र खूप मोठे आहे. कमाल ५ MB चे PNG किंवा JPEG निवडा.'],
    415: ['This photograph format is not supported. Choose a valid PNG or JPEG.', 'या छायाचित्राचा प्रकार समर्थित नाही. वैध PNG किंवा JPEG निवडा.'],
    422: operation === 'photo'
      ? ['This photograph could not be accepted. Choose a valid PNG or JPEG of at most 5 MB.', 'हे छायाचित्र स्वीकारता आले नाही. कमाल ५ MB चे वैध PNG किंवा JPEG निवडा.']
      : ['Review the category, service zone, location and observation. If an asset is selected, it must belong to that zone.', 'प्रकार, सेवा क्षेत्र, ठिकाण आणि निरीक्षण तपासा. मालमत्ता निवडली असल्यास ती त्याच सेवा क्षेत्रातील असावी.'],
    429: ['Too many attempts. Keep this report and wait a minute before trying again.', 'खूप प्रयत्न झाले आहेत. हा अहवाल जतन ठेवा आणि एका मिनिटानंतर पुन्हा प्रयत्न करा.'],
  };
  const fallback: [string, string] = operation === 'read'
    ? ['Reports could not be loaded. Check your connection and try again; your saved reports remain on the server.', 'अहवाल मिळवता आले नाहीत. जोडणी तपासून पुन्हा प्रयत्न करा; जतन केलेले अहवाल सर्व्हरवर आहेत.']
    : ['Confirmation is unavailable. Check the submission status before retrying the same report.', 'पुष्टी उपलब्ध नाही. तोच अहवाल पुन्हा पाठवण्यापूर्वी स्थिती तपासा.'];
  return (messages[status || 0] || fallback)[language === 'mr' ? 1 : 0];
}

export function isReportReceipt(value: unknown): value is {id: string; case_id: string; receipt: string; status: string; created_at: string; domain: string} {
  if (!value || typeof value !== 'object') return false;
  const receipt = value as Record<string, unknown>;
  return ['id', 'case_id', 'receipt', 'status', 'created_at', 'domain'].every(key => typeof receipt[key] === 'string' && receipt[key] !== '');
}
