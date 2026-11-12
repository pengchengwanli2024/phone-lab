"""Local editable SVG layouts and caption panels; no generative provider calls."""
import base64
from pathlib import Path
from xml.sax.saxutils import escape


def text_rows(text, width=20, limit=240):
    text=text.replace('\r',' ').replace('\n',' ')
    if len(text)>limit: raise ValueError('creative_caption_too_long_shorten_product_facts')
    return [text[i:i+width] for i in range(0,len(text),width)] or ['']


def panel_svg(text):
    rows=text_rows(text,20,100)
    y=1080-len(rows)*38
    spans=''.join(f'<tspan x="360" dy="{0 if i==0 else 38}">{escape(row)}</tspan>' for i,row in enumerate(rows))
    return f'<svg xmlns="http://www.w3.org/2000/svg" width="720" height="1280"><rect x="26" y="{y-40}" width="668" height="{len(rows)*38+44}" rx="12" fill="#111827" fill-opacity=".86"/><text x="360" y="{y}" font-family="sans-serif" font-size="30" text-anchor="middle" fill="white">{spans}</text></svg>'


def layout_svg(path, title, fact, kind):
    mime='image/png' if path.suffix=='.png' else 'image/jpeg'
    image=base64.b64encode(path.read_bytes()).decode()
    colors={'product_main':('#ffffff','#111827'),'usage_scene':('#e9edf3','#16324a'),'advertisement':('#101827','#ffffff')}
    background,ink=colors[kind]
    title_rows=text_rows(title,18,54);fact_rows=text_rows(fact,22,88)
    title_text=''.join(f'<tspan x="64" dy="{0 if i==0 else 54}">{escape(row)}</tspan>' for i,row in enumerate(title_rows))
    fact_text=''.join(f'<tspan x="64" dy="{0 if i==0 else 38}">{escape(row)}</tspan>' for i,row in enumerate(fact_rows))
    return f'<svg xmlns="http://www.w3.org/2000/svg" xmlns:xlink="http://www.w3.org/1999/xlink" width="1080" height="1080"><rect width="1080" height="1080" fill="{background}"/><text x="64" y="88" font-family="sans-serif" font-size="46" fill="{ink}">{title_text}</text><rect x="64" y="220" width="952" height="580" rx="18" fill="#ffffff"/><image x="84" y="240" width="912" height="540" preserveAspectRatio="xMidYMid meet" xlink:href="data:{mime};base64,{image}"/><text x="64" y="880" font-family="sans-serif" font-size="30" fill="{ink}">{fact_text}</text></svg>'


def render_svg(studio, folder, name, content):
    source=folder/(name+'.svg');image=folder/(name+'.png')
    source.write_text(content,encoding='utf-8');source.chmod(0o600)
    studio.run(['rsvg-convert','-o',image,source],30)
    image.chmod(0o600)
    return source,image
