"""Explicit protocol adapters. Model IDs and workflow graphs are operator supplied."""
import base64
import copy
import json
import re
from urllib.parse import quote, urlencode
import uuid

from .transport import json_request, request, TransportError

SOURCES = {
    'comfyui': 'https://github.com/Comfy-Org/docs/blob/main/development/comfyui-server/comms_routes.mdx',
    'bytedance_ark_image': 'https://docs.volcengine.com/docs/ark/image-generation-api?lang=zh',
    'bytedance_ark_video': 'https://docs.volcengine.com/docs/ark/video-generation-tutorial?lang=zh',
    'dashscope_wan26_video': 'https://www.alibabacloud.com/help/en/model-studio/legacy-image-to-video-api-reference/',
    'minimax_video_v2': 'https://platform.minimax.io/docs/api-reference/video-generation-v2-create',
}
NATIVE = {'bytedance_ark_image': ('bytedance', 'image'), 'bytedance_ark_video': ('bytedance', 'video'),
          'dashscope_wan26_video': ('alibaba', 'video'), 'minimax_video_v2': ('minimax', 'video')}
# These limits describe the implemented request builders, rather than a vendor's
# broader model family. Current video builders inject one first-frame image.
INPUT_IMAGE_LIMITS = {'generic_json_async': 8, 'comfyui': 1, 'bytedance_ark_image': 8,
                      'bytedance_ark_video': 1, 'dashscope_wan26_video': 1, 'minimax_video_v2': 1}


def input_image_limit(config):
    return min(config.get('capabilities', {}).get('max_input_images', 1), INPUT_IMAGE_LIMITS[config['adapter']])

GENERIC = {'probe_path': '/health', 'submit_path': '/jobs', 'poll_path': '/jobs/{{task_id}}',
           'submit_body': {'model': '{{model}}', 'prompt': '{{prompt}}', 'images': '{{images}}',
                           'width': '{{width}}', 'height': '{{height}}', 'duration_seconds': '{{duration_seconds}}'},
           'task_id_path': 'id', 'status_path': 'status', 'outputs_path': 'outputs', 'output_url_path': 'url', 'output_base64_path': 'base64',
           'states': {'pending': ['pending', 'queued', 'running'], 'succeeded': ['succeeded', 'completed'], 'failed': ['failed', 'cancelled']}}


def get_path(value, path, default=None):
    if not path: return value
    try:
        for part in path.split('.'):
            value = value[int(part)] if isinstance(value, list) else value[part]
        return value
    except (KeyError, TypeError, ValueError, IndexError):
        return default


def set_path(value, path, replacement):
    parts = path.split('.')
    for part in parts[:-1]:
        value = value[int(part)] if isinstance(value, list) else value[part]
    part = parts[-1]
    if isinstance(value, list): value[int(part)] = replacement
    else:
        if part not in value: raise ValueError('media_provider_workflow_binding_missing')
        value[part] = replacement


def render(value, context):
    if isinstance(value, dict): return {k: render(v, context) for k, v in value.items()}
    if isinstance(value, list): return [render(v, context) for v in value]
    if not isinstance(value, str): return value
    match = re.fullmatch(r'\{\{([a-z0-9_]+)\}\}', value)
    if match:
        if match[1] not in context: raise ValueError('media_provider_unknown_template_variable')
        return context[match[1]]
    def replace(match):
        if match[1] not in context: raise ValueError('media_provider_unknown_template_variable')
        result = context[match[1]]
        if isinstance(result, (dict, list)): raise ValueError('media_provider_template_scalar_required')
        return str(result)
    return re.sub(r'\{\{([a-z0-9_]+)\}\}', replace, value)


def _content(context):
    return [{'type': 'text', 'text': context['prompt']},
            {'type': 'image_url', 'image_url': {'url': context['image_data_uri_0']}, 'role': 'first_frame'}]


