"""Render an explicit scene/closeup/demonstration shot list from actual assets."""
import hashlib
import json
import zipfile
from creative_render import panel_svg, render_svg
from creative_preflight import captions, inspect, output_review
from creative_media_observations import inspect_output
from creative_review_frames import contact_sheet
from creative_shot_cache import ShotCache


def render(studio,job,data):
    pid=data['project_id'];folder=studio.folder(pid);spec=data['production_spec'];clips=[]
    edit=spec.get('editing');width,height=spec['width'],spec['height'];duration=spec['duration_ms']/1000
    from creative_delivery import worker_guard,preflight_check,output_check
    sample_approval=worker_guard(studio,data)
    studio.stage(job,'production_preflight')
    preflight=preflight_check(spec,inspect(studio,pid,spec,data['shot_assets'],data.get('audio_asset_id'),data['source_assets']))
    if not preflight['can_render']:raise ValueError(preflight['errors'][0]['code'])
    texts=captions(spec)
    cache=ShotCache(studio)
    reuse={'scope':'verified_local_clips_same_project','cache_limit_bytes':cache.limit,
           'reused_shot_indexes':[],'rendered_shot_indexes':[],'shots':[]}
    for index,(shot,aid) in enumerate(zip(spec['shots'],data['shot_assets'])):
        studio.stage(job,'render_shot_'+str(index+1))
        path,meta,kind=studio.asset(pid,aid)
        if hashlib.sha256(path.read_bytes()).hexdigest()!=data['source_assets'][aid]:raise ValueError('creative_asset_changed')
        text=edit['shots'][index]['caption']if edit else texts[index]or data['brief']['product']['name']
        if len(text)>100:raise ValueError('creative_caption_too_long_shorten_product_facts')
        _,panel=render_svg(studio,folder,job+'-shot-caption-'+str(index),panel_svg(text,width,height)if text else f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}"></svg>')
        clip=folder/(job+'-shot-'+str(index)+'.mp4')
        filters=f'[0:v]scale={width}:{height}:force_original_aspect_ratio=decrease,pad={width}:{height}:(ow-iw)/2:(oh-ih)/2,setsar=1[base];[base][1:v]overlay=0:0[out]'
        still=kind in ('product_image','generated_image');seconds=(shot['end_ms']-shot['start_ms'])/1000
        start=edit['shots'][index]['source_start_ms']/1000 if edit else 0
        if edit and not still and start+seconds>meta.get('media',{}).get('duration_seconds',0)+.05:raise ValueError('creative_clip_range_exceeded')
        argv=['ffmpeg','-nostdin','-v','error','-y']+(['-loop','1']if still else ['-ss',str(start)]if edit else ['-stream_loop','-1'])
        argv+=['-i',path,'-loop','1','-i',panel]
        source_audio=bool(edit and edit['keep_source_audio'] and not still and meta.get('media',{}).get('has_audio'))
        if not source_audio:argv+=['-f','lavfi','-i','anullsrc=r=48000:cl=stereo']
        argv+=['-t',str(seconds),'-filter_complex_threads','1','-filter_complex',filters,'-map','[out]','-map','0:a:0'if source_audio else'2:a:0','-c:a','aac','-ar','48000','-ac','2',
               '-r','24','-c:v','libx264','-threads','2','-preset','veryfast','-crf','28','-pix_fmt','yuv420p',clip]
        placeholders={str(path):'SOURCE',str(panel):'CAPTION_PANEL',str(clip):'OUTPUT'}
        recipe={'source_sha256':data['source_assets'][aid],'source_kind':kind,
                'panel_sha256':hashlib.sha256(panel.read_bytes()).hexdigest(),
                'argv':[placeholders.get(str(a),str(a)) for a in argv]}
        key=cache.key(pid,recipe)
        hit=cache.restore(pid,key,clip,{'width':width,'height':height,'has_audio':True,'duration_seconds':seconds})
        if hit:
            reuse['reused_shot_indexes'].append(index)
        else:
            studio.run(argv,70);cache.store(pid,key,clip,job)
            reuse['rendered_shot_indexes'].append(index)
        reuse['shots'].append({'index':index,'key':key,'reused':bool(hit),
                               'origin_job_id':hit['origin_job_id'] if hit else job,
                               'clip_sha256':hashlib.sha256(clip.read_bytes()).hexdigest()})
        clips.append(clip)
    studio.stage(job,'assemble_storyboard')
    manifest=folder/(job+'-concat.txt');manifest.write_text(''.join("file '"+p.name+"'\n" for p in clips));manifest.chmod(0o600)
    output=folder/(job+'-story.mp4')
    args=['ffmpeg','-nostdin','-v','error','-y','-f','concat','-safe','1','-i',manifest]
    if data.get('audio_asset_id'):
        audio,meta,_=studio.asset(pid,data['audio_asset_id'])
        if hashlib.sha256(audio.read_bytes()).hexdigest()!=data['source_assets'][data['audio_asset_id']]:raise ValueError('creative_asset_changed')
        if edit and edit['keep_source_audio']:
            args+=['-i',audio,'-filter_complex','[1:a]apad[voice];[0:a][voice]amix=inputs=2:duration=first:normalize=0[a]','-map','0:v:0','-map','[a]','-c:a','aac']
        else:args+=['-i',audio,'-map','0:v:0','-map','1:a:0','-c:a','aac','-af','apad']
    elif edit and edit['keep_source_audio']:args+=['-map','0:v:0','-map','0:a:0','-c:a','copy']
    else:args+=['-an']
    args+=['-t',str(duration),'-c:v','copy','-movflags','+faststart',output]
    studio.run(args,40);media=studio.probe(output)
    if abs(media['duration_seconds']-duration)>.2:raise ValueError('creative_story_duration_mismatch')
    studio.stage(job,'verify_delivery')
    observations=inspect_output(studio,output,media)
    video_sha256=hashlib.sha256(output.read_bytes()).hexdigest()
    quality=output_review(preflight,spec,media,video_sha256,decoded=observations['decoded'])
    if quality['technical_status']!='passed':raise ValueError('creative_delivery_check_failed')
    studio.stage(job,'sample_review_frames')
    review_sheet,frame_index=contact_sheet(studio,folder,job,output,media)
    quality.update(media_observations=observations,review_frames=frame_index,render_reuse=reuse)
    if spec.get('delivery_commitment'):
        quality['delivery_commitment_check']=output_check(spec,media,observations)
    frame_index_path=folder/(job+'-review-frames.json')
    frame_index_path.write_text(json.dumps(frame_index,ensure_ascii=False,indent=2),encoding='utf-8')
    def stamp(ms):
        seconds,milli=divmod(ms,1000);minutes,second=divmod(seconds,60);hour,minute=divmod(minutes,60)
        return f'{hour:02}:{minute:02}:{second:02},{milli:03}'
    subtitle=folder/(job+'-captions.srt');subtitle.write_text('\n\n'.join(str(i+1)+'\n'+stamp(s['start_ms'])+' --> '+stamp(s['end_ms'])+'\n'+text for i,(s,text)in enumerate((s,edit['shots'][i]['caption']if edit else texts[i])for i,s in enumerate(spec['shots']))if text),encoding='utf-8')
    cover=folder/(job+'-cover.png');studio.run(['ffmpeg','-nostdin','-v','error','-y','-i',output,'-frames:v','1','-update','1',cover],20)
    document={'schema':'commerce-video-delivery-v1','production_request_id':data['request_id'],'project_id':pid,'request_source_revision':data['revision'],'shots':spec['shots'],'editing':edit,'source_assets':data['source_assets'],'media':media,'video_sha256':video_sha256,'quality_report':quality,'publication_executed':False,'synthetic':bool(data['brief'].get('synthetic'))}
    if spec.get('delivery_commitment'):
        document.update(delivery_commitment=spec['delivery_commitment'],delivery_role=spec['delivery_role'],sample_approval=sample_approval)
    delivery_manifest=folder/(job+'-manifest.json');delivery_manifest.write_text(json.dumps(document,ensure_ascii=False,indent=2),encoding='utf-8')
    quality_path=folder/(job+'-quality.json');quality_path.write_text(json.dumps(quality,ensure_ascii=False,indent=2),encoding='utf-8')
    package=folder/(job+'-delivery.zip')
    with zipfile.ZipFile(package,'w',compression=zipfile.ZIP_STORED)as archive:
        for path,name in [(output,'video.mp4'),(cover,'cover.png'),(subtitle,'captions.srt'),(delivery_manifest,'manifest.json'),(quality_path,'quality-report.json'),(review_sheet,'review-frames.png'),(frame_index_path,'review-frames.json')]:archive.write(path,name)
    asset=studio.register(pid,'video_draft',output,{'display_name':spec['label']+' · 分镜剪辑草稿','origin':'derived','source_revision':data['revision'],
             'production_request_id':data['request_id'],'job_id':job,'media':media,'parent_asset_ids':data['shot_assets'],
             'audio_parent_asset_id':data.get('audio_asset_id'),'generator':'local_storyboard_edit','generated_actor_in_this_job':False,
             'voiceover_generated_in_this_job':False,'provided_audio_used':bool(data.get('audio_asset_id'))})
    files=[asset]
    for path,kind,name in [(cover,'video_cover','成片封面'),(subtitle,'captions','可编辑字幕'),(delivery_manifest,'production_manifest','分镜与来源清单'),(quality_path,'quality_report','成片技术检查'),(review_sheet,'review_contact_sheet','实帧总览'),(frame_index_path,'review_frame_index','实帧取样位置'),(package,'delivery_package','视频交付包')]:
        files.append(studio.register(pid,kind,path,{'display_name':name,'origin':'derived','production_request_id':data['request_id'],'job_id':job,'parent_asset_ids':[asset['id']]}))
    for path in clips+[manifest]:path.unlink(missing_ok=True)
    return {'assets':files,'output_kind':'storyboard_edit_from_supplied_media','shots':spec['shots'],'quality_report':quality,'missing':[],
            'limitations':['画面来自所选素材；本任务未生成新场景、演员或配音。','音轨使用与裁剪以本次编辑版本为准；发布及素材权利仍需独立核对。']}
