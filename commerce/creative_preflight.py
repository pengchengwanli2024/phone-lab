"""Bounded checks for the existing local storyboard renderer, with no generation.

Video-container duration is observable; semantic motion and product identity
are not. Reports deliberately keep those judgements for viewing and review.
"""
import hashlib
import math

import creative_tools
from research import canonical, digest
from creative_studio import MAX_ASSET


def captions(spec):
    if spec.get('delivery_captions') is not None:
        values = spec['delivery_captions']
    elif spec.get('editing'):
        values = [row['caption'] for row in spec['editing']['shots']]
    else:
        script = spec['script']; body = script['body']
        if len(body) > 300:
            raise ValueError('creative_caption_too_long_shorten_product_facts')
        chunk = max(1, (len(body) + 2) // 3)
        values = [script['hook']] + [body[i * chunk:(i + 1) * chunk] for i in range(3)] + [script['cta']]
    if any(len(text) > 100 for text in values):
        raise ValueError('creative_caption_too_long_shorten_product_facts')
    return values


def inspect(studio, project_id, spec, asset_ids, audio_asset_id=None, expected_hashes=None):
    shots = spec['shots']; editing = spec.get('editing')
    if not isinstance(asset_ids, list) or not 1 <= len(shots) <= 8 or len(asset_ids) != len(shots):
        raise ValueError('creative_shot_assets_required')
    errors, warnings, rows, sources, media = [], [], [], {}, {}

    def issue(target, code, **details):
        target.append({'code': code, **details})

    available = {}
    for name in ('ffmpeg', 'ffprobe', 'rsvg-convert'):
        try:
            creative_tools.command(name); available[name] = True
        except ValueError:
            available[name] = False
            issue(errors, 'creative_local_tool_unavailable', tool=name)

    # Verify bytes before trusting registered metadata. Stream with an explicit
    # bound and detect replacement during the read; never expose local paths.
    for aid in dict.fromkeys([*asset_ids, *([audio_asset_id] if audio_asset_id else [])]):
        path, meta, kind = studio.asset(project_id, aid)
        if aid in asset_ids and kind not in ('product_image', 'generated_image', 'product_video', 'generated_video'):
            raise ValueError('creative_product_media_required')
        if aid == audio_asset_id and kind != 'audio':
            raise ValueError('creative_audio_required')
        before = path.stat(); hasher = hashlib.sha256(); size = 0
        if not 0 < before.st_size <= MAX_ASSET or before.st_size != meta['size']:
            raise ValueError('creative_asset_changed')
        with path.open('rb') as file:
            while chunk := file.read(1024 * 1024):
                size += len(chunk)
                if size > MAX_ASSET:
                    raise ValueError('creative_asset_changed')
                hasher.update(chunk)
        after = path.stat()
        signature = lambda s: (s.st_dev, s.st_ino, s.st_size, s.st_mtime_ns)
        if signature(before) != signature(after) or hasher.hexdigest() != meta['sha256'] or expected_hashes is not None and expected_hashes.get(aid) != meta['sha256']:
            raise ValueError('creative_asset_changed')
        sources[aid] = meta['sha256']
        observed = None
        if kind in ('product_video', 'generated_video', 'audio') and available['ffprobe']:
            try:
                observed = studio.probe(path)
                duration = observed['duration_seconds']
                if not math.isfinite(duration) or duration <= 0 or kind == 'audio' and not observed['has_audio'] or kind != 'audio' and not (observed['width'] and observed['height']):
                    raise ValueError('creative_invalid_media')
            except ValueError:
                issue(errors, 'creative_invalid_media', asset_id=aid); observed = None
        media[aid] = (kind, observed)

    try:
        texts = captions(spec)
    except ValueError as error:
        issue(errors, str(error)); texts = [''] * len(shots)
    cursor = 0; still_ms = video_ms = 0; looped = []; source_audio_ms = 0
    for index, (shot, aid) in enumerate(zip(shots, asset_ids)):
        start, end = shot['start_ms'], shot['end_ms']
        if type(start) is not int or type(end) is not int or start != cursor or end <= start:
            issue(errors, 'creative_timeline_invalid', shot_index=index)
        cursor = end; milliseconds = max(0, end - start)
        kind, observed = media[aid]; still = kind in ('product_image', 'generated_image')
        source_ms = round(observed['duration_seconds'] * 1000) if observed else None
        source_start = editing['shots'][index]['source_start_ms'] if editing else 0
        repeat = bool(not still and source_ms is not None and not editing and milliseconds > source_ms + 50)
        if still:
            still_ms += milliseconds
        else:
            video_ms += milliseconds
            if editing and source_ms is not None and source_start + milliseconds > source_ms + 50:
                issue(errors, 'creative_clip_range_exceeded', shot_index=index)
        if repeat:
            looped.append(index); issue(warnings, 'short_clip_looped', shot_index=index)
        if editing and editing['keep_source_audio'] and observed and observed['has_audio'] and not still:
            source_audio_ms += milliseconds
        rows.append({'index': index, 'asset_id': aid, 'sha256': sources[aid], 'kind': kind,
                     'duration_ms': milliseconds, 'source_start_ms': source_start,
                     'source_duration_ms': source_ms, 'looped': repeat, 'caption_characters': len(texts[index])})
    total = spec['duration_ms']
    if type(total) is not int or not 1000 <= total <= 90000 or cursor != total or len(texts) != len(shots):
        issue(errors, 'creative_timeline_invalid')
    if still_ms:
        issue(warnings, 'still_images_in_video', duration_ms=still_ms)
    if len(set(sources[aid] for aid in asset_ids)) < len(asset_ids):
        issue(warnings, 'repeated_source_media')
    audio_ms = None
    if audio_asset_id and media[audio_asset_id][1]:
        audio_ms = round(media[audio_asset_id][1]['duration_seconds'] * 1000)
        if audio_ms + 50 < total:
            issue(warnings, 'audio_padded_with_silence', duration_ms=total - audio_ms)
        elif audio_ms > total + 50:
            issue(warnings, 'audio_trimmed_to_timeline', duration_ms=audio_ms - total)
    # The renderer writes a silent track for still shots when preserving source
    # audio, then copies that track at assembly. Presence is not audibility.
    output_audio = bool(audio_asset_id or editing and editing['keep_source_audio'])
    if not output_audio:
        issue(warnings, 'no_output_audio')
    elif not audio_asset_id and not source_audio_ms:
        issue(warnings, 'silent_output_audio')
    elif not audio_asset_id and source_audio_ms < total:
        issue(warnings, 'source_audio_has_silent_sections', duration_ms=total - source_audio_ms)
    kind = 'still_image_video_draft' if still_ms == total else 'mixed_media_video_draft' if still_ms else 'supplied_video_edit'
    return {'schema': 'commerce-video-preflight-v1', 'can_render': not errors,
            'delivery_kind': kind, 'renderer': 'local_ffmpeg_storyboard',
            'spec_sha256': digest(canonical(spec)), 'source_assets': sources,
            'selection_sha256': digest(canonical([spec, asset_ids, audio_asset_id, sources])),
            'tools': available, 'shots': rows, 'errors': errors, 'warnings': warnings,
            'summary': {'duration_ms': total, 'still_duration_ms': still_ms, 'video_duration_ms': video_ms,
                        'video_duration_ratio': video_ms / total if total > 0 else None,
                        'looped_shot_indexes': looped, 'output_has_audio': output_audio,
                        'audio_duration_ms': audio_ms},
            'semantic_motion_verified': None, 'human_review_required': True,
            'external_generation_submitted': False,
            'limitations': ['视频占比按容器时长计算，不证明画面有真实动作。', '商品身份、动作、台词、素材权利与观看质量仍需人工审阅。']}


def output_review(preflight, spec, media, video_sha256, *, decoded=False):
    checks = {'duration': abs(media['duration_seconds'] - spec['duration_ms'] / 1000) <= .2,
              'dimensions': (media['width'], media['height']) == (spec['width'], spec['height']),
              'audio_presence': media['has_audio'] == preflight['summary']['output_has_audio'],
              'decode': decoded}
    return {'schema': 'commerce-video-quality-v1', 'preflight': preflight, 'checks': checks,
            'technical_status': 'passed' if all(checks.values()) else 'failed',
            'video_sha256': video_sha256, 'media': media, 'human_review_required': True,
            'semantic_motion_verified': None, 'publication_executed': False}
