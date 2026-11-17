"""Bounded shared public retrieval; search summaries never become verified news."""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime,timedelta,timezone
from html import unescape
from html.parser import HTMLParser
import copy
import hashlib
import ipaddress
import json
import os
from pathlib import Path
import re
import shutil
import signal
import subprocess
import tempfile
import threading
import time
from urllib.parse import urlsplit,urlunsplit,urljoin
from urllib.request import getproxies

ROOT=Path(__file__).resolve().parents[1]
BEIJING=timezone(timedelta(hours=8))
REGIONS={
 'southeast_asia':('东南亚',('东南亚','东盟','southeast asia','asean')),
 'russia':('俄罗斯',('俄罗斯','russia')),
 'middle_east':('中东',('中东','middle east')),
 'east_asia':('东亚',('东亚','east asia')),
 'europe':('欧洲',('欧洲','europe')),
 'north_america':('北美',('北美','north america')),
 'latin_america':('拉美',('拉美','拉丁美洲','latin america')),
 'africa':('非洲',('非洲','africa'))}
PERIODS=('auto','any','today','24h','7d')
READ_ONLY=('commerce_web_search','commerce_web_read')


class RetrievalCancelled(Exception):pass


def check_cancelled(cancelled):
    if cancelled():raise RetrievalCancelled()


def canonical(value):return json.dumps(value,ensure_ascii=False,sort_keys=True,separators=(',',':'),allow_nan=False)
def digest(value):return hashlib.sha256(canonical(value).encode()).hexdigest()
def text(value,limit=400):return re.sub(r'\s+',' ',unescape(re.sub(r'<[^>]*>',' ',str(value or'')))).strip()[:limit]
def beijing_time(value):return datetime.fromtimestamp(value,BEIJING).strftime('%Y-%m-%d %H:%M:%S +08:00')


def public_url(value):
    try:
        if not isinstance(value,str)or not 1<=len(value)<=2048 or re.search(r'[\x00-\x20\\]',value):raise ValueError()
        p=urlsplit(value);host=(p.hostname or'').rstrip('.').lower()
        if p.scheme not in ('http','https')or not host or p.username is not None or p.password is not None or '%'in host:raise ValueError()
        if p.port not in (None,443 if p.scheme=='https'else 80):raise ValueError()
        if host=='localhost'or host.endswith(('.localhost','.local','.internal','.lan')):raise ValueError()
        try:
            if not ipaddress.ip_address(host).is_global:raise ValueError()
        except ValueError:
            if '.'not in host or re.fullmatch(r'[0-9a-fx.]+',host)or ':'in host:raise ValueError()
        return urlunsplit((p.scheme,p.netloc.lower(),p.path,p.query,''))
    except (ValueError,TypeError):raise ValueError('web_public_url_required')from None


def time_window(period,now):
    if period not in PERIODS:raise ValueError('web_invalid_period')
    current=datetime.fromtimestamp(now,timezone.utc);local=current.astimezone(BEIJING)
    start=end=None
    if period=='today':start=local.replace(hour=0,minute=0,second=0,microsecond=0);end=start+timedelta(days=1)
    elif period in ('24h','7d'):start=current-timedelta(hours=24 if period=='24h'else 168);end=current
    return {'period':period,'timezone':'Asia/Shanghai','date_beijing':local.date().isoformat(),
            'from_utc':start.astimezone(timezone.utc).isoformat()if start else None,
            'to_utc':end.astimezone(timezone.utc).isoformat()if end else None}


def published(value):
    try:
        if not isinstance(value,str)or len(value)>80:return None
        stamp=datetime.fromisoformat(value.replace('Z','+00:00'))
        return stamp.timestamp()if stamp.tzinfo else None
    except (ValueError,OverflowError,OSError):return None


