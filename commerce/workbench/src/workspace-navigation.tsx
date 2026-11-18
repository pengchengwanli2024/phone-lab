import {labels, navigation, sectionFor} from './navigation';

/** One place for business destinations; object tabs stay inside the object. */
export function WorkspaceNavigation({route, select}:{route:string;select:(route:string)=>void}) {
  const destination=navigation.find(item=>item.items.includes(route));
  if(!destination||destination.items.length<2)return null;
  const link=(id:string)=><button type="button" key={id} className="r-workspace-link" aria-current={route===id?'page':undefined} onClick={()=>select(id)}>{labels[id]}</button>;
  return <nav className="r-workspace-navigation" aria-label={`${destination.label}页面`}>
    {destination.sections?destination.sections.map(section=><details key={section.id} open={sectionFor(route)?.id===section.id}>
      <summary>{section.label}</summary><div>{[...section.primary,...section.secondary].map(link)}</div>
    </details>):destination.items.map(link)}
  </nav>;
}

export function CompactPageNavigation({route,select}:{route:string;select:(route:string)=>void}) {
  const destination=navigation.find(item=>item.items.includes(route));
  if(!destination||destination.items.length<2)return null;
  return <div className="r-compact-page-navigation"><label htmlFor="workspace-page">当前页面</label><select id="workspace-page" value={route} onChange={event=>select(event.target.value)}>
    {destination.sections?destination.sections.map(section=><optgroup key={section.id} label={section.label}>{[...section.primary,...section.secondary].map(id=><option key={id} value={id}>{labels[id]}</option>)}</optgroup>):destination.items.map(id=><option key={id} value={id}>{labels[id]}</option>)}
  </select></div>;
}
