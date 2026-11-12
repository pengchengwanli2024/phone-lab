"""Read only the existing project Hermes profile; never connect a platform."""
import contextlib
import io
import json
from pathlib import Path


def inspect_profile():
    from hermes_constants import get_hermes_home
    home = get_hermes_home()
    expected = Path.home() / '.hermes/profiles/commerce-bot'
    if home.resolve() != expected.resolve() or expected.is_symlink() or not home.is_dir():
        raise ValueError('channel_profile_unavailable')
    from hermes_cli.plugins import discover_plugins
    discover_plugins()
    from gateway.config import load_gateway_config, Platform
    from gateway.platform_registry import platform_registry
    from agent.secret_scope import get_secret
    from gateway.status import read_runtime_status, runtime_status_pid_is_live, runtime_status_is_stale
    from hermes_cli.mcp_config import _get_mcp_servers
    config = load_gateway_config()
    runtime = read_runtime_status(home / 'gateway_state.json')
    live = runtime_status_pid_is_live(runtime)
    fresh = live and not runtime_status_is_stale(runtime)
    result = {}
    for name in ('feishu', 'wecom', 'wecom_callback', 'weixin', 'dingtalk'):
        entry = platform_registry.get(name)
        required = list(entry.required_env or ()) if entry else []
        missing = [key for key in required if not get_secret(key)]
        settings = config.platforms.get(Platform(name))
        state = (runtime or {}).get('platforms', {}).get(name, {})
        observed = state.get('state') if isinstance(state, dict) else None
        result[name] = {'adapter_available': entry is not None,
                        'credentials_present': bool(required) and not missing,
                        'missing_fields': missing, 'gateway_enabled': bool(settings and settings.enabled),
                        'runtime_status': 'not_running' if not live else 'stale' if not fresh else 'connected_reported' if observed == 'connected' else 'not_connected'}
    servers = _get_mcp_servers()
    commerce = servers.get('commerce')
    return {'profile_available': True, 'shared_core_configured': isinstance(commerce, dict) and commerce.get('enabled', True) is not False,
            'platforms': result}


if __name__ == '__main__':
    try:
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            result = inspect_profile()
        print(json.dumps(result))
    except Exception:
        print(json.dumps({'error': 'channel_probe_unavailable'}))
        raise SystemExit(1)
