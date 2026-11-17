"""Eight actual output samples, labeled with approximate extraction positions."""
import base64
import hashlib

from creative_render import render_svg


def contact_sheet(studio, folder, name, video, media):
    duration = media['duration_seconds']
    raw = folder / (name + '-frames-raw.png')
    # One pass keeps the bounded review cheap. Sampling is approximate; these
    # timestamps must never be presented as frame-exact evidence.
    studio.run(['ffmpeg', '-nostdin', '-v', 'error', '-y', '-i', video, '-an', '-vf',
                f'fps=8/{duration}:start_time=0:round=near,scale=240:176:force_original_aspect_ratio=decrease,'
                'pad=240:200:(ow-iw)/2:0,tile=4x2:nb_frames=8',
                '-frames:v', '1', '-threads', '1', raw], 40)
    samples = [{'requested_ms': round(i * duration * 1000 / 8),
                'column': i % 4, 'row': i // 4} for i in range(8)]
    image = base64.b64encode(raw.read_bytes()).decode()
    labels = ''.join(f'<text x="{s["column"] * 240 + 10}" y="{s["row"] * 200 + 190}" '
                     f'font-family="sans-serif" font-size="14" fill="white">'
                     f'{s["requested_ms"] / 1000:.2f}s</text>' for s in samples)
    source, sheet = render_svg(studio, folder, name + '-review-frames',
        '<svg xmlns="http://www.w3.org/2000/svg" xmlns:xlink="http://www.w3.org/1999/xlink" '
        f'width="960" height="400"><image width="960" height="400" xlink:href="data:image/png;base64,{image}"/>'
        + labels + '</svg>')
    raw.unlink(missing_ok=True)
    return sheet, {'schema': 'commerce-review-frames-v1', 'samples': samples,
                   'times_are_approximate': True, 'columns': 4, 'cell_width': 240, 'cell_height': 200,
                   'video_sha256': hashlib.sha256(video.read_bytes()).hexdigest(),
                   'contact_sheet_sha256': hashlib.sha256(sheet.read_bytes()).hexdigest(),
                   'human_review_required': True}
