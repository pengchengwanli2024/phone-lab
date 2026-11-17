"""Bounded, source-specific facts; original public data remains the evidence."""
from datetime import datetime, timedelta, timezone
import math
from urllib.parse import urlsplit

BEIJING=timezone(timedelta(hours=8))


def number(value):
    try:return value if type(value)in(int,float)and math.isfinite(value)else None
    except OverflowError:return None


def text(value,limit=240):
    return value[:limit]if isinstance(value,str)else None


def event_fact(event):
    if not isinstance(event,dict)or event.get('type')!='Feature' or not isinstance(event.get('properties'),dict):return None
    props=event['properties'];geometry=event.get('geometry')
    coords=geometry.get('coordinates')if isinstance(geometry,dict)and geometry.get('type')=='Point'else None
    depth=number(coords[2])if isinstance(coords,list)and len(coords)>=3 else None
    utc=beijing=date_changed=None;stamp=number(props.get('time'))
    if stamp is not None:
        try:
            occurred=datetime.fromtimestamp(stamp/1000,timezone.utc)
            utc=occurred.strftime('%Y-%m-%d %H:%M:%S UTC')
            local=occurred.astimezone(BEIJING)
            beijing=local.strftime('%Y-%m-%d %H:%M:%S +08:00')
            date_changed=occurred.date()!=local.date()
        except (ValueError,OverflowError,OSError):pass
    status=props.get('status');alert=props.get('alert');tsunami=props.get('tsunami')
    return {'event_id':text(event.get('id'),100),'place':text(props.get('place')),
            'magnitude':number(props.get('mag')),'magnitude_type':text(props.get('magType'),20),
            'depth_km':depth,'occurred_utc':utc,'occurred_beijing':beijing,
            'utc_to_beijing_date_changed':date_changed,
            'review_status':status if status in('automatic','reviewed')else None,
            'alert':alert if alert in('green','yellow','orange','red')else None,
            'tsunami_flag':tsunami if type(tsunami)is int and tsunami in(0,1)else None}


def official_facts(url,data):
    """USGS GeoJSON units: mag, Point depth km, Unix milliseconds in UTC.

    https://earthquake.usgs.gov/earthquakes/feed/v1.0/geojson.php
    Occurrence time is never promoted to publication or independent verification.
    """
    parsed=urlsplit(url)
    if parsed.scheme!='https'or parsed.hostname!='earthquake.usgs.gov':return None
    if not(parsed.path=='/fdsnws/event/1/query'or
           parsed.path.startswith('/earthquakes/feed/v1.0/')and parsed.path.endswith('.geojson')):return None
    if not isinstance(data,dict):return None
    if data.get('type')=='FeatureCollection'and isinstance(data.get('features'),list):events=data['features']
    elif data.get('type')=='Feature':events=[data]
    else:return None
    items=[fact for event in events[:3]if(fact:=event_fact(event))is not None]
    if events and not items:return None
    return {'schema':'usgs-earthquake-v1','records_returned':len(events),'truncated':len(events)>3,'items':items}
