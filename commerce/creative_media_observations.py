"""Measured picture/audio features, separate from technical and human review."""
import math
import re

NUMBER = r'(-?\d+(?:\.\d+)?)'
MAX_LOG = 512 * 1024


def _intervals(log, kind, duration):
    rows = []; opened = None
    if kind == 'black':
        rows = [(float(a), float(b)) for a, b in re.findall(
            r'black_start:' + NUMBER + r'\s+black_end:' + NUMBER, log)]
    else:
        for event, value in re.findall(kind + r'_(start|end):\s*' + NUMBER, log):
            value = float(value)
            if event == 'start':
                opened = value if opened is None else min(opened, value)
            elif opened is not None:
                rows.append((opened, value)); opened = None
        if opened is not None: rows.append((opened, duration))
    merged = []
    for start, end in sorted(rows):
        start = max(0, min(duration, start)); end = max(start, min(duration, end))
        if end <= start: continue
        if merged and start <= merged[-1][1]: merged[-1][1] = max(merged[-1][1], end)
        else: merged.append([start, end])
    return [{'start_ms': round(a * 1000), 'end_ms': round(b * 1000)} for a, b in merged]


def _duration(rows):
    return sum(r['end_ms'] - r['start_ms'] for r in rows)


def _level(log, name):
    values = re.findall(name + r':\s*(-?inf|-?\d+(?:\.\d+)?)\s*dB', log)
    value = float(values[-1]) if values else None
    return value if value is not None and math.isfinite(value) else None


def inspect_output(studio, path, media):
    duration = media['duration_seconds']
    base = ['ffmpeg', '-nostdin', '-hide_banner', '-nostats', '-v', 'info', '-xerror', '-i', path]
    args = base + ['-map', '0:v:0', '-vf',
                   'blackdetect=d=0.1:pix_th=0.1:pic_th=0.98,freezedetect=n=-50dB:d=0.5']
    if media['has_audio']:
        args += ['-map', '0:a:0', '-af', 'silencedetect=noise=-50dB:d=0.5,volumedetect']
    args += ['-f', 'null', '-']
    try:
        result = studio.run(args, 40)
    except ValueError:
        # Unsupported analysis filters must not masquerade as a clean scan.
        # Full decode remains mandatory even when optional measurements fail.
        studio.run(['ffmpeg', '-nostdin', '-v', 'error', '-xerror', '-i', path,
                    '-map', '0:v:0', '-map', '0:a?', '-f', 'null', '-'], 40)
        return {'schema': 'commerce-media-observations-v1', 'status': 'unavailable',
                'decoded': True, 'video': None, 'audio': None,
                'reason': 'media_feature_scan_unavailable', 'semantic_motion_verified': None}
    raw = result.stderr
    log = raw[:MAX_LOG].decode('utf-8', errors='replace')
    black = _intervals(log, 'black', duration)
    frozen = _intervals(log, 'freeze', duration)
    silent = _intervals(log, 'silence', duration) if media['has_audio'] else None
    return {'schema': 'commerce-media-observations-v1',
            'status': 'completed' if len(raw) <= MAX_LOG else 'partial', 'decoded': True,
            'thresholds': {'black_min_ms': 100, 'black_pixel_luma': .1,
                           'black_frame_ratio': .98, 'freeze_min_ms': 500,
                           'freeze_noise_db': -50, 'silence_min_ms': 500, 'silence_dbfs': -50},
            'video': {'black_segments': black, 'black_duration_ms': _duration(black),
                      'frozen_segments': frozen, 'frozen_duration_ms': _duration(frozen)},
            'audio': {'status': 'analyzed' if media['has_audio'] else 'no_audio',
                      'silent_segments': silent, 'silent_duration_ms': _duration(silent) if silent is not None else None,
                      'mean_dbfs': _level(log, 'mean_volume') if media['has_audio'] else None,
                      'peak_dbfs': _level(log, 'max_volume') if media['has_audio'] else None},
            'semantic_motion_verified': None,
            'human_review_required': True,
            'limitations': ['冻结与黑场是画面特征，可能来自有意的静态画面或转场。',
                            '电平与静音不证明台词清楚、音轨授权或真实动作。']}