class Page(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True);self.stack=[];self.parts=[];self.article=[];self.content_depth=None;self.title=[];self.date=None;self.og_title=None;self.ld=None
        self.links=[];self.anchor=None;self.og_type=None;self.article_count=0
    def handle_starttag(self,tag,attrs):
        a=dict(attrs)
        if tag=='meta':
            key=(a.get('property')or a.get('name')or a.get('itemprop')or'').lower()
            if key in ('article:published_time','datepublished','pubdate','publishdate','date')and not self.date:self.date=published(a.get('content'))
            if key=='og:title':self.og_title=text(a.get('content'),240)
            if key=='og:type':self.og_type=a.get('content')
        if tag=='article':self.article_count+=1
        if tag=='a'and len(self.links)<128:self.anchor={'href':a.get('href',''),'parts':[],'preferred':self.content_depth is not None}
        if tag=='time'and not self.date:self.date=published(a.get('datetime'))
        if tag=='script':self.ld=[]if a.get('type','').lower()=='application/ld+json'else None
        if tag not in ('meta','img','br','hr','input','link','source','wbr','area','embed'):self.stack.append(tag)
        identity=' '.join((a.get('id',''),a.get('class',''),a.get('itemprop',''))).lower()
        if self.content_depth is None and (tag in ('article','main')or re.search(r'\b(?:articlebody|article[-_]body|article[-_]content|entry[-_]content|story[-_]body|live-page-body)\b',identity)):
            self.content_depth=len(self.stack)
    def handle_endtag(self,tag):
        if tag=='a'and self.anchor is not None:self.links.append(self.anchor);self.anchor=None
        if tag=='script'and self.ld is not None:
            try:
                def dates(value,depth=0):
                    if depth>6 or self.date:return
                    if isinstance(value,dict):
                        self.date=published(value.get('datePublished'))
                        if not self.date:
                            for item in list(value.values())[:100]:dates(item,depth+1)
                    elif isinstance(value,list):
                        for item in value[:100]:dates(item,depth+1)
                if not self.date:dates(json.loads(''.join(self.ld)[:64000]))
            except (ValueError,RecursionError):pass
            self.ld=None
        if tag in self.stack:self.stack=self.stack[:len(self.stack)-1-self.stack[::-1].index(tag)]
        if self.content_depth is not None and len(self.stack)<self.content_depth:self.content_depth=None
    def handle_data(self,value):
        if 'script'in self.stack:
            if self.ld is not None:self.ld.append(value[:64000])
            return
        if any(t in self.stack for t in ('script','style','noscript','svg','nav','header','footer','form')):return
        value=text(value,20000)
        if not value:return
        if self.anchor is not None:self.anchor['parts'].append(value[:240])
        if 'title'in self.stack:self.title.append(value);return
        if 'head'in self.stack:return
        self.parts.append(value)
        if self.content_depth is not None:self.article.append(value)


def parse_page(html,url):
    parser=Page();parser.feed(html)
    body='\n'.join(parser.article or parser.parts)[:18000]
    if not body or (len(body)<400 and re.search(
            r'latest earthquakes application supports|(?:please )?enable javascript to (?:run|view|use)|javascript is required',body,re.I)):
        raise ValueError('web_page_body_unavailable')
    candidates=[];seen={public_url(url)}
    for anchor in sorted(parser.links,key=lambda row:not row['preferred']):
        title=text(' '.join(anchor['parts']),180)
        if len(title)<8:continue
        try:target=public_url(urljoin(url,anchor['href']))
        except ValueError:continue
        if not target.startswith('https://')or target in seen:continue
        path=urlsplit(target).path
        if re.search(r'\.(?:jpe?g|png|webp|gif|svg|mp4|mp3|pdf)$',path,re.I):continue
        if not re.search(r'\d|\.html?$|/(?:news|article|story|world)/',path,re.I):continue
        seen.add(target);candidates.append({'url':target,'title':title,'content_status':'link_not_read'})
        if len(candidates)>=8:break
    index_path=re.search(r'/(?:tags?|topics?|categor(?:y|ies)|subject|channel|archive)(?:[-/]|$)',urlsplit(url).path,re.I)
    from sourcing_extract import html_product
    product=html_product(html,url)
    return {'url':public_url(url),'title':parser.og_title or text(' '.join(parser.title),240)or urlsplit(url).hostname,
            **({'product_metadata':product}if product else{}),
            'text':body,'published_at':parser.date,'page_kind':'article'if not index_path and(parser.og_type=='article'or parser.article_count==1)else'index_or_page',
            **({'article_candidates':candidates}if candidates else{})}


