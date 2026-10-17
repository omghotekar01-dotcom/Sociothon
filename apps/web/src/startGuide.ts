/** Predictable navigation suggestions, not an AI response or report submission. */
export const civicDomains=['water','electricity','roads','drainage','waste','streetlights','general'] as const;
export type CivicDomain=typeof civicDomains[number];
export type GuideResult={title:string;detail:string;path:string};
export function reportPath(domain?:string):string{
 return domain&&civicDomains.some(d=>d===domain)?'/report?domain='+domain:'/report';
}
export function guideRequest(raw:string):GuideResult{
 const text=raw.toLowerCase().replace(/\s+/g,' ').trim();
 const domain:CivicDomain|undefined=
   /street\s?lights?|lamp\s?posts?|lamp\s?outage/.test(text)?'streetlights':
   /electric|power|voltage|blackout|transformer/.test(text)?'electricity':
   /drain|sewer|flood|waterlog/.test(text)?'drainage':
   /pothole|road|footpath|sidewalk/.test(text)?'roads':
   /garbage|trash|waste|rubbish|pickup/.test(text)?'waste':
   /water|leak|pipe|tap|supply|meter/.test(text)?'water':
   /infrastructure|facility|public building/.test(text)?'general':undefined;
 if(/\b(track|tracking|status|receipt|follow.up|my cases?|my reports?|submitted)\b/.test(text))
   return {title:'Track your report',detail:'See receipts, current status and any recorded follow-up.',path:'/reports'};
 if(/\b(demo|simulation|scenario|walkthrough|showcase)\b/.test(text))
   return {title:'Explore the live demo',detail:'Use the guided synthetic scenario—no real city systems are connected.',path:'/demo'};
 if(/\b(report|add|create|submit|file|complaint|problem|issue|leak|pothole|broken|overflow|outage)\b/.test(text))
   return {title:'Start a new report',detail:'Choose a location, describe the issue and submit it on the next screen. Nothing has been sent yet.',path:reportPath(domain)};
 if(domain)
   return {title:'Explore '+(domain==='streetlights'?'streetlight':domain)+' signals',detail:'Open the service workspace for recorded observations and investigations.',path:'/domains/'+domain};
 if(/\b(help|how|works|method|about)\b/.test(text))
   return {title:'How CivicSignal works',detail:'Learn what the prototype can—and cannot—verify.',path:'/about'};
 return {title:'Open your dashboard',detail:'View available cases, service signals and the next steps in one place.',path:'/overview'};
}
