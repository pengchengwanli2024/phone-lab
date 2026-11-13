"""Fresh native Hermes Agent process for a single pinned, tool-free request.

Installed native APIs are version checked by integration tests. Credentials stay
under Hermes ownership; no secret value is copied into the commerce request.
"""
import contextlib
import json
from pathlib import Path
import sys


def run():
    request = json.loads(sys.stdin.buffer.read(131073))['request']
    route = request['route']
    if route['provider'] != 'codex': raise ValueError('unsupported_host_route')
    # Bind before importing config, plugins, model tools or the Agent. The
    # installed managed-worker policy freezes an empty customization snapshot,
    # disables startup migrations, hooks, memory and provider fallback.
    from agent.safe_worker_policy import _bind_safe_worker_policy
    _bind_safe_worker_policy(safe_mode=True, ignore_user_config=True, config={})
    with contextlib.redirect_stdout(sys.stderr):
        from run_agent import AIAgent
        agent = AIAgent(provider='openai-codex', model=route['model'], enabled_toolsets=[],
                        max_iterations=1, max_tokens=3500, quiet_mode=True, save_trajectories=False,
                        skip_context_files=True, skip_memory=True, skip_background_review=True,
                        load_soul_identity=False, fallback_model={}, run_budget_seconds=90,
                        ephemeral_system_prompt=request['instructions'], platform='tool', cwd=str(Path.cwd()))
        try:
            if agent.tools or agent.valid_tool_names: raise ValueError('native_tools_not_empty')
            if agent.model != route['model'] or agent.provider not in ('openai-codex', 'codex'):
                raise ValueError('native_model_route_changed')
            result = agent.run_conversation(user_message=json.dumps({
                'request_id': request['request_id'], 'input': request['payload'],
                'output_schema': request['output_schema']}, ensure_ascii=False), conversation_history=[])
            if not isinstance(result, dict) or result.get('failed') or result.get('partial') or result.get('error'):
                raise ValueError('native_result_unconfirmed')
            value = json.loads(result['final_response'])
            if agent.tools or agent.valid_tool_names or agent.model != route['model']:
                raise ValueError('native_scope_changed')
            receipt = {'session_id': agent.session_id, 'provider': 'codex', 'model': agent.model,
                       'finish_reason': 'completed', 'tools_used': []}
        finally:
            close = getattr(agent, 'close', None)
            if callable(close): close()
    sys.stdout.write(json.dumps({'data': value, 'receipt': receipt}, ensure_ascii=False))


if __name__ == '__main__':
    try: run()
    except Exception:
        # Native diagnostics may contain private provider data. Only a stable
        # unconfirmed outcome reaches the caller; the parent retains UNKNOWN.
        sys.stderr.write('bounded_hermes_native_outcome_unconfirmed\n')
        raise SystemExit(1)
