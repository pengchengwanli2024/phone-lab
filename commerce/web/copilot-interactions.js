/* Pure reading helpers. Controlled Markdown subset; no raw HTML or media loading. */
((target)=>{
  const MAX_TEXT=5000;
  const plainText=value=>typeof value==='string'?value:typeof value==='number'||typeof value==='boolean'?String(value):'';
  const escape=value=>value.replace(/[&<>"']/g,char=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[char]));
  function linkURL(value){
    if(!/^https?:\/\//i.test(value)||/[\s\\<>\x00-\x1f\x7f]/.test(value))return null;
    try{const url=new URL(value);return ['http:','https:'].includes(url.protocol)&&url.hostname&&!url.username&&!url.password?url.href:null}catch{return null}
  }
  function inline(text,depth=0,links=true){
    if(depth>3)return escape(text);
    let html='',index=0;
    while(index<text.length){
      const char=text[index];
      if(char==='\\'&&/[\\`*_\[\]{}()#!+\-.|]/.test(text[index+1]||'')){html+=escape(text[index+1]);index+=2;continue}
      if(char==='`'){
        const marker=text.slice(index).match(/^`+/)[0],end=text.indexOf(marker,index+marker.length);
        if(end>=0){html+='<code>'+escape(text.slice(index+marker.length,end))+'</code>';index=end+marker.length;continue}
      }
      const image=char==='!'&&text[index+1]==='[';
      if(links&&(char==='['||image)){
        const start=index+(image?2:1),middle=text.indexOf('](',start),end=middle<0?-1:text.indexOf(')',middle+2);
        if(end>=0){
          const url=linkURL(text.slice(middle+2,end));
          if(url){html+='<a href="'+escape(url)+'" target="_blank" rel="noopener noreferrer">'+(image?'图片：':'')+inline(text.slice(start,middle),depth+1,false)+'</a>';index=end+1;continue}
          // Consume an unsafe image/link as literal data; do not reinterpret a
          // nested label as a second opportunity to create an active anchor.
          html+=escape(text.slice(index,end+1));index=end+1;continue;
        }
      }
      if(char==='*'||char==='_'){
        const marker=text.startsWith(char+char,index)?char+char:char,end=text.indexOf(marker,index+marker.length);
        const insideWord=char==='_'&&/[\p{L}\p{N}]/u.test(text[index-1]||'');
        if(!insideWord&&end>index+marker.length){const tag=marker.length===2?'strong':'em';html+='<'+tag+'>'+inline(text.slice(index+marker.length,end),depth+1,links)+'</'+tag+'>';index=end+marker.length;continue}
      }
      html+=char==='\n'?'<br>':escape(char);index++;
    }
    return html;
  }
  function cells(line){
    const values=[];let value='',code='',index=0;
    while(index<line.length){
      const char=line[index];
      if(char==='\\'&&line[index+1]==='|'){value+='\\|';index+=2;continue}
      if(char==='`'){const marker=line.slice(index).match(/^`+/)[0];if(!code)code=marker;else if(code===marker)code='';value+=marker;index+=marker.length;continue}
      if(char==='|'&&!code){values.push(value.trim());value=''}else value+=char;
      index++;
    }
    values.push(value.trim());
    if(values[0]===''&&line.trimStart().startsWith('|'))values.shift();
    if(values.at(-1)===''&&line.trimEnd().endsWith('|'))values.pop();
    return values;
  }
  function tableAt(lines,index){
    if(!lines[index]?.includes('|')||!lines[index+1]?.includes('|'))return null;
    const header=cells(lines[index]),rules=cells(lines[index+1]);
    if(!header.length||header.length>12||header.length!==rules.length||!rules.every(rule=>/^:?-{3,}:?$/.test(rule)))return null;
    return {header,align:rules.map(rule=>rule.startsWith(':')&&rule.endsWith(':')?'center':rule.startsWith(':')?'left':rule.endsWith(':')?'right':'')};
  }
  const fence=line=>line.match(/^ {0,3}(`{3,}|~{3,})([a-zA-Z0-9_-]{0,32})\s*$/);
  const heading=line=>line.match(/^ {0,3}(#{1,6})[ \t]+(.+)$/);
  const listItem=line=>line.match(/^ {0,3}([-+*]|\d{1,6}[.)])[ \t]+(.+)$/);
  const ordered=item=>/^\d/.test(item[1]);
  function markdown(value){
    const source=plainText(value);if(!source)return '';
    let text=source.slice(0,MAX_TEXT);if(/[\uD800-\uDBFF]$/.test(text))text=text.slice(0,-1);
    const clipped=text.length<source.length,lines=text.replace(/\r\n?/g,'\n').split('\n');let html='',index=0;
    while(index<lines.length){
      const line=lines[index];if(!line.trim()){index++;continue}
      const code=fence(line);
      if(code){
        const content=[],marker=code[1];index++;
        const closing=new RegExp('^ {0,3}'+(marker[0]==='`'?'`':'~')+'{'+marker.length+',}\\s*$');
        while(index<lines.length&&!closing.test(lines[index]))content.push(lines[index++]);
        if(index<lines.length)index++;
        html+='<pre><code'+(code[2]?' class="language-'+escape(code[2])+'"':'')+'>'+escape(content.join('\n'))+'</code></pre>';continue;
      }
      const title=heading(line);
      if(title){html+='<h'+title[1].length+'>'+inline(title[2])+'</h'+title[1].length+'>';index++;continue}
      const table=tableAt(lines,index);
      if(table){
        const attr=column=>table.align[column]?' style="text-align:'+table.align[column]+'"':'';
        html+='<div class="copilot-markdown-table"><table><thead><tr>'+table.header.map((cell,column)=>'<th'+attr(column)+'>'+inline(cell)+'</th>').join('')+'</tr></thead><tbody>';index+=2;
        while(index<lines.length&&lines[index].trim()&&lines[index].includes('|')){
          const row=cells(lines[index]);if(row.length!==table.header.length)break;
          html+='<tr>'+row.map((cell,column)=>'<td'+attr(column)+'>'+inline(cell)+'</td>').join('')+'</tr>';index++;
        }
        html+='</tbody></table></div>';continue;
      }
      const item=listItem(line);
      if(item){
        const isOrdered=ordered(item),tag=isOrdered?'ol':'ul',start=isOrdered?parseInt(item[1],10):1;
        html+='<'+tag+(isOrdered&&start!==1?' start="'+start+'"':'')+'>';
        while(index<lines.length){const next=listItem(lines[index]);if(!next||ordered(next)!==isOrdered)break;html+='<li>'+inline(next[2])+'</li>';index++}
        html+='</'+tag+'>';continue;
      }
      const paragraph=[line];index++;
      while(index<lines.length&&lines[index].trim()&&!fence(lines[index])&&!heading(lines[index])&&!listItem(lines[index])&&!tableAt(lines,index))paragraph.push(lines[index++]);
      html+='<p>'+inline(paragraph.join('\n'))+'</p>';
    }
    return html+(clipped?'<p class="copilot-truncated">内容较长，仅展示前 5000 个字符。</p>':'');
  }
  function suggestions(context={},page={}){
    context=context&&typeof context==='object'?context:{};page=page&&typeof page==='object'?page:typeof page==='string'?{page}:{};
    const route=page.page||context.module||'',section=page.section||'';
    // An explicit visible page wins over a previous chat's selected object.
    const entity=page.entity||(!page.page||page.page===context.module?context.entity:null)||{};let rows;
    if(['operations','restock'].includes(route)||['cost','stock'].includes(section))rows=[
      ['核对测算口径','根据当前已填参数，解释成本或补货测算的口径，区分已知值、假设与未知项。'],
      ['找出缺失参数','检查当前测算还缺哪些实际参数，以及缺失参数会影响哪些结论。'],
      ['分析关键边界','根据当前已有数据，说明价格、费用或库存变化对测算结果的影响；缺少依据时保留未知。']];
    else if(route==='phones')rows=[['核对设备连接','解释当前设备连接、只读预览和控制租约状态；没有设备时列出缺少的接入条件。'],['排查预览问题','根据当前页面已有回执排查设备预览问题，缺少的连接信息保持未知。'],['说明控制状态','解释当前设备的控制权限、租约和停止方式；不要未经明确授权控制设备。']];
    else if(['intelligence','news'].includes(route))rows=[
      [entity.kind==='intel'?'解读这条情报':'解读当前情报',entity.kind==='intel'?'根据当前选中的情报与已有原文，概括主要事件、时间和仍待核实的信息。':'概括当前情报页面的主要事件，保留来源、时间和未核实状态。'],
      ['核对来源与时效','核对当前情报的来源、发布时间与本机采集时间，指出过期、缺证或互相矛盾的信息。'],
      ['分析潜在影响','根据当前情报与明确的业务范围，区分已观察事实和可能影响；没有经营关联依据时不要推断。']];
    else if(route==='overview')rows=[
      ['解读当前概览','结合当前筛选范围，解释经营概览与趋势，区分实际数据、示例数据和未知项。'],
      ['排查经营异常','根据当前概览，找出值得优先核对的经营异常，并说明还需要哪些证据。'],
      ['梳理待办优先级','根据当前经营概览与已有提醒，按影响和依据整理需要人工核对的下一步。']];
    else if(['orders','store-ops','order-imports','support'].includes(route))rows=[
      ['梳理订单状态',`根据${entity.kind==='order'?'这笔订单':'当前订单范围'}的已有数据，解释订单状态、时间与尚未确认的信息。`],
      ['核对异常原因','核对当前订单范围内的异常迹象，区分已知原因和需要补充的证据。'],
      ['整理处理建议','根据当前订单资料整理可审阅的处理建议，并标明需要人工确认的条件。']];
    else if(route==='products'||entity.kind==='product')rows=[
      ['分析当前库存','根据当前商品与库存口径，说明可售情况、预警和缺少的依据。'],
      ['核对商品资料','检查当前商品资料的一致性，区分已确认事实和待补充字段。'],
      ['梳理商品下一步','根据当前商品的资料和状态，整理下一步核对事项及所需输入。']];
    else if(route==='creative')rows=[
      ['梳理创意方向','根据当前创意项目与已提供素材，整理适合的表达方向和需要补充的素材。'],
      ['核对商品主张','核对当前创意内容里的商品主张，标出缺少商品事实支持的表述。'],
      ['整理制作清单','根据当前创意项目整理文案、图片与视频制作清单，保留未完成和未验证项。']];
    else if(['tasks','agent'].includes(route)||entity.kind==='task')rows=[
      ['解释当前进度','根据当前任务的真实状态与回执，解释已完成、等待中和结果未知的部分。'],
      ['核对阻塞原因','根据当前任务记录解释阻塞或失败原因，区分已观察原因和未验证推断。'],
      ['整理恢复条件','根据当前任务状态列出恢复所需的输入与确认条件，保留原任务和已有结果。']];
    else if(route==='listing'||section==='content')rows=[
      ['核对商品内容','根据当前商品事实核对内容草稿，指出不一致或缺少依据的字段。'],
      ['整理上架缺项','根据当前上架准备状态整理尚缺的资料与核对条件，不把草稿视为已发布。'],
      ['检查资料一致性','检查当前商品事实、内容与目标范围的一致性，并说明未验证项。']];
    else if(['research','pilots','insights'].includes(route))rows=[
      ['核对研究依据','核对当前研究或候选的来源、时间与证据强度，区分观察、推断和待核实信息。'],
      ['比较候选差异','根据当前已有资料比较候选差异；资料不足时说明缺口，不估造市场数据。'],
      ['列出验证清单','根据当前研究结论整理后续需要验证的问题、来源和必要输入。']];
    else if(entity.kind==='case'||['workspace','organization','workflow'].includes(route))rows=[
      ['梳理当前工作项','根据当前工作项的资料与状态，整理已完成事项和当前主线。'],
      ['核对资料缺项','检查当前工作项的资料缺项与版本一致性，说明哪些结论仍需核实。'],
      ['整理交接事项','根据当前工作项的缺项和责任范围，整理可审阅的交接事项及所需输入。']];
    else if(['models','connections','platforms','live','memory'].includes(route))rows=[
      ['核对可用能力','根据当前页面的实际连接与可用状态，区分已配置、已连接和已验证的能力。'],
      ['解释当前状态','解释当前连接或资料状态及其影响；缺少回执时保留未知。'],
      ['梳理配置缺项','根据当前页面整理需要补充的配置或资料，不包含密钥、令牌或密码。']];
    else rows=[
      ['解释当前页面','根据当前页面与明确范围，解释已有资料、状态和需要关注的信息。'],
      ['核对缺失信息','根据当前页面，说明还缺哪些信息，以及它们会影响哪些判断。'],
      ['整理下一步','根据当前已有依据整理需要人工核对的下一步，并保留未知与未验证项。']];
    return rows;
  }
  target.CommerceCopilotInteractions=Object.freeze({markdown,suggestions,plainText});
})(typeof window==='object'?window:globalThis);
