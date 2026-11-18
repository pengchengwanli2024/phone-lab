"""Fence agent-authored text before it is placed in another agent's prompt.

Studied from the Open Duet / suparagent team fence (backend/app/team/fence.py):
text one agent wrote is untrusted input for the next agent, so role markers,
invisible characters and embedded credentials must not survive into the prompt.

Independent standard-library implementation with two deliberate differences:

* Cyrillic is never transliterated. This project serves Russian marketplaces, so
  folding Cyrillic letters to Latin look-alikes would corrupt genuine answers.
  Mixed-script words are only flagged, never rewritten.
* Only the prompt copy is fenced. Stored answers, stored answer hashes and any
  business record keep their exact bytes.
"""
import re
import unicodedata

MAX_TEXT = 2000
INVISIBLE = dict.fromkeys(map(ord, '\u200b\u200c\u200d\u2060\ufeff\u00ad\u180e'), None)
CONTROL = re.compile(r'[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]')
# Line-leading role or directive markers, with or without brackets.
MARKER = re.compile(r'^(\s*)((?:#{1,6}\s*)?(?:system|assistant|user|developer|system prompt|instruction|instructions|approval|approved|authori[sz]ed|tool|tool result|function|admin|root|政策|系统|助手|用户|指令|批准|已批准|授权|工具结果)\s*[:：>\]】])', re.I)
LONG_SECRET = re.compile(r'\b(?=[A-Za-z0-9_\-]{24,}\b)(?=[A-Za-z0-9_\-]*[0-9])[A-Za-z0-9_\-]{24,}\b')
NAMED_SECRET = re.compile(r'(?i)\b(api[_-]?key|access[_-]?token|refresh[_-]?token|secret|password|passwd|pwd|authorization|bearer|token|cookie)\b(\s*[:=]\s*|\s+)(\S+)')
AUTH_HEADER = re.compile(r'(?i)\b(bearer|basic)\s+[A-Za-z0-9._~+/=\-]{8,}')
MIXED_SCRIPT = re.compile(r'\b(?=[^\s]*[A-Za-z])(?=[^\s]*[\u0400-\u04ff])[^\s]+\b')
CJK_CONTROL = re.compile(r'[\u202a-\u202e\u2066-\u2069]')
# Bracketed role labels such as 【系统】 or 【工具结果】 are folded the same way.
WRAPPED = re.compile(r'^(\s*)【\s*(system|assistant|user|developer|instruction|approval|tool|tool result|admin|系统|助手|用户|指令|批准|已批准|授权|工具结果|工具调用)\s*】', re.I)


def _flag(flags, code):
    if code not in flags:
        flags.append(code)


def fence_text(value, limit=MAX_TEXT):
    """Return {'text', 'flags'} for one untrusted agent-authored block."""
    if not isinstance(value, str):
        raise ValueError('fence_invalid_text')
    if not isinstance(limit, int) or not 1 <= limit <= 200000:
        raise ValueError('fence_invalid_limit')
    flags = []
    text = unicodedata.normalize('NFKC', value)
    if text != value:
        _flag(flags, 'unicode_normalized')
    stripped = text.translate(INVISIBLE)
    if stripped != text:
        _flag(flags, 'invisible_characters_removed')
        text = stripped
    cleaned = CONTROL.sub('', text)
    if cleaned != text:
        _flag(flags, 'control_characters_removed')
        text = cleaned
    bidi = CJK_CONTROL.sub('', text)
    if bidi != text:
        _flag(flags, 'bidi_controls_removed')
        text = bidi
    auth = AUTH_HEADER.sub(lambda m: m.group(1) + ' [隐藏]', text)
    if auth != text:
        _flag(flags, 'credential_like_text_masked')
        text = auth
    named = NAMED_SECRET.sub(lambda m: m.group(1) + m.group(2) + '[隐藏]', text)
    if named != text:
        _flag(flags, 'credential_like_text_masked')
        text = named
    long_token = LONG_SECRET.sub('[隐藏]', text)
    if long_token != text:
        _flag(flags, 'credential_like_text_masked')
        text = long_token
    if MIXED_SCRIPT.search(text):
        _flag(flags, 'mixed_script_words')
    lines, folded = [], 0
    for line in text.split('\n'):
        wrapped = WRAPPED.match(line)
        if wrapped:
            line = wrapped.group(1) + '(' + line.lstrip()
            folded += 1
            lines.append(line)
            continue
        match = MARKER.match(line)
        if match:
            line = match.group(1) + '(' + line[match.start(2):]
            folded += 1
        lines.append(line)
    if folded:
        _flag(flags, 'line_marker_folded')
    text = '\n'.join(lines).strip()
    if len(text) > limit:
        text = text[:limit]
        _flag(flags, 'truncated')
    if not text:
        _flag(flags, 'empty_after_fence')
    return {'text': text, 'flags': flags, 'original_length': len(value), 'fenced_length': len(text)}


def fence_line(value, limit=256):
    """Fence one single-line field: no newlines, no angle brackets, bounded."""
    if not isinstance(value, str):
        raise ValueError('fence_invalid_text')
    result = fence_text(value.replace('\r', ' ').replace('\n', ' '), limit)
    text = result['text'].replace('<', '\uff1c').replace('>', '\uff1e')
    return {'text': text, 'flags': result['flags']}


def fence_collaboration(collaboration):
    """Copy a collaboration binding with each prior answer fenced, never rewritten elsewhere."""
    if not isinstance(collaboration, dict):
        raise ValueError('fence_invalid_collaboration')
    result = dict(collaboration)
    answers = []
    for answer in collaboration.get('prior_answers') or []:
        if not isinstance(answer, dict):
            raise ValueError('fence_invalid_collaboration')
        fenced = fence_text(answer.get('answer') or '')
        answers.append({**answer, 'answer': fenced['text'], 'fenced': fenced['flags']})
    result['prior_answers'] = answers
    result['fenced'] = True
    return result
