import {MoreActions} from './action-menu';
import {labels,storeSections,storeSectionFor} from './navigation';
import './store-navigation.css';

/** Leaf routes retain their existing scopes, drafts and return destinations. */
export function StoreNavigation({route,navigate}:{route:string;navigate:(route:string)=>void}) {
  const active=route.replace('old:',''),section=storeSectionFor(active);
  if(!section)return null;
  return <div className="r-store-navigation">
    <nav className="r-store-sections" aria-label="店铺管理业务分区">
      {storeSections.map(item=><button type="button" key={item.id} aria-pressed={item.id===section.id} onClick={()=>navigate(item.defaultRoute)}>{item.label}</button>)}
    </nav>
    <label className="r-store-section-select ui-field">店铺管理分区<select value={section.id} onChange={event=>{const next=storeSections.find(item=>item.id===event.target.value);if(next)navigate(next.defaultRoute)}}>{storeSections.map(item=><option key={item.id} value={item.id}>{item.label}</option>)}</select></label>
    <nav className="r-store-routes" aria-label={section.label+'页面'}>
      {section.primary.map(id=><button type="button" key={id} aria-current={active===id?'page':undefined} onClick={()=>navigate(id)}>{labels[id]}</button>)}
      {section.secondary.length>0&&<MoreActions label="更多商品工具" actions={section.secondary.map(id=>({id,label:labels[id],onSelect:()=>navigate(id)}))}/>}
      {section.secondary.includes(active)&&<span className="r-store-tool-name" title={labels[active]}>{labels[active]}</span>}
    </nav>
  </div>;
}
