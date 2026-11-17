/* A bounded DOM window over the original complete, paginated conversation. */
;(function(target){
  function create(size=40){
    size=Math.max(2,Math.min(80,size));
    let identity=null,first=null,following=true,start=0;
    const turnKey=turn=>turn.id||turn.run?.id||turn.question;
    function range(thread,reading){
      const turns=thread?.turns||[];
      if(identity!==thread?.id){identity=thread?.id;first=null;following=true;start=0}
      const last=Math.max(0,turns.length-size);
      if(following)start=last;
      else{const index=turns.findIndex(turn=>turnKey(turn)===first);start=index<0?Math.min(start,last):Math.min(index,last)}
      if(reading?.anchor&&!reading.bottom){const index=turns.findIndex(turn=>'turn:'+turnKey(turn)===reading.anchor||'run:'+turn.run?.id===reading.anchor);if(index>=0&&index<start){start=index;following=false}}
      first=turns[start]?turnKey(turns[start]):null;
      const end=Math.min(turns.length,start+size);
      return {turns:turns.slice(start,end),before:start,after:turns.length-end,total:turns.length,start,end};
    }
    return {range,move(thread,direction){range(thread);start=Math.max(0,Math.min(Math.max(0,thread.turns.length-size),start+Math.sign(direction)*size));following=start>=thread.turns.length-size;first=thread.turns[start]?turnKey(thread.turns[start]):null;return range(thread)},latest(thread){identity=thread?.id;following=true;first=null;return range(thread)}};
  }
  function capture(log){
    const selection=log?.ownerDocument?.getSelection?.();
    if(!selection||selection.isCollapsed||!log.contains(selection.anchorNode)||!log.contains(selection.focusNode))return null;
    const point=(node,offset)=>{const element=(node.nodeType===1?node:node.parentElement)?.closest('[data-message-key]');if(!element||!log.contains(element))return null;const range=log.ownerDocument.createRange();range.selectNodeContents(element);range.setEnd(node,offset);return {key:element.dataset.messageKey,offset:range.toString().length}};
    const anchor=point(selection.anchorNode,selection.anchorOffset),focus=point(selection.focusNode,selection.focusOffset);
    return anchor&&focus?{anchor,focus}:null;
  }
  function restore(log,saved){
    if(!log||!saved)return;
    const point=saved=>{const element=[...log.querySelectorAll('[data-message-key]')].find(el=>el.dataset.messageKey===saved.key);if(!element)return null;const walker=log.ownerDocument.createTreeWalker(element,4);let offset=saved.offset,node;while((node=walker.nextNode())){if(offset<=node.textContent.length)return {node,offset};offset-=node.textContent.length}return null};
    const a=point(saved.anchor),b=point(saved.focus);if(a&&b)log.ownerDocument.getSelection()?.setBaseAndExtent(a.node,a.offset,b.node,b.offset);
  }
  target.CommerceCopilotReading={create,capture,restore};
})(typeof window==='undefined'?globalThis:window);
