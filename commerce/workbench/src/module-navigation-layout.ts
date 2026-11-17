/** Keep the current page visible; all remaining links stay available in More. */
export function visibleModuleLinks(widths:number[],available:number,active:number,more=44,gap=4):number[] {
  if(!widths.length)return [];
  if(widths.reduce((sum,width)=>sum+width,0)+gap*(widths.length-1)<=available)return widths.map((_,index)=>index);
  const selected=active>=0&&active<widths.length?active:0,visible=new Set([selected]);
  let used=widths[selected]+more+gap;
  for(let index=0;index<widths.length;index++){
    if(index===selected)continue;
    if(used+widths[index]+gap<=available){visible.add(index);used+=widths[index]+gap;}
  }
  return widths.map((_,index)=>index).filter(index=>visible.has(index));
}
