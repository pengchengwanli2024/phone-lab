"""Isolated browser fixture. Every business record and model answer is synthetic."""
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import server
import translation
from seed_intel_workspace import seed as seed_intel
from fixture_agent_cases import seed as seed_case
from article_binding import text_hash


def synthetic_model(data, route=None):
    return translation.validate_response(data, {
        'provider': 'synthetic-no-network', 'model': 'synthetic',
        'translations': [{'id': value['id'], 'zh': '合成中文资料：' + value['text']}
                         for value in data['items']]})


if __name__ == '__main__':
    translation.run_model = synthetic_model
    server.Handler.secret = server.token()
    app = server.Handler.service = seed_intel(server.STATE)
    seed_case(app)
    def capture(doc):
        text = 'Synthetic publisher body 25 USD. This is an isolated fixture. '
        return dict(text=text, content_sha256=text_hash(text), source_url=doc['url'],
                    captured_at='2026-01-01T00:00:00Z', routes=['synthetic-a','synthetic-b'])
    app.articles.fetcher = capture
    # No device bridge or platform/model workers. Collection still uses the real
    # fixed public-feed worker and the candidate's private evidence directory.
    app.collections.start(recover=True)
    http = server.CommerceHTTPServer(('127.0.0.1', server.PORT), server.Handler)
    try:
        http.serve_forever()
    finally:
        app.collections.stop()
        http.server_close()
