export type WaterCase = {id:string;domain?:string;evidence?:Record<string,unknown>;evidence_records?:Array<{id?:string;kind?:string;created_at?:string}>};
export type InvestigationCheck = {topic:string;available:string;next:string;sources:string[]};

export function waterInvestigation(record:WaterCase, mr=false):InvestigationCheck[] {
  if(record.domain!=='water')return [];
  const t=(en:string,marathi:string)=>mr?marathi:en;
  const evidence=record.evidence||{};
  const finite=(key:string)=>typeof evidence[key]==='number'&&Number.isFinite(evidence[key]);
  const records=record.evidence_records||[];
  const inspections=records.filter(r=>r.kind==='inspection');
  const reviews=records.filter(r=>r.kind==='water_review');
  const interventions=records.filter(r=>r.kind==='intervention');
  const latestIntervention=Math.max(...interventions.map(r=>Date.parse(r.created_at||'')));
  const followups=records.filter(r=>r.kind==='follow_up'&&Number.isFinite(latestIntervention)&&Date.parse(r.created_at||'')>latestIntervention);
  const ids=(values:typeof records)=>values.map(r=>r.id).filter((id):id is string=>!!id);
  return [
    {topic:t('Consumption pattern','वापराची पद्धत'),available:finite('observed')&&finite('expected')?t('Observed and historical expected quantities are attached.','नोंदवलेले व ऐतिहासिक अपेक्षित प्रमाण जोडले आहे.'):t('Comparable observed and expected quantities are not attached.','तुलनेसाठी नोंदवलेले व अपेक्षित प्रमाण जोडलेले नाही.'),next:t('Compare original intervals, units, coverage and meter identity before interpreting excess.','अतिरिक्त वापराचा अर्थ लावण्यापूर्वी मूळ कालावधी, एकके, माहितीची व्याप्ती आणि मीटर तपासा.'),sources:[record.id]},
    {topic:t('Operating context','पुरवठ्याचा संदर्भ'),available:(reviews.length?t('A saved operations review is attached. It records the reviewed configuration and observations, not proof of historical supply.','जतन केलेला पुरवठा आढावा जोडला आहे. त्यात तपासलेली संरचना व मोजमापे आहेत; ऐतिहासिक पुरवठ्याचा पुरावा नाही.'):t('A current zone schedule alone does not establish the schedule at the time of this case.','सध्याचे क्षेत्रीय वेळापत्रक या घटनेच्या वेळचे वेळापत्रक सिद्ध करत नाही.')),next:t('Review the event window against documented supply changes, legitimate demand and tank-refilling records.','घटनेच्या कालावधीतील पुरवठ्याचे बदल, वैध मागणी आणि टाकी भरण्याच्या नोंदी तपासा.'),sources:reviews.length?ids(reviews):[record.id]},
    {topic:t('Field evidence','स्थळावरील पुरावा'),available:inspections.length?t('Inspection records are available; review their findings.','तपासणीच्या नोंदी उपलब्ध आहेत; निष्कर्ष तपासा.'):t('No inspection record is attached.','तपासणीची नोंद जोडलेली नाही.'),next:t('An authorized inspector should document observations and alternative explanations; a photograph alone does not establish leak volume.','अधिकृत निरीक्षकाने निरीक्षणे आणि पर्यायी स्पष्टीकरणे नोंदवावीत; केवळ छायाचित्र गळतीचे प्रमाण सिद्ध करत नाही.'),sources:inspections.length?ids(inspections):[record.id]},
    {topic:t('Intervention follow-up','कार्यवाहीनंतरचा पाठपुरावा'),available:followups.length?t('A follow-up record is dated after the latest recorded intervention.','नवीनतम कार्यवाहीनंतरची पाठपुरावा नोंद उपलब्ध आहे.'):t('No dated follow-up after the latest intervention is established by these records.','या नोंदींमधून नवीनतम कार्यवाहीनंतरचा दिनांकित पाठपुरावा सिद्ध होत नाही.'),next:t('Compare equivalent periods and supply conditions. Missing readings are not improvement; an authorized person must review closure.','समतुल्य कालावधी व पुरवठा परिस्थितीची तुलना करा. गहाळ मोजमाप म्हणजे सुधारणा नाही; प्रकरण बंद करण्यासाठी अधिकृत पुनरावलोकन आवश्यक आहे.'),sources:followups.length?ids(followups):[record.id]},
  ];
}
