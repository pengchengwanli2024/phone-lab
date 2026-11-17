"""Open the existing local phone manager without exposing its authentication."""
import webbrowser


def open_in_browser(service):
    from runtime import PORT
    ticket = service.live.new_setup_ticket()
    try:
        opened = bool(webbrowser.open(f'http://127.0.0.1:{PORT}/phones?ticket=' + ticket))
    except (OSError, webbrowser.Error):
        opened = False
    return {'opened': opened, 'status': 'opened_local_phone_management' if opened else 'browser_open_unconfirmed'}
