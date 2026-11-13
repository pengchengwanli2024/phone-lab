"""Recognize explicit human research intent without accepting model authorization."""
import re


def _excluded(message):
    return bool(re.search(
        r'如何|怎么|介绍|功能[？?]|是否支持|'
        r'(?:不要|别|不用|无需|停止|取消|暂停).{0,16}(?:研究|调研|选品|分析|采集|收集)',
        message))


def _explicit(message):
    subject = re.search(r'选品|市场调研|调研|研究.*市场|市场行情|市场分析|分析.*市场', message)
    execute = re.search(r'请|帮我|开始|采集|收集|保存.*候选|筛选|我要|我想', message)
    return not _excluded(message) and bool(subject and execute)


def requests_research(message, context):
    if not isinstance(message, str):
        return False
    russian = context.get('market') == 'RU' or re.search(r'俄罗斯|俄区|俄语|\bRU\b', message, re.I)
    return bool(russian and _explicit(message))


def research_request(message, context, *, previous=None, has_research=False):
    """Return human request text, or None. No execution or database access.

    The caller supplies only the immediately previous, same-revision/scope turn
    from its own database. Existing research tasks use their own continuation or
    explicit resume path; their history cannot authorize another task.
    """
    if not isinstance(message, str) or not message.strip() or _excluded(message):
        return None
    if requests_research(message, context):
        return message
    if (has_research or not isinstance(previous, dict)
            or previous.get('status') != 'awaiting_input'
            or not previous.get('questions')):
        return None
    question = previous.get('question')
    if not isinstance(question, str) or not _explicit(question):
        return None
    combined = question + '\n补充：' + message
    return combined if requests_research(combined, context) else None
