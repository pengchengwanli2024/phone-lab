/* Shared local-state descriptions; capability flags come from each domain. */
(()=>{
  const definitions=Object.freeze({
    queued:['等待执行','blue',false],running:['执行中','blue',false],cancelling:['正在取消','warning',false],
    awaiting_input:['等待补充信息','warning',false],awaiting_review:['待审核','warning',false],pending_review:['待审核','warning',false],
    partial:['部分完成','warning',true],completed:['已完成','success',true],succeeded:['已完成','success',true],success:['已完成','success',true],
    failed:['失败','danger',true],interrupted:['已中断','warning',true],cancelled:['已取消','gray',true]
  });
  const cancellable=new Set(['queued','running','awaiting_input','awaiting_review','pending_review']);
  const retryable=new Set(['failed','interrupted','cancelled']);
  function describe(code,capabilities={}){
    const row=typeof code==='string'&&Object.hasOwn(definitions,code)?definitions[code]:['状态未知','gray',false];
    return Object.freeze({label:row[0],tone:row[1],terminal:row[2],
      canCancel:capabilities?.cancel===true&&cancellable.has(code),canRetry:capabilities?.retry===true&&retryable.has(code)});
  }
  globalThis.CommerceStatus=Object.freeze({describe});
})();
