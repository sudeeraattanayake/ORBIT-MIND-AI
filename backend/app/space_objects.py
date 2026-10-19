"""Public orbital elements and historical fireballs; no spacecraft health telemetry."""
import os, math, time
from datetime import datetime, timezone
from functools import lru_cache
import httpx
from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field
from sgp4.api import Satrec, jday
router=APIRouter(prefix="/api/space", tags=["Space objects"])
CELESTRAK="https://celestrak.org/NORAD/elements/gp.php"
FIREBALL="https://ssd-api.jpl.nasa.gov/fireball.api"
GROUPS={"stations":"stations", "weather":"weather", "science":"science", "starlink":"starlink", "active":"active"}
_cache={}

def cached_json(key, url, params, ttl=1800):
    if key in _cache and time.time()-_cache[key][0]<ttl:return _cache[key][1]
    try:
        with httpx.Client(timeout=18, follow_redirects=True, headers={"User-Agent":"OrbitMindAI-Education/4.0"}) as client:
            r=client.get(url,params=params);r.raise_for_status();data=r.json()
    except Exception as e:
        raise HTTPException(503,detail=f"External public data service unavailable: {type(e).__name__}") from e
    _cache[key]=(time.time(),data)
    return data

def position(gp):
    try:
        sat=Satrec.twoline2rv(gp['TLE_LINE1'],gp['TLE_LINE2'])
        now=datetime.now(timezone.utc); jd,fr=jday(now.year,now.month,now.day,now.hour,now.minute,now.second+now.microsecond/1e6)
        error,r,v=sat.sgp4(jd,fr)
        if error: return None
        radius=math.sqrt(sum(c*c for c in r))
        return {"distance_from_earth_center_km":round(radius,1),"altitude_above_earth_km":round(radius-6371.0,1),"eci_position_km":[round(x,1) for x in r],"calculated_at":now.isoformat(),"method":"SGP4 TLE approximation; mean Earth radius 6371 km"}
    except (ValueError,KeyError,TypeError):return None

@router.get('/satellites')
def satellites(group:str=Query('stations'),limit:int=Query(30,ge=1,le=100),search:str=''):
    if group not in GROUPS:raise HTTPException(400,'Unsupported group')
    # CelesTrak JSON GP response includes TLE_LINE1 and TLE_LINE2 only when FORMAT=TLE? JSON GP provides elements, not TLE.
    # Request TLE and parse 3-line records instead.
    key='tle:'+group
    if key in _cache and time.time()-_cache[key][0]<1800: raw=_cache[key][1]
    else:
        try:
            with httpx.Client(timeout=22,follow_redirects=True) as client:
                r=client.get(CELESTRAK,params={'GROUP':GROUPS[group],'FORMAT':'3LE'});r.raise_for_status();raw=r.text
            if '<html' in raw.lower() or len(raw)<30:raise ValueError('Invalid orbital feed')
            _cache[key]=(time.time(),raw)
        except Exception as e:raise HTTPException(503,detail='CelesTrak orbital feed currently unavailable') from e
    lines=[s.strip() for s in raw.splitlines() if s.strip()]
    records=[]
    for i in range(0,len(lines)-2,3):
        name,l1,l2=lines[i:i+3]
        if not (l1.startswith('1 ') and l2.startswith('2 ')):continue
        if search and search.lower() not in name.lower() and search not in l1[2:7]:continue
        norad=l1[2:7].strip()
        p=position({'TLE_LINE1':l1,'TLE_LINE2':l2})
        records.append({'name':name,'norad_id':norad,'position':p,'source':'CelesTrak GP TLE', 'health_status':'unknown','repair_required':'unknown','repair_feasibility':'unknown','health_note':'Public orbital elements do not provide satellite component health or repairability.'})
        if len(records)>=limit:break
    return {'group':group,'count_returned':len(records),'satellites':records,'source_url':'https://celestrak.org/NORAD/elements/','notice':'Orbit is estimated from public TLEs, not real-time tracking. No health or repair data is provided.'}

@router.get('/fireballs')
def fireballs(limit:int=Query(25,ge=1,le=100)):
    data=cached_json('fireballs',FIREBALL,{'limit':limit,'req-loc':'true'},ttl=3600)
    fields=data.get('fields',[])
    items=[dict(zip(fields,row)) for row in data.get('data',[]) or []]
    return {'events':items,'count':len(items),'source_url':FIREBALL,'notice':'Historical observed atmospheric fireballs; NOT a live meteor detector, future impact forecast, or comprehensive count.'}

class Inspection(BaseModel):
    satellite_name:str=Field(min_length=1,max_length=120)
    battery_pct:float=Field(ge=0,le=100)
    temperature_c:float=Field(ge=-200,le=250)
    signal_pct:float=Field(ge=0,le=100)
    propulsion_ok:bool=True
    hardware_accessible:bool=False

@router.post('/repair-assessment')
def repair_assessment(t:Inspection):
    flags=[]
    if t.battery_pct<20:flags.append('Low battery')
    if t.temperature_c < -20 or t.temperature_c>65:flags.append('Thermal threshold exceeded')
    if t.signal_pct<30:flags.append('Weak communication signal')
    if not t.propulsion_ok:flags.append('Propulsion flagged by operator')
    status='needs_review' if flags else 'nominal_in_supplied_test_values'
    return {'satellite_name':t.satellite_name,'status':status,'flags':flags,'repair_required':'possible_inspection' if flags else 'not_indicated_by_test_values','repair_feasibility':'requires engineering and mission assessment' if t.hardware_accessible else 'not_determinable; no servicing access confirmed','data_type':'USER_SUPPLIED_SCENARIO','note':'This is a hypothetical rule-based triage, not actual satellite diagnosis or confirmation of repairability.'}