def cli_runner(action,value,cancelled):
    executable=shutil.which('node');entry=ROOT/'.local/search/open-websearch/node_modules/open-websearch/build/index.js'
    if not executable or not entry.is_file():raise ValueError('web_search_not_configured')
    # Fixed installed CLI, argument array, request mode, no daemon spawn or shell.
    env={k:v for k,v in os.environ.items()if not k.startswith(('OPEN_WEBSEARCH_','PROXY_','USE_PROXY','FETCH_WEB_','ANYSEARCH_'))}
    env.update(MODE='stdio',ENABLE_HTTP_SERVER='false',SEARCH_MODE='request',DEFAULT_SEARCH_ENGINE='duckduckgo')
    proxy=getproxies().get('https')or getproxies().get('http')
    if proxy:env.update(USE_PROXY='true',PROXY_URL=proxy)
    output=tempfile.TemporaryFile()
    child=subprocess.Popen([executable,str(entry),'search',value,'--limit','6','--engine','duckduckgo','--search-mode','request','--json'],
        stdin=subprocess.DEVNULL,stdout=output,stderr=subprocess.DEVNULL,env=env,start_new_session=True)
    deadline=time.monotonic()+24
    try:
        while True:
            check_cancelled(cancelled)
            if os.fstat(output.fileno()).st_size>1_000_000:raise ValueError('web_provider_result_too_large')
            try:child.wait(timeout=.2);break
            except subprocess.TimeoutExpired:
                if time.monotonic()>deadline:raise ValueError('web_provider_timeout')
        output.seek(0);raw=output.read(1_000_001)
        if len(raw)>1_000_000:raise ValueError('web_provider_result_too_large')
        try:value=json.loads(raw)
        except (ValueError,UnicodeError):raise ValueError('web_provider_invalid_response')from None
        if child.returncode or value.get('status')!='ok':raise ValueError('web_provider_unavailable')
        return value['data']
    finally:
        if child.poll()is None:
            try:os.killpg(child.pid,signal.SIGTERM);child.wait(timeout=2)
            except (OSError,subprocess.TimeoutExpired):
                try:os.killpg(child.pid,signal.SIGKILL)
                except OSError:pass
                child.wait(timeout=2)
        output.close()


