"""Open the loopback-only private wizard without printing a credential or ticket."""
import json
import os
import urllib.request
import webbrowser
from runtime import ensure, token, PORT


def main():
    ensure();origin='http://127.0.0.1:'+str(PORT)
    request=urllib.request.Request(origin+'/v1/connections/ticket',data=b'{}',headers={'Content-Type':'application/json','Authorization':'Bearer '+token()})
    with urllib.request.urlopen(request,timeout=8) as response:ticket=json.load(response)['ticket']
    if webbrowser.open(origin+'/setup?ticket='+ticket):print('本机私有接入向导已在默认浏览器打开。密钥只在该页面填写。')
    else:raise RuntimeError('browser_open_failed_no_ticket_printed')


if __name__=='__main__':main()
