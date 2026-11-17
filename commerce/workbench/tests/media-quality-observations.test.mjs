import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import vm from 'node:vm';

function view(report){
  const window={CommerceUI:{escape:value=>String(value).replaceAll('&','&amp;').replaceAll('<','&lt;').replaceAll('>','&gt;'),alert:(text)=>`<p>${text}</p>`}};
  vm.runInNewContext(readFileSync(new URL('../../web/media-quality-ui.js',import.meta.url),'utf8'),{window});
  return window.CommerceMediaQualityView(report);
}
const base={technical_status:'passed',checks:{duration:true,dimensions:true,audio_presence:true,decode:true},preflight:{summary:{duration_ms:2500,still_duration_ms:2500,video_duration_ms:0},delivery_kind:'still_image_video_draft',errors:[],warnings:[]}};

test('measured freeze, silence and reuse remain separate from human content approval',()=>{
  const html=view({...base,media_observations:{status:'completed',video:{black_duration_ms:0,frozen_duration_ms:2000},audio:{status:'analyzed',silent_duration_ms:1500,peak_dbfs:-91}},render_reuse:{reused_shot_indexes:[0,1,3,4],rendered_shot_indexes:[2]}});
  assert.match(html,/冻结画面 2秒/);assert.match(html,/静音 1.5秒/);
  assert.match(html,/峰值 -91 dBFS/);assert.match(html,/复用 4个镜头/);assert.match(html,/新制作 1个镜头/);
  assert.match(html,/内容仍待人工审阅/);assert.doesNotMatch(html,/动作已通过|音质已通过/);
});
test('unavailable detector and absent audio never appear as zero-valued measurements',()=>{
  assert.match(view({...base,media_observations:{status:'unavailable',video:null,audio:null}}),/画面与声音检测暂不可用/);
  const html=view({...base,media_observations:{status:'completed',video:{black_duration_ms:0,frozen_duration_ms:0},audio:{status:'no_audio',silent_duration_ms:null,peak_dbfs:null}}});
  assert.match(html,/没有音轨/);assert.doesNotMatch(html,/静音 0秒|峰值 0 dBFS/);
});
test('historic reports do not acquire new observations or reuse claims',()=>{
  const html=view(base);assert.doesNotMatch(html,/画面与声音检测|复用 .*镜头/);
});