def protocol(config):
    adapter = config['adapter']
    supplied = config.get('protocol', {})
    if adapter == 'generic_json_async': return supplied
    if adapter == 'bytedance_ark_image':
        return {'submit_path': '/images/generations', 'submit_body': {'model': '{{model}}', 'prompt': '{{prompt}}', 'image': '{{image_data_uris}}', 'response_format': 'b64_json'},
                'outputs_path': 'data', 'output_url_path': 'url', 'output_base64_path': 'b64_json', **{k: v for k, v in supplied.items() if k == 'probe_path'}}
    if adapter == 'bytedance_ark_video':
        return {'submit_path': '/contents/generations/tasks', 'poll_path': '/contents/generations/tasks/{{task_id}}',
                'task_id_path': 'id', 'status_path': 'status', 'outputs_path': 'content.video_url',
                'states': {'pending': ['queued', 'running'], 'succeeded': ['succeeded'], 'failed': ['failed', 'cancelled', 'expired']},
                **{k: v for k, v in supplied.items() if k == 'probe_path'}}
    if adapter == 'dashscope_wan26_video':
        return {'submit_path': '/api/v1/services/aigc/video-generation/video-synthesis', 'poll_path': '/api/v1/tasks/{{task_id}}',
                'task_id_path': 'output.task_id', 'status_path': 'output.task_status', 'outputs_path': 'output.video_url',
                'states': {'pending': ['PENDING', 'RUNNING'], 'succeeded': ['SUCCEEDED'], 'failed': ['FAILED', 'CANCELED'], 'unknown': ['UNKNOWN']},
                **{k: v for k, v in supplied.items() if k == 'probe_path'}}
    if adapter == 'minimax_video_v2':
        return {'submit_path': '/v2/video_generation', 'poll_path': '/v2/query/video_generation/{{task_id}}',
                'task_id_path': 'task_id', 'status_path': 'task.status', 'outputs_path': 'task.content.url',
                'states': {'pending': ['queued', 'running'], 'succeeded': ['succeeded'], 'failed': ['failed', 'cancelled']},
                **{k: v for k, v in supplied.items() if k == 'probe_path'}}
    raise ValueError('media_provider_unknown_adapter')


def _normalized(config, response, *, submitted=False):
    p = protocol(config)
    state = get_path(response, p.get('status_path')) if p.get('status_path') else None
    task_id = get_path(response, p.get('task_id_path')) if p.get('task_id_path') else None
    if task_id is not None and (not isinstance(task_id, (str, int)) or not re.fullmatch(r'[a-zA-Z0-9_:.\-]{1,240}', str(task_id))):
        raise TransportError('media_provider_invalid_task_id', ambiguous=submitted)
    states = p.get('states') or GENERIC['states']
    outputs = get_path(response, p['outputs_path'], [])
    if isinstance(outputs, str): outputs = [{'url': outputs}]
    elif isinstance(outputs, dict): outputs = [outputs]
    if not isinstance(outputs, list): raise TransportError('media_provider_invalid_outputs', ambiguous=submitted)
    normalized = []
    for output in outputs:
        if isinstance(output, str): normalized.append({'url': output}); continue
        if not isinstance(output, dict): raise TransportError('media_provider_invalid_outputs', ambiguous=submitted)
        url = output.get('url') if isinstance(get_path(response, p['outputs_path']), str) else get_path(output, p.get('output_url_path', 'url'))
        b64 = get_path(output, p.get('output_base64_path', 'base64'))
        if output.get('error'): raise TransportError('media_provider_output_rejected')
        if url: normalized.append({'url': url})
        elif b64: normalized.append({'base64': b64})
    if state in states.get('failed', []): status = 'failed'
    elif state in states.get('succeeded', []) or (state is None and normalized): status = 'succeeded'
    elif state in states.get('unknown', []): status = 'unknown'
    elif state in states.get('pending', []) or (state is None and task_id): status = 'submitted' if submitted else 'pending'
    else: raise TransportError('media_provider_unknown_response_state', ambiguous=submitted)
    return {'status': status, 'provider_status': str(state or status), 'remote_task_id': str(task_id) if task_id is not None else None, 'outputs': normalized}


def probe(config, api_key):
    path = '/system_stats' if config['adapter'] == 'comfyui' else protocol(config).get('probe_path')
    if not path: return 'not_available'
    json_request(config, 'GET', path, api_key=api_key)
    return 'passed'


