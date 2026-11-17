"""Stable conversation can answer directly; current facts and actions need reads."""
import re
from datetime import datetime,timedelta,timezone


def clock_question(question):
    if not isinstance(question,str)or not re.search(r'北京时间|UTC|几点|星期|周几|日期|年月日|几月',question):return False
    # Only clock/calendar vocabulary. "Today" in a news/order request never
    # grants an exemption from source reads or business validation.
    tokens=r'请|问|根据|按照|按|当前|现在|本机|北京时间|UTC|时间|告诉我|今天|今日|明天|后天|的|是|以及|和|及|年月日|日期|几月|几日|几号|几点|几分|几秒|星期几|星期|周几|多少|什么|哪天|年|月|日|号|[\s，,。？！?、：:]'
    return re.fullmatch('(?:'+tokens+')+',question)is not None


def clock_fields(stamp):
    utc=datetime.fromtimestamp(stamp,timezone.utc);local=utc.astimezone(timezone(timedelta(hours=8)))
    tomorrow=local+timedelta(days=1);weekdays=('星期一','星期二','星期三','星期四','星期五','星期六','星期日')
    return {'clock_source':'local_system_clock','now_utc':utc.strftime('%Y-%m-%d %H:%M:%S UTC'),
            'now_beijing':local.strftime('%Y-%m-%d %H:%M:%S +08:00'),'date_beijing':local.date().isoformat(),
            'weekday_beijing':weekdays[local.weekday()],'tomorrow_date_beijing':tomorrow.date().isoformat(),
            'tomorrow_weekday_beijing':weekdays[tomorrow.weekday()]}


def needs_page_read(question):
    public_news=re.search(r'新闻|要闻|news|headlines',question,re.I)
    # An archive destination does not make the visible page a news source.
    scope_text=re.sub(r'本机(?:公开研究)?(?:简报|报告|任务)', '', question)
    # A prohibition names protected resources, not sources to preload. Keep
    # explicit positive analysis/read clauses and discard only write denials.
    scope_text='，'.join(clause for clause in re.split(r'[，,。；;\n]',scope_text)
        if not re.match(r'\s*(?:不要|不|无需|禁止|别)(?:修改|写入|发布|更新|操作|删除|发送)',clause))
    external=re.search(r'https?://|公开(?:网络|来源|数据)|官方(?:接口|数据|网站|来源)|联网',scope_text,re.I)
    if external:
        scope_text=re.sub(r'https?://[^\s，。；、]+','',scope_text,flags=re.I)
        # A supplied URL owns references such as "this event". Only an explicit
        # local scope asks us to preload the unrelated page currently visible.
        return bool(re.search(r'本页|当前页面|这页|这里的(?:页面|订单|库存|商品)|我的|我们|本店|本机|已采集|快照|当前地图',scope_text))
    local=re.search(r'本页|页面|这里|这条|这款|这个|这些|我的|我们|本店|本机|已采集|快照|地图|库存|订单|商品',scope_text)
    return not public_news or bool(local)


def requires_evidence(question, topic):
    if topic != 'workspace' or not isinstance(question, str):
        return True
    text=question.strip()
    if clock_question(text):return False
    if re.fullmatch(r'(?:你好|您好|嗨|谢谢|多谢|早上好|晚上好|hi|hello|thanks)[\s，,。.!！?？]*',text,re.I):
        return False
    arithmetic=re.fullmatch(r'(?:请|帮我)?\s*(?:计算|算一下)?\s*([\d\s.+\-*/×÷()]+)\s*(?:等于几|是多少|等于多少|=)?\s*[?？。]?',text)
    if arithmetic and re.search(r'\d\s*[+\-*/×÷]\s*\d',arithmetic[1]):
        return False
    if (len(re.findall(r'\d+(?:\.\d+)?',text))>=2 and re.search(r'剩|合计|总共|计算|相加|减去|多少',text)
        and not re.search(r'当前|今天|今日|昨天|本周|最新|实时|现在|我的|我们|本店|库存|订单|成本|利润|售价|货币|汇率|任务|保存|归档|发布|提交|执行|同步',text)):
        return False
    # Concept explanations can use model knowledge. Current-page/temporal claims
    # still require evidence, including questions phrased as an explanation.
    concept=re.search(r'什么是|是什么意思|(?:解释|介绍|科普|讲讲|原理|区别)',text)
    current=re.search(r'当前|今天|今日|昨天|本周|最新|实时|现在|这个|这些|这里|本页|我的|我们|本店|这条|这款',text)
    if concept and not current:
        return False
    if re.fullmatch(r'(?:请问)?你(?:是谁|能做什么|可以做什么|能帮我做什么)[?？。！!]*',text):return False
    writing=re.search(r'翻译|润色|改写|写(?:一首|首|一篇|一段|一封|个).{0,12}(?:诗|故事|短文|文案|草稿|邮件)|(?:写作|写诗)',text)
    positive_clauses=[clause for clause in re.split(r'[，,。；;！？!?\n]',text)if not re.search(r'不要|无需|不必|禁止|别',clause)]
    if writing and not current and not re.search(r'发送|发布|提交|执行|删除|保存|归档|今天|最新|实时',' '.join(positive_clauses)):return False
    return True
