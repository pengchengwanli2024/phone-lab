"""Job targets. Native event sources retain their existing single-client scope."""
from crawler_feed_bridge import REGISTRY as FEEDS
from intelligence import SOURCES

NATIVE_KEYS=('usgs','gdacs')
REGISTRY={**FEEDS,**{key:{'id':key,'kind':'native-'+key,'publisher':SOURCES[key]['name'],
                         'url':SOURCES[key]['url'],'scope':SOURCES[key]['coverage']}
                     for key in NATIVE_KEYS}}