def submit(config, context, api_key):
    if config['adapter'] == 'comfyui': return _comfy_submit(config, context, api_key)
    p = protocol(config)
    adapter = config['adapter']
    params = copy.deepcopy(config.get('parameters', {}))
    if adapter == 'bytedance_ark_video':
        body = {**params, 'model': context['model'], 'content': _content(context), 'duration': context['duration_seconds']}
    elif adapter == 'dashscope_wan26_video':
        # This adapter is explicitly the 2.6 protocol. Newer Wan contracts differ.
        body = {'model': context['model'], 'input': {'prompt': context['prompt'], 'img_url': context['image_data_uri_0']},
                'parameters': {**params, 'duration': context['duration_seconds']}}
        config = {**config, '_headers': {'X-DashScope-Async': 'enable'}}
    elif adapter == 'minimax_video_v2':
        body = {**params, 'model': context['model'], 'content': _content(context), 'duration': context['duration_seconds'], 'response_format': 'task'}
    else:
        body = render(p['submit_body'], context)
        if adapter == 'bytedance_ark_image': body.update({k: v for k, v in params.items() if k not in ('model', 'prompt', 'image', 'response_format')})
    result = json_request(config, 'POST', p['submit_path'], data=body, api_key=api_key, limit=48 * 1024 * 1024)
    return _normalized(config, result, submitted=True)


def poll(config, task_id, api_key):
    if config['adapter'] == 'comfyui': return _comfy_poll(config, task_id, api_key)
    p = protocol(config)
    if not p.get('poll_path'): raise ValueError('media_provider_poll_not_configured')
    result = json_request(config, 'GET', render(p['poll_path'], {'task_id': quote(task_id, safe='')}), api_key=api_key, limit=48 * 1024 * 1024)
    return _normalized(config, result)


def cancel(config, task_id, api_key):
    if config['adapter'] == 'comfyui': return 'not_available_no_global_interrupt'
    p = protocol(config)
    if not p.get('cancel_path'): return 'not_available'
    json_request(config, 'POST', render(p['cancel_path'], {'task_id': quote(task_id, safe='')}),
                 data=render(p.get('cancel_body', {}), {'task_id': task_id}), api_key=api_key)
    return 'request_acknowledged_not_confirmed'


def _comfy_submit(config, context, api_key):
    graph = copy.deepcopy(config['workflow'])
    bindings = config['bindings']
    for key in ('prompt', 'width', 'height', 'duration_seconds', 'model'):
        if key in bindings: set_path(graph, bindings[key], context[key])
    if 'image' in bindings:
        if len(context['images']) != 1: raise ValueError('media_provider_comfy_single_image_binding_required')
        image = context['images'][0]
        boundary = 'commerce-' + uuid.uuid4().hex
        filename = uuid.uuid4().hex + ('.png' if image['mime'] == 'image/png' else '.jpg')
        body = ('--' + boundary + '\r\nContent-Disposition: form-data; name="image"; filename="' + filename + '"\r\nContent-Type: ' + image['mime'] + '\r\n\r\n').encode() + base64.b64decode(image['base64'])
        body += ('\r\n--' + boundary + '\r\nContent-Disposition: form-data; name="type"\r\n\r\ninput\r\n--' + boundary + '--\r\n').encode()
        uploaded = json_request(config, 'POST', '/upload/image', data=body, content_type='multipart/form-data; boundary=' + boundary, api_key=api_key)
        name = uploaded.get('name'); sub = uploaded.get('subfolder', '')
        if not isinstance(name, str) or not name or any(x in name for x in ('/', '\\', '..')) or not isinstance(sub, str) or any(x in sub for x in ('..', '\\')) or sub.startswith('/'):
            raise TransportError('media_provider_invalid_comfy_upload', ambiguous=True)
        set_path(graph, bindings['image'], (sub + '/' if sub else '') + name)
    response = json_request(config, 'POST', '/prompt', data={'prompt': graph, 'client_id': context['job_id']}, api_key=api_key)
    task = response.get('prompt_id')
    if response.get('error') or response.get('node_errors'): raise TransportError('media_provider_comfy_workflow_rejected')
    if not isinstance(task, str) or not re.fullmatch(r'[a-zA-Z0-9_\-]{1,240}', task): raise TransportError('media_provider_invalid_task_id', ambiguous=True)
    return {'status': 'submitted', 'provider_status': 'queued', 'remote_task_id': task, 'outputs': []}


