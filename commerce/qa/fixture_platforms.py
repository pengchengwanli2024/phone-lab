"""Isolated platform UI fixture. All provider replies are synthetic."""
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import server
from test_platform_connections import synthetic
from test_pilot_bridge import seed

if __name__=='__main__':
 server.Handler.secret=server.token();server.Handler.service=server.Commerce(server.STATE)
 server.Handler.service.platforms.request=synthetic
 seed(server.Handler.service)
 try:server.CommerceHTTPServer(('127.0.0.1',server.PORT),server.Handler).serve_forever()
 finally:server.Handler.service.platforms.stop()
