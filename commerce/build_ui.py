"""Inline the operations module for already-running Harness hosts reading three UI files."""
from pathlib import Path
import os

ROOT = Path(__file__).resolve().parent / 'web'
BEGIN = '/* BEGIN GENERATED OPERATIONS MODULE */\n'
END = '/* END GENERATED OPERATIONS MODULE */\n'


def main():
    path = ROOT / 'app.js'; original = path.read_text(); body = original
    modules=[('/* BEGIN GENERATED ORGANIZATION MODULE */\n','/* END GENERATED ORGANIZATION MODULE */\n','organization-ui.js'),(BEGIN,END,'ops-ui.js'),('/* BEGIN GENERATED LIVE PLAN MODULE */\n','/* END GENERATED LIVE PLAN MODULE */\n','live-plan-ui.js'),('/* BEGIN GENERATED LIVE CONNECTION MODULE */\n','/* END GENERATED LIVE CONNECTION MODULE */\n','live-ui.js')]
    for start,end,_ in modules:
        if start in body:
            before, rest = body.split(start, 1)
            _, after = rest.split(end, 1)
            body = before + after
    content = ''.join(start+(ROOT/file).read_text()+'\n'+end for start,end,file in modules)+body
    temporary = path.with_name('app.build.tmp')
    temporary.write_text(content)
    if path.read_text()!=original:
        temporary.unlink();raise SystemExit('Concurrent UI change detected; reload current sources and retry.')
    os.replace(temporary, path)


if __name__ == '__main__': main()
