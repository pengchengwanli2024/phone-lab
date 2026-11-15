"""Render an explicit scene/closeup/demonstration shot list from actual assets."""
import hashlib
from creative_render import panel_svg, render_svg


def render(studio,job,data):
    pid=data['project_id'];folder=studio.folder(pid);spec=data['production_spec'];clips=[]
    script=spec['script'];body=script['body']
    if len(body)>300:raise ValueError('creative_caption_too_long_shorten_product_facts')
    width=max(1,(len(body)+2)//3)
    texts=[script['hook']]+[body[i*width:(i+1)*width] for i in range(3)]+[script['cta']]
    for index,(shot,aid) in enumerate(zip(spec['shots'],data['shot_assets'])):
        studio.stage(job,'render_shot_'+str(index+1))
        path,meta,kind=studio.asset(pid,aid)
        if hashlib.sha256(path.read_bytes()).hexdigest()!=data['source_assets'][aid]:raise ValueError('creative_asset_changed')
        text=texts[index] or data['brief']['product']['name']
        if len(text)>100:raise ValueError('creative_caption_too_long_shorten_product_facts')
        _,panel=render_svg(studio,folder,job+'-shot-caption-'+str(index),panel_svg(text))
        clip=folder/(job+'-shot-'+str(index)+'.mp4')
        filters='[0:v]scale=720:1280:force_original_aspect_ratio=decrease,pad=720:1280:(ow-iw)/2:(oh-ih)/2,setsar=1[base];[base][1:v]overlay=0:0[out]'
        argv=['ffmpeg','-nostdin','-v','error','-y']+(['-loop','1'] if kind in ('product_image','generated_image') else ['-stream_loop','-1'])
        argv+=['-i',path,'-loop','1','-i',panel,'-t',str((shot['end_ms']-shot['start_ms'])/1000),'-filter_complex_threads','1','-filter_complex',filters,
               '-map','[out]','-an','-r','24','-c:v','libx264','-threads','2','-preset','veryfast','-crf','28','-pix_fmt','yuv420p',clip]
        studio.run(argv,70);clips.append(clip)
    studio.stage(job,'assemble_storyboard')
    manifest=folder/(job+'-concat.txt');manifest.write_text(''.join("file '"+p.name+"'\n" for p in clips));manifest.chmod(0o600)
    output=folder/(job+'-story.mp4')
    args=['ffmpeg','-nostdin','-v','error','-y','-f','concat','-safe','1','-i',manifest]
    if data.get('audio_asset_id'):
        audio,meta,_=studio.asset(pid,data['audio_asset_id'])
        if hashlib.sha256(audio.read_bytes()).hexdigest()!=data['source_assets'][data['audio_asset_id']]:raise ValueError('creative_asset_changed')
        args+=['-i',audio,'-map','0:v:0','-map','1:a:0','-c:a','aac','-af','apad']
    else:args+=['-an']
    args+=['-t','30','-c:v','copy','-movflags','+faststart',output]
    studio.run(args,40);media=studio.probe(output)
    if abs(media['duration_seconds']-30)>.2:raise ValueError('creative_story_duration_mismatch')
    asset=studio.register(pid,'video_draft',output,{'display_name':spec['label']+' · 分镜剪辑草稿','origin':'derived','source_revision':data['revision'],
             'production_request_id':data['request_id'],'job_id':job,'media':media,'parent_asset_ids':data['shot_assets'],
             'audio_parent_asset_id':data.get('audio_asset_id'),'generator':'local_storyboard_edit','generated_actor_in_this_job':False,
             'voiceover_generated_in_this_job':False,'provided_audio_used':bool(data.get('audio_asset_id'))})
    for path in clips+[manifest]:path.unlink(missing_ok=True)
    return {'assets':[asset],'output_kind':'storyboard_edit_from_supplied_media','shots':spec['shots'],'missing':[],
            'limitations':['画面来自所选素材；本任务未生成新场景、演员或配音。','单镜头原音轨未混入；可选配音作为整片音轨。']}
