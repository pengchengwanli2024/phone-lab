"""Seed only an explicitly isolated synthetic acceptance directory; no network."""
import os
from pathlib import Path
import sys

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from commerce_core import Core
from live_connections import LiveConnections
from test_live_connections import batch, SECRET

state=Path(os.environ['COMMERCE_STATE']).resolve()
assert state.name=='state' and state.parent.name.startswith('commerce-harness-')
live=LiveConnections(Core(state/'commerce.sqlite'),state)
live.configure({'ozon_client_id':'123456','ozon_api_key':SECRET,'fulfillment_modes':['OGL']})
config=live.config()
for kind in ('orders','stock'):live._publish(config['connection_id'],kind,batch(kind),config,False)
live.configure({'orders_scope_confirmed':True,'stock_basis':'present_minus_reserved','basis_confirmed':True})
