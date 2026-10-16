"""Domain-specific manual observations; never inferred from photographs."""
import math
from fastapi import HTTPException


def text(key, label, mr):
    return {"key":key,"label":label,"mr":mr,"type":"text","max_length":500}


def number(key, label, mr, unit, maximum):
    return {"key":key,"label":label,"mr":mr,"type":"number","unit":unit,"minimum":0,"maximum":maximum}


SCHEMAS = {
    "water":[text("observed_condition","Observed water condition","पाण्याची प्रत्यक्ष स्थिती"),text("supply_context","Supply / tank-refilling context","पुरवठा / टाकी भरण्याचा संदर्भ"),number("measured_volume_l","Manually measured volume","प्रत्यक्ष मोजलेले प्रमाण","L",1e9),number("measurement_minutes","Measurement duration","मोजमापाचा कालावधी","min",1440),text("measurement_method","Measurement method and limitations","मोजण्याची पद्धत व मर्यादा")],
    "roads":[text("damage_category","Damage category","नुकसानीचा प्रकार"),number("measured_length_m","Manually measured length","प्रत्यक्ष मोजलेली लांबी","m",100000),number("measured_width_m","Manually measured width","प्रत्यक्ष मोजलेली रुंदी","m",1000),number("measured_depth_mm","Manually measured depth","प्रत्यक्ष मोजलेली खोली","mm",10000),text("proposed_treatment","Proposed treatment / recorded action","प्रस्तावित उपाय / नोंदवलेली कार्यवाही")],
    "drainage":[text("observed_obstruction","Observed obstruction or overflow","प्रत्यक्ष अडथळा किंवा ओसंडणे"),number("observed_level_cm","Measured water level","मोजलेली पाण्याची पातळी","cm",100000),text("clearance_record","Clearance and disposal record","सफाई व विल्हेवाटीची नोंद"),text("followup_condition","Follow-up drainage condition","पाठपुराव्यातील निचऱ्याची स्थिती")],
    "waste":[number("estimated_fill_percent","Observed / estimated fill","निरीक्षणानुसार भरलेले प्रमाण","%",100),number("collected_volume_l","Recorded collected volume","नोंदवलेले संकलित प्रमाण","L",1e9),text("collection_record","Collection time and crew reference","संकलनाची वेळ व पथकाचा संदर्भ"),text("remaining_waste","Remaining accumulation","उरलेला कचरा")],
    "streetlights":[text("observed_state","Observed lamp state","दिव्याची प्रत्यक्ष स्थिती"),text("schedule_context","Scheduled state at observation time","निरीक्षणाच्या वेळी नियोजित स्थिती"),text("component_action","Authorized component action","अधिकृत घटकावरील कार्यवाही"),text("followup_state","Follow-up observed state","पाठपुराव्यात दिसलेली स्थिती")],
    "electricity":[text("safe_observation","Safe authorized observation","सुरक्षित अधिकृत निरीक्षण"),text("qualification_reference","Externally checked qualification reference","बाहेरून पडताळलेल्या पात्रतेचा संदर्भ"),text("work_reference","Authorized work / completion reference","अधिकृत काम / पूर्णत्वाचा संदर्भ"),text("monitoring_evidence","Post-work monitoring evidence","कामानंतरच्या निरीक्षणाचा पुरावा")],
    "general":[text("asset_condition","Observed asset condition","मालमत्तेची प्रत्यक्ष स्थिती"),text("work_category","Work category","कामाचा प्रकार"),text("completion_evidence","Completion evidence reference","पूर्णत्वाच्या पुराव्याचा संदर्भ"),text("followup_condition","Follow-up condition","पाठपुराव्यातील स्थिती")],
}


def validate_observations(domain, observations):
    fields={field["key"]:field for field in SCHEMAS.get(domain, [])}
    for key,value in observations.items():
        field=fields.get(key)
        if not field:
            raise HTTPException(422,"Observation field does not belong to this domain.")
        if field["type"] == "number":
            if isinstance(value,bool) or not isinstance(value,(int,float)) or not math.isfinite(value) or not field["minimum"] <= value <= field["maximum"]:
                raise HTTPException(422,"Measured observations must be finite and within the field's stated bounds.")
        elif not isinstance(value,str) or not 1 <= len(value.strip()) <= field["max_length"]:
            raise HTTPException(422,"Observation text must contain 1–500 characters.")
    if domain=="water" and "measured_volume_l" in observations:
        if observations.get("measurement_minutes",0)<=0 or not observations.get("measurement_method"):
            raise HTTPException(422,"A measured water volume requires a positive duration and its measurement method.")
    return observations
