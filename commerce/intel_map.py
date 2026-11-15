"""Bounded dashboard projections of publisher metadata; never infer business risk.

Layer/panel catalog ideas studied in World Monitor; implementation uses our
existing source records. Static geographic references are not live observations.
"""
import json
import math
import re
from pathlib import Path

EVENT_LAYERS = {
    'earthquake': ('地震', 'usgs / gdacs'), 'flood': ('洪水', 'gdacs'),
    'storm': ('风暴与气旋', 'gdacs'), 'fire': ('森林火灾', 'gdacs'),
    'drought': ('干旱', 'gdacs'), 'volcano': ('火山', 'gdacs'),
    'tsunami': ('海啸', 'gdacs'), 'other': ('其它灾害', 'gdacs'),
}
REFERENCE_LAYERS = {'waterways': '航运通道参考', 'ports': '港口位置参考'}
LIVE_LAYERS = {'flights': '航空器位置', 'vessels': '船舶位置'}
LAYER_IDS = [*EVENT_LAYERS, *REFERENCE_LAYERS, *LIVE_LAYERS]
PANEL_IDS = ['trade', 'macro', 'energy', 'logistics']
TIMES = ['all', '1', '6', '24', '48', '168']
REGIONS = {
    'global': {'label': '全球', 'x': 0, 'y': 0, 'w': 720, 'h': 360},
    'asia': {'label': '亚洲', 'x': 450, 'y': 30, 'w': 260, 'h': 130},
    'europe': {'label': '欧洲', 'x': 310, 'y': 20, 'w': 200, 'h': 100},
    'americas': {'label': '美洲', 'x': 20, 'y': 30, 'w': 300, 'h': 150},
    'mena': {'label': '中东与北非', 'x': 330, 'y': 60, 'w': 220, 'h': 110},
}
_countries = json.loads((Path(__file__).parent / 'ui/intel-country-names.json').read_text())['countries']
_names = {r['en'].casefold(): r['zh'] for r in _countries}
_names.update({r['iso2'].casefold(): r['zh'] for r in _countries})
_names.update({'united states of america': '美国', 'russian federation': '俄罗斯', 'republic of korea': '韩国',
               'democratic republic of the congo': '刚果（金）', 'congo democratic republic': '刚果（金）',
               'viet nam': '越南', 'iran, islamic republic of': '伊朗', 'bolivia': '玻利维亚',
               'venezuela': '委内瑞拉', 'tanzania': '坦桑尼亚', 'türkiye': '土耳其', 'turkey': '土耳其'})


def country_name(value):
    value = str(value or '').strip()
    if not value:
        return '国家未提供'
    if value.casefold() in _names:
        return _names[value.casefold()]
    return '、'.join(_names.get(p.strip().casefold(), p.strip()) for p in value.split(','))


def layer_for(row):
    if row['source'] == 'usgs':
        return 'earthquake'
    if row['source'] != 'gdacs':
        return None
    text = row.get('title', '').casefold()
    # Only literal publisher terms; no magnitude-based danger/impact scores.
    for layer, pattern in [('tsunami', r'\btsunami\b'), ('earthquake', r'\bearthquake\b'),
                           ('flood', r'\bflood\b'), ('storm', r'\b(cyclone|hurricane|typhoon|storm)\b'),
                           ('fire', r'\b(fire|wildfire)\b'), ('drought', r'\bdrought\b'),
                           ('volcano', r'\b(volcano|volcanic)\b')]:
        if re.search(pattern, text):
            return layer
    return 'other'