def _comfy_poll(config, task_id, api_key):
    response = json_request(config, 'GET', '/history/' + quote(task_id, safe=''), api_key=api_key)
    record = response.get(task_id)
    if not record: return {'status': 'pending', 'provider_status': 'pending', 'outputs': []}
    status = record.get('status', {})
    if status.get('status_str') == 'error': return {'status': 'failed', 'provider_status': 'error', 'outputs': []}
    if not status.get('completed'): return {'status': 'pending', 'provider_status': 'running', 'outputs': []}
    outputs = []
    for node in config['output_nodes']:
        output = record.get('outputs', {}).get(node, {})
        for field in ('images', 'videos', 'gifs'):
            for file in output.get(field, []):
                name = file.get('filename'); sub = file.get('subfolder', '')
                if not isinstance(name, str) or not name or any(x in name for x in ('/', '\\', '..')) or not isinstance(sub, str) or sub.startswith('/') or any(x in sub for x in ('\\', '..')) or file.get('type') != 'output':
                    raise ValueError('media_provider_invalid_comfy_output')
                outputs.append({'url': config['base_url'] + '/view?' + urlencode({'filename': name, 'subfolder': sub, 'type': 'output'})})
    return {'status': 'succeeded', 'provider_status': 'success', 'outputs': outputs}


def catalog_adapters():
    examples = [
        ('generic_json_async', '自定义 JSON 生成接口', {'provider': 'custom', 'adapter': 'generic_json_async', 'base_url': 'https://media.example.invalid', 'media_kind': 'image', 'protocol': GENERIC}),
        ('comfyui', '本机 ComfyUI 工作流', {'provider': 'local', 'adapter': 'comfyui', 'base_url': 'http://127.0.0.1:8188', 'media_kind': 'image',
          'workflow': {}, 'bindings': {'prompt': '6.inputs.text', 'image': '10.inputs.image'}, 'output_nodes': ['9']}),
        ('bytedance_ark_image', '火山方舟图片', {'provider': 'bytedance', 'adapter': 'bytedance_ark_image', 'base_url': 'https://ark.cn-beijing.volces.com/api/v3', 'media_kind': 'image'}),
        ('bytedance_ark_video', '火山方舟视频', {'provider': 'bytedance', 'adapter': 'bytedance_ark_video', 'base_url': 'https://ark.cn-beijing.volces.com/api/v3', 'media_kind': 'video', 'parameters': {}}),
        ('dashscope_wan26_video', '阿里 Wan 2.1–2.6 首帧视频', {'provider': 'alibaba', 'adapter': 'dashscope_wan26_video', 'base_url': 'https://WORKSPACE_ID.ap-southeast-1.maas.aliyuncs.com', 'media_kind': 'video', 'parameters': {'resolution': '720P'}}),
        ('minimax_video_v2', 'MiniMax V2 视频', {'provider': 'minimax', 'adapter': 'minimax_video_v2', 'base_url': 'https://api.minimax.io', 'media_kind': 'video', 'parameters': {'resolution': '768P', 'ratio': '9:16'}}),
    ]
    return [{'id': ident, 'version': '1', 'label': label, 'max_input_images': INPUT_IMAGE_LIMITS[ident], 'configuration_example': {'label': label, 'model': '', 'enabled': False, 'capabilities': {'image_input': True, 'max_input_images': 8 if ident == 'bytedance_ark_image' else 1, **({'min_duration_seconds': 4, 'max_duration_seconds': 15} if value['media_kind'] == 'video' else {})}, **value},
             'protocol_source': SOURCES.get(ident), 'live_verified': False} for ident, label, value in examples]
