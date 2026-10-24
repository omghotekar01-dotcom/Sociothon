/** Presentation-only evidence classification; never a leak detector or repair claim. */
export type FollowupCategory='insufficient'|'observed_reduction'|'no_clear_change'|'increased';
export function classifyWaterFollowup(result:{status:string;before_total_l:number|null;after_total_l:number|null;issues:string[]}):{
  category:FollowupCategory;label:string;reason:string
}{
  const {before_total_l:before,after_total_l:after,status,issues}=result;
  if(status!=='comparison_available'||issues.length||before===null||after===null||!Number.isFinite(before)||!Number.isFinite(after)||before<=0||after<0)
    return {category:'insufficient',label:'Insufficient evidence',reason:'Complete, valid and comparable interval readings are required before interpreting change.'};
  const change=(before-after)/before;
  // A 2% descriptive band avoids framing rounding differences as meaningful changes.
  // This is NOT a statistical confidence interval or proof of causality.
  if(change>=0.02)return {category:'observed_reduction',label:'Observed improvement in recorded volume',reason:'Recorded volume decreased by at least 2% in the matched windows. This does not establish leakage reduction, repairs or causal savings.'};
  if(change<=-0.02)return {category:'increased',label:'No observed improvement',reason:'Recorded volume increased by at least 2% in the matched windows. Review changes in demand, supply schedules and storage.'};
  return {category:'no_clear_change',label:'No clear change',reason:'The recorded difference is within a 2% descriptive band. This is not a statistical significance test.'};
}
