/* Shared report view: technical checks never stand in for content review. */
window.CommerceMediaQualityView=report=>{
  if(!report)return '';
  const ui=window.CommerceUI,e=ui.escape,p=report.preflight||report,q=report.preflight?report:null;
  const labels={still_images_in_video:'包含静态图片',short_clip_looped:'短镜头将循环播放',repeated_source_media:'多个分镜复用同一素材',no_output_audio:'成片没有音轨',silent_output_audio:'仅保留静音轨道，没有素材原声',audio_padded_with_silence:'补充音轨较短，尾部补静音',audio_trimmed_to_timeline:'补充音轨较长，按成片时长裁剪',source_audio_has_silent_sections:'部分分镜没有原声',creative_clip_range_exceeded:'裁剪入点与时长超出素材范围',creative_local_tool_unavailable:'本机制作工具不可用',creative_invalid_media:'素材媒体信息无效',creative_timeline_invalid:'时间线存在缺口、重叠或时长不一致',creative_caption_too_long_shorten_product_facts:'字幕过长，请精简文字'};
  const kind={still_image_video_draft:'图文视频草稿',mixed_media_video_draft:'图片与视频混剪草稿',supplied_video_edit:'已有视频素材剪辑'};
  const message=x=>(labels[x.code]||'请核对素材与制作条件')+(x.shot_index==null?'':' · 分镜 '+(x.shot_index+1))+(x.tool?' · '+x.tool:'');
  const summary=p.summary;
  function observations(){
    const o=q?.media_observations;if(!o)return '';
    if(o.status==='unavailable')return ui.alert('画面与声音检测暂不可用；文件检查结果仍单独保留。','warning');
    const seconds=ms=>Math.round(ms/10)/100;
    const audio=o.audio?.status==='no_audio'?'没有音轨':`静音 ${seconds(o.audio.silent_duration_ms)}秒${o.audio.peak_dbfs==null?' · 未测得有限峰值电平':' · 峰值 '+o.audio.peak_dbfs+' dBFS'}`;
    const ranges=(label,rows)=>rows?.length?`<p>${e(label+'：'+rows.map(r=>seconds(r.start_ms)+'–'+seconds(r.end_ms)+'秒').join('，'))}</p>`:'';
    return `<div aria-label="画面与声音检测"><h4>画面与声音检测</h4>${o.status==='partial'?ui.alert('检测记录不完整，请结合实帧与原片核对。','warning'):''}<p>${e('黑场 '+seconds(o.video.black_duration_ms)+'秒 · 冻结画面 '+seconds(o.video.frozen_duration_ms)+'秒 · '+audio)}</p><p class="muted">黑场、冻结和静音可能来自有意的画面或转场，请结合原片审阅。</p><details><summary>检测位置与阈值</summary>${ranges('黑场',o.video.black_segments)}${ranges('冻结画面',o.video.frozen_segments)}${ranges('静音',o.audio.silent_segments)}<p class="muted">黑场至少0.1秒；冻结、低于−50 dBFS的静音至少0.5秒。</p></details></div>`;
  }
  const commitment=q?.delivery_commitment_check;
  const promise=commitment?`<p role="status">${e('交付要求检查：'+(commitment.status==='passed'?'通过 · 内容仍待人工审阅':'未通过 · 请调整后重新确认'))}</p>`:'';
  const reuse=q?.render_reuse;
  const reused=reuse?`<p class="muted">${e('本机制作：复用 '+reuse.reused_shot_indexes.length+'个镜头 · 新制作 '+reuse.rendered_shot_indexes.length+'个镜头')}</p>`:'';
  const frames=q?.review_frames?`<p class="muted">实帧总览包含 ${q.review_frames.samples.length}个成片取样，时间为近似位置。</p>`:'';
  return `<section class="media-review-report" aria-label="${q?'成片技术检查':'视频制作预检'}"><h3>${q?'成片技术检查':'视频制作预检'}</h3><p role="status">${e(q?(q.technical_status==='passed'?'文件技术检查通过 · 内容仍待人工审阅':'文件技术检查未通过'):(p.can_render?'可以本机制作':'请先解决制作问题'))}</p><p>${e(kind[p.delivery_kind]||'视频草稿')} · ${summary.duration_ms/1000}秒 · 静态图片 ${summary.still_duration_ms/1000}秒 · 视频素材 ${summary.video_duration_ms/1000}秒</p>${(p.errors||[]).map(x=>ui.alert(message(x),'danger')).join('')}${(p.warnings||[]).map(x=>ui.alert(message(x),'warning')).join('')}<p class="muted">视频占比按容器时长计算，实际动作、商品身份、台词与素材权利须人工审阅。</p>${q?`<p class="muted">${e(Object.entries({duration:'时长',dimensions:'画幅',audio_presence:'音轨',decode:'完整解码'}).map(([key,label])=>label+'：'+(q.checks[key]?'通过':'未通过')).join(' · '))}</p>`:''}${promise}${observations()}${frames}${reused}</section>`;
};