class PublicWeb:
    def __init__(self,state,runner=None,reader=None,clock=time.time):
        from public_web_transport import fetch_page
        self.state=Path(state);self.runner=runner or cli_runner;self.reader=reader or fetch_page;self.clock=clock
        self.cache={};self.lock=threading.Lock();self.slots=threading.BoundedSemaphore(3)

    def search(self,query,regions=None,period='auto',limit=5,refresh=False,cancelled=lambda:False):
        if not isinstance(query,str)or not 1<=len(query.strip())<=240 or any(ord(c)<32 for c in query):raise ValueError('web_invalid_query')
        if type(limit)is not int or not 1<=limit<=6:raise ValueError('web_invalid_limit')
        if type(refresh)is not bool:raise ValueError('web_invalid_refresh')
        if period not in PERIODS:raise ValueError('web_invalid_period')
        if regions is not None and(not isinstance(regions,list)or len(regions)>3 or any(not isinstance(r,str)or r not in REGIONS for r in regions)):raise ValueError('web_invalid_regions')
        if period=='auto':period='today'if re.search('今日|今天|today',query,re.I)else'any'
        if regions is None:
            regions=[k for k,(_,aliases)in REGIONS.items()if any(a in query.lower()for a in aliases)]if re.search('新闻|要闻|局势|news|headlines',query,re.I)else[]
        regions=list(dict.fromkeys(regions))[:3];window=time_window(period,self.clock())
        key=digest([query,regions,period,window['date_beijing'],limit]);check_cancelled(cancelled)
        with self.lock:
            old=self.cache.get(key)
            if not refresh and old and self.clock()-old['retrieved_at']<120:return {**copy.deepcopy(old),'cached':True}
        def collect(region):
            label=REGIONS[region][0]if region else'公开网络'
            # Separate regional queries avoid asking one article to match all regions.
            subject=query
            if region:
                for selected in regions:
                    for alias in REGIONS[selected][1]:
                        pattern=re.escape(alias)if re.search(r'[\u4e00-\u9fff]',alias)else r'\b'+re.escape(alias)+r'\b'
                        subject=re.sub(pattern,' ',subject,flags=re.I)
                subject=re.sub(r'帮我(?:看看|查询|查找|搜索|查一下)|请(?:查询|查找|搜索)|目前|今日|今天|要闻|最新|以及',' ',subject)
                subject=re.sub(r'[、，,；;]+',' ',subject);subject=' '.join(subject.split()).strip(' 的和与')
            search=(label+' '+(subject or'新闻')if region else query.strip())
            if period!='any':search+=' '+window['date_beijing']
            group={'region':region or'global','label':label,'query':search,'items':[]}
            try:
                check_cancelled(cancelled)
                if not self.slots.acquire(timeout=.5):raise ValueError('web_retrieval_busy')
                try:raw=self.runner('search',search,cancelled)
                finally:self.slots.release()
                seen=set()
                if not isinstance(raw,dict)or not isinstance(raw.get('results'),list):raise ValueError('web_provider_invalid_response')
                for row in raw.get('results',[]):
                    if not isinstance(row,dict):continue
                    try:url=public_url(row.get('url'))
                    except ValueError:continue
                    if url in seen:continue
                    seen.add(url);item={'url':url,'title':text(row.get('title'),240),'summary':text(row.get('description'),500),
                        'publisher':urlsplit(url).hostname,'engine':text(row.get('engine'),40),'retrieved_at':self.clock(),
                        'published_at':None,'publication_status':'unconfirmed','content_status':'search_summary_only','independently_verified':False}
                    item['source_sha256']=digest(item);group['items'].append(item)
                    if len(group['items'])>=min(limit,3 if regions else limit):break
                group.update(status='ready'if group['items']else'empty',error=None)
            except ValueError as error:group.update(status='failed',error=str(error)if str(error).startswith('web_')else'web_provider_unavailable')
            return group
        with ThreadPoolExecutor(max_workers=3)as pool:groups=list(pool.map(collect,regions or[None]))
        check_cancelled(cancelled);failed=sum(g['status']=='failed'for g in groups)
        result={'status':'failed'if failed==len(groups)else'partial'if failed else'ready','query':query,'window':window,
                'groups':groups,'retrieved_at':self.clock(),'cached':False,'provider':'Open-WebSearch / DuckDuckGo',
                'publication_times_require_page_read':True,'independently_verified':False}
        with self.lock:
            if len(self.cache)>=64:self.cache.pop(next(iter(self.cache)))
            self.cache[key]=copy.deepcopy(result)
        return result

    def read(self,urls,period='any',cancelled=lambda:False,url_validator=None):
        if not isinstance(urls,list)or not 1<=len(urls)<=3:raise ValueError('web_invalid_urls')
        if period not in ('any','today','24h','7d'):raise ValueError('web_invalid_period')
        urls=list(dict.fromkeys(public_url(u)for u in urls));window=time_window(period,self.clock());items=[]
        for url in urls:
            check_cancelled(cancelled)
            try:
                if url_validator is not None:url_validator(url)
                if not self.slots.acquire(timeout=.5):raise ValueError('web_retrieval_busy')
                try:
                    from public_web_transport import fetch_page
                    page=(self.reader(url,cancelled,url_validator=url_validator)
                          if url_validator is not None and self.reader is fetch_page else self.reader(url,cancelled))
                finally:self.slots.release()
                if url_validator is not None:url_validator(page['url'])
                stamp=page.get('published_at');status='unconfirmed'
                if stamp is not None:
                    status='reported_by_publisher'
                    if window['from_utc']:
                        status='within_window'if datetime.fromisoformat(window['from_utc']).timestamp()<=stamp<datetime.fromisoformat(window['to_utc']).timestamp()else'outside_window'
                    if stamp>self.clock()+300:status='future_timestamp'
                retrieved=self.clock()
                item={**page,'text':page.get('text','')[:3200],'status':'ready','retrieved_at':retrieved,'retrieved_beijing':beijing_time(retrieved),
                      'publication_status':status,'content_status':page.get('content_status','page_text'),'independently_verified':False}
                if page.get('text_truncated')or len(page.get('text',''))>3200:item['text_truncated']=True
                if stamp is not None:item.update(published_utc=datetime.fromtimestamp(stamp,timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC'),published_beijing=datetime.fromtimestamp(stamp,BEIJING).strftime('%Y-%m-%d %H:%M:%S +08:00'))
                item['source_sha256']=digest(item)
            except ValueError as error:
                retrieved=self.clock()
                item={'url':url,'status':'failed','error':str(error)if str(error).startswith('web_')else'web_page_unavailable','retrieved_at':retrieved,'retrieved_beijing':beijing_time(retrieved)}
            items.append(item)
        failed=sum(i['status']=='failed'for i in items)
        retrieved=self.clock()
        return {'status':'failed'if failed==len(items)else'partial'if failed else'ready','items':items,'window':window,'retrieved_at':retrieved,'retrieved_beijing':beijing_time(retrieved),'independently_verified':False}

    def invoke(self,name,args,cancelled=lambda:False):
        if name=='commerce_web_search':return self.search(**args,cancelled=cancelled)
        if name=='commerce_web_read':return self.read(**args,cancelled=cancelled)
        raise ValueError('unknown_tool')


def definitions(schema,S):
    return [
      ('commerce_web_search','检索公开网络；可按地区分别查询今日新闻，摘要不等于已读取正文或已核实事实',schema({
        'query':{'type':'string','minLength':1,'maxLength':240},'regions':{'type':'array','maxItems':3,'items':{'type':'string','enum':list(REGIONS)}},
        'period':{'type':'string','enum':list(PERIODS)},'limit':{'type':'integer','minimum':1,'maximum':6},'refresh':{'type':'boolean'}},['query'])),
      ('commerce_web_read','读取1至3个公开网页正文或JSON数据，保留来源时间和读取时间；逐来源保留失败，不绕过登录或挑战',schema({
        'urls':{'type':'array','minItems':1,'maxItems':3,'items':{'type':'string','maxLength':2048}},'period':{'type':'string','enum':['any','today','24h','7d']}},['urls']))]


def tool_menu():
    return [{'tool':'commerce_web_search','arguments':{'query':'public search text, at most 240 characters; use for current news and public information',
              'regions':'optional list of up to 3: '+', '.join(REGIONS),'period':'auto|any|today|24h|7d; today means Beijing calendar date','refresh':'optional boolean; true only when the user explicitly asks to refresh/retry the public search'}},
            {'tool':'commerce_web_read','arguments':{'urls':'1..3 public URLs returned by search or explicitly supplied by the user','period':'any|today|24h|7d'}}]


def check_call(name,args,seen):
    if name=='commerce_web_search':
        if set(args)-{'query','regions','period','limit','refresh'}or not isinstance(args.get('query'),str)or not 1<=len(args['query'].strip())<=240:raise ValueError('agent_invalid_tool_arguments')
        if type(args.get('refresh',False))is not bool:raise ValueError('agent_invalid_tool_arguments')
        if args.get('period','auto')not in PERIODS or type(args.get('limit',5))is not int or not 1<=args.get('limit',5)<=6:raise ValueError('agent_invalid_tool_arguments')
        regions=args.get('regions',[])
        if not isinstance(regions,list)or len(regions)>3 or any(not isinstance(r,str)or r not in REGIONS for r in regions):raise ValueError('agent_invalid_tool_arguments')
    elif name=='commerce_web_read':
        if set(args)-{'urls','period'}or not isinstance(args.get('urls'),list)or not 1<=len(args['urls'])<=3 or args.get('period','any')not in ('any','today','24h','7d'):raise ValueError('agent_invalid_tool_arguments')
        try:urls=[public_url(u)for u in args['urls']]
        except ValueError:raise ValueError('agent_public_web_outside_read_scope')from None
        if any(u not in seen for u in urls):raise ValueError('agent_public_web_outside_read_scope')
        args={**args,'urls':urls}
    else:raise ValueError('agent_tool_outside_scope')
    return name,copy.deepcopy(args)


def projection(value):
    result=copy.deepcopy(value)
    # Three regional samples or pages must fit one runtime observation.
    while len(canonical(result))>14000:
        if 'groups'in result:
            group=max(result['groups'],key=lambda g:len(canonical(g['items'])))
            if not group['items']:break
            group['items'].pop();group['truncated']=True
        else:
            row=max(result.get('items',[]),key=lambda r:len(r.get('text','')),default={})
            if not row.get('text'):break
            row['text']=row['text'][:-300];row['truncated']=True
    return result


def explicit_urls(question):
    urls=[]
    for match in re.findall(r'https?://[^\s<>"\u3000]+',question):
        try:urls.append(public_url(match.rstrip('，。；、！？）)]}')))
        except ValueError:pass
    return urls[:6]


def result_urls(value):
    found=[]
    def visit(item,depth=0):
        if depth>6:return
        if isinstance(item,dict):
            for key,v in item.items():
                if key in ('url','source_url')and isinstance(v,str):
                    try:found.append(public_url(v))
                    except ValueError:pass
                elif isinstance(v,(dict,list)):visit(v,depth+1)
        elif isinstance(item,list):
            for row in item[:30]:visit(row,depth+1)
    visit(value)
    return set(found)
