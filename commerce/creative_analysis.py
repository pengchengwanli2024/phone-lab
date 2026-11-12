"""Bounded visual cut candidates; these are not semantic scene labels."""
import math
import re


def detect_shots(studio, path, duration):
    result=studio.run(['ffmpeg','-nostdin','-v','info','-i',path,'-an',
        '-vf',"fps=10,scale=320:-2,select='gt(scene,0.30)',showinfo",'-f','null','-'],60)
    candidates=[]
    for value in re.findall(r'pts_time:([0-9.]+)',result.stderr.decode(errors='replace')):
        at=round(float(value),3)
        if math.isfinite(at) and .35<=at<duration-.15 and (not candidates or at-candidates[-1]>=.35):
            candidates.append(at)
    retained=candidates
    if len(retained)>40:
        retained=[candidates[round(i*(len(candidates)-1)/39)] for i in range(40)]
    boundaries=[0.0]+retained+[duration]
    segments=[{'start_seconds':a,'end_seconds':b} for a,b in zip(boundaries,boundaries[1:]) if b>a]
    # Keep the existing four samples for a clip with no detected visual cuts.
    if candidates:
        times=[0.0]+candidates
        if len(times)>12:times=[times[round(i*(len(times)-1)/11)] for i in range(12)]
    else:times=[round(duration*i/4,3) for i in range(4)]
    return {'method':'ffmpeg_visual_difference_candidates','threshold':.30,'sample_fps':10,
        'cuts_seconds':retained,'detected_cut_count':len(candidates),'omitted_cut_count':len(candidates)-len(retained),
        'segments':segments,'keyframe_times':times,'semantic_labels':'not_performed',
        'limitations':['Visual differences can be flashes, motion or edits; gradual transitions may be missed.',
                        'Retained intervals may contain omitted cuts when the display limit is reached.']}


def production_markdown(project):
    """Human-readable private handoff, including facts and review boundaries."""
    def plain(value):
        value=str(value).replace('<','&lt;').replace('>','&gt;').replace('\n',' ')
        return re.sub(r'([\\`*_{}\[\]()#!|])',r'\\\1',value)
    brief=project['brief'];reference=brief.get('reference',{})
    lines=['# 创意制作清单 · 私有草稿','',plain(brief.get('product',{}).get('name','未命名项目')),
        '',f"资料版本：{project['revision']}",
        '合成测试资料。' if brief.get('synthetic') else '商品主张与最终成片仍需核对。','',
        '## 商品依据','']
    for f in project['plan']['facts']:lines.append(f"- {plain(f['id'])}：{plain(f['text'])}；依据：{plain(f['evidence_ref'])}")
    lines+=['','## 参考口播','',plain(reference.get('transcript','尚未提供')),
        '', '校对状态：'+('调用者已校对，未独立核实' if reference.get('transcript_review') else '待确认'),
        '', '## 制作文案','']
    scripts=[brief['reviewed_script']] if brief.get('reviewed_script') else project['plan']['scripts']
    for s in scripts:
        lines+=[f"### {plain(s['angle'])}",'',plain(s['hook']),plain(s['body']),plain(s['cta']),
            '卖点引用：'+', '.join(map(plain,s['fact_ids'])),'']
    lines+=['## 30秒分镜骨架','']
    for s in project['plan']['video_plan']['segments']:
        lines.append(f"- {s['start_ms']/1000:g}–{s['end_ms']/1000:g}秒：{plain(s['role'])}；待补实际镜头与动作。")
    lines+=['','## 原片分析回执','']
    for j in project.get('analysis_receipts',[]):
        r=j.get('result') or {};cuts=r.get('shot_analysis',{})
        lines.append(f"- 资料版本 {plain(j['input']['revision'])}；状态 {plain(j['status'])}；切点候选 {cuts.get('detected_cut_count','未检测')}；非语义分镜。")
        for s in cuts.get('segments',[]):lines.append(f"  - {s['start_seconds']:g}–{s['end_seconds']:g}秒：画面区间，待人工解释。")
    lines+=['','## 素材与产物','']
    for a in project['assets']:lines.append(f"- {plain(a.get('display_name',a['kind']))}；{plain(a['kind'])}；SHA-256 {a['sha256']}")
    lines+=['','## 待完成','',
        '- 核对转写、翻译与商品一致性；补充实际产品演示和授权音轨。',
        '- 当前图片为模板重排，视频为素材合成草稿；语义分镜、自动主体分割与真人生成尚未接入。',
        '- 完成观看验收与效果测试后再决定发布。本导出不发布任何内容。','']
    return '\n'.join(lines)
