import {useEffect,useRef,useState} from 'react';
import {api,errorText} from './api';
import {Badge,Button,Empty,ErrorNotice,Panel} from './ui';
import {closableItems,kindName,sourceName,type ReviewItem} from './outcome-review-state';

interface Page {items:ReviewItem[];complete:boolean;has_more:boolean}

/** Failed or unknown requests the operator has looked at can be closed. Closing never resends anything. */
export function OutcomeReviewPanel({synthetic,active=true}:{synthetic:boolean;active?:boolean}) {
  const [page,setPage]=useState<Page|null>(null),[error,setError]=useState(''),[notice,setNotice]=useState(''),[loading,setLoading]=useState(false),[busy,setBusy]=useState('');
  const version=useRef(0),alive=useRef(true);
  async function load() {
    const read=++version.current;setLoading(true);
    try{
      const [unknown,failed]=await Promise.all(['unknown','failed'].map(kind=>api<Page>('commerce_attention_list',{demo:synthetic,kind,limit:50})));
      if(alive.current&&read===version.current){setPage({items:[...unknown.items,...failed.items],complete:unknown.complete&&failed.complete,has_more:unknown.has_more||failed.has_more});setError('');}
    }catch(failure){if(alive.current&&read===version.current){setPage(null);setError(errorText(failure));}}
    finally{if(alive.current&&read===version.current)setLoading(false);}
  }
  useEffect(()=>{alive.current=true;setPage(null);setNotice('');if(active)void load();return ()=>{alive.current=false;version.current++;};},[synthetic,active]);
  async function close(item:ReviewItem) {
    if(busy)return;setBusy(item.id);setError('');setNotice('');
    try{await api('commerce_attention_close',{item_id:item.id,note:''});if(alive.current)setNotice('已标记为核对过并关闭。原请求和它的状态没有改变，也没有重发。');}
    catch(failure){if(alive.current)setError(errorText(failure));}
    finally{if(alive.current){setBusy('');void load();}}
  }
  if(!active)return null;
  const items=page?closableItems(page.items):[];
  return <Panel title="待核对的失败与未知结果" action={<Button onClick={()=>void load()} disabled={loading}>刷新</Button>}>
    <ErrorNotice>{error}</ErrorNotice>
    {notice?<p className="r-oc-result r-loop-status" role="status">{notice}</p>:null}
    {!page?<Empty>{loading?'正在读取待核对事项…':'待核对事项未读到，请刷新。'}</Empty>:<>
      <p className="r-footnote">系统不会自动重发这些请求。你核对过原记录、确认不需要再处理后，可以在这里关闭；同一请求以后若再次失败，会重新出现。{page.complete?'':'部分来源未读到，列表不完整。'}{page.has_more?'仅显示前 50 条。':''}</p>
      {items.length?<ul className="r-oc-records">{items.map(item=><li key={item.id}>
        <div className="r-oc-record-heading"><strong>{item.title}</strong><Badge tone="warning">{kindName(item)}</Badge></div>
        <p className="r-footnote">{sourceName(item.source)} · {item.detail}</p>
        <Button disabled={!!busy} onClick={()=>void close(item)}>{busy===item.id?'正在关闭…':'已核对，关闭'}</Button>
      </li>)}</ul>:<Empty>当前范围没有待核对的失败或未知结果。</Empty>}
    </>}
  </Panel>;
}