def presentation(row):
    layer = layer_for(row)
    country = country_name(row.get('country'))
    title = row['title']
    zh = None
    if row['source'] == 'gdacs' and layer != 'other':
        alert = {'green': '绿色', 'orange': '橙色', 'red': '红色'}.get(str(row.get('publisher_alert') or '').casefold())
        place = country if row.get('country') else None
        if place:
            zh = f"{place} · {EVENT_LAYERS[layer][0]}通报" + (f'（{alert}）' if alert else '')
    elif row['source'] == 'usgs':
        match = re.match(r'^M\s*([0-9]+(?:\.[0-9]+)?)\s*-\s*(.+)$', title)
        if match:
            place = match[2]
            # A country at the end of a publisher place string can be localized.
            # Do not alter country-like words inside proper names such as
            # "West Chile Rise" or treat them as country metadata.
            if ',' in place:
                prefix, tail = place.rsplit(',', 1)
                place = prefix + '，' + _names.get(tail.strip().casefold(), tail.strip())
            direction = {'N': '以北', 'S': '以南', 'E': '以东', 'W': '以西', 'NE': '东北', 'NW': '西北',
                         'SE': '东南', 'SW': '西南', 'NNE': '北偏东北', 'NNW': '北偏西北', 'SSE': '南偏东南',
                         'SSW': '南偏西南', 'ENE': '东偏东北', 'ESE': '东偏东南', 'WNW': '西偏西北', 'WSW': '西偏西南'}
            loc = re.match(r'^(\d+(?:\.\d+)?) km ([NSEW]{1,3}) of (.+)$', place)
            if loc and loc[2] in direction:
                place = f'{loc[3]} {direction[loc[2]]}{loc[1]}公里'
            zh = f'{match[1]}级地震 · {place}'
    return {'zh_title': zh, 'country_zh': country, 'layer': layer,
            'kind': 'structured_publisher_metadata' if zh else 'original',
            'note': '按来源字段整理，地名可能保留原文；来源陈述未经独立核实' if zh else None}


def validate_layers(layers):
    if layers is None:
        return list(EVENT_LAYERS)
    if (not isinstance(layers, list) or len(layers) > len(LAYER_IDS)
            or any(not isinstance(k, str) or k not in LAYER_IDS for k in layers)
            or len(set(layers)) != len(layers)):
        raise ValueError('invalid_intel_map_layers')
    return layers


def validate_bounds(bounds):
    if bounds is None:
        return None
    if (not isinstance(bounds, dict) or set(bounds) != {'west', 'east', 'south', 'north'}
            or any(type(v) not in (int, float) or not math.isfinite(v) for v in bounds.values())
            or not -180 <= bounds['west'] <= 180 or not -180 <= bounds['east'] <= 180
            or not -90 <= bounds['south'] < bounds['north'] <= 90):
        raise ValueError('invalid_intel_map_bounds')
    return bounds


def in_bounds(location, bounds):
    if not bounds:
        return True
    lon, lat = location['lon'], location['lat']
    longitude = bounds['west'] <= lon <= bounds['east'] if bounds['west'] <= bounds['east'] else lon >= bounds['west'] or lon <= bounds['east']
    return longitude and bounds['south'] <= lat <= bounds['north']


# Approximate geographic anchors. These do not contain ship, congestion,
# closure, capacity or disruption measurements. Source facts: public reference
# coordinates in World Monitor's geo/chokepoint/ports catalogs, rounded here.
_anchors = [
    ('suez', '苏伊士运河', 32.3, 30.5), ('panama', '巴拿马运河', -79.7, 9.1),
    ('hormuz', '霍尔木兹海峡', 56.3, 26.5), ('malacca', '马六甲海峡', 101.5, 2.5),
    ('mandeb', '曼德海峡', 43.4, 12.6), ('gibraltar', '直布罗陀海峡', -5.6, 35.9),
    ('bosphorus', '博斯普鲁斯海峡', 29.1, 41.1), ('cape', '好望角航路', 18.5, -34.4),
]
_ports = [('shanghai', '上海港', 121.8, 31.3), ('singapore', '新加坡港', 103.8, 1.3),
          ('rotterdam', '鹿特丹港', 4.1, 51.9), ('los-angeles', '洛杉矶港', -118.3, 33.7),
          ('jebel-ali', '杰贝阿里港', 55.1, 25.0), ('busan', '釜山港', 129.0, 35.1)]
REFERENCES = [dict(id=f'ref-{kind}-{key}', title=title, layer=kind, location={'lon': lon, 'lat': lat},
                   kind='static_geographic_reference', operational_status='unknown',
                   source_url='https://github.com/koala73/worldmonitor/blob/main/src/config/' + ('chokepoint-registry.ts' if kind == 'waterways' else 'ports.ts'))
              for kind, entries in [('waterways', _anchors), ('ports', _ports)] for key, title, lon, lat in entries]


def catalog():
    return [dict(id=key, name=name, sources=source, kind='publisher_event') for key, (name, source) in EVENT_LAYERS.items()] + [
        dict(id=key, name=name, sources='公开地理参考', kind='static_geographic_reference') for key, name in REFERENCE_LAYERS.items()] + [
        dict(id=key, name=name, sources='OpenSky Network' if key=='flights' else 'AISStream', kind='live_observation') for key,name in LIVE_LAYERS.items()]
