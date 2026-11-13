"""Only deterministic small talk may bypass current business evidence reads."""
import re


def requires_evidence(question, topic):
    if topic != 'workspace' or not isinstance(question, str):
        return True
    text=question.strip()
    if re.fullmatch(r'(?:你好|您好|嗨|谢谢|多谢|早上好|晚上好|hi|hello|thanks)[\s，,。.!！?？]*',text,re.I):
        return False
    arithmetic=re.fullmatch(r'(?:请|帮我)?\s*(?:计算|算一下)?\s*([\d\s.+\-*/×÷()]+)\s*(?:等于几|是多少|等于多少|=)?\s*[?？。]?',text)
    if arithmetic and re.search(r'\d\s*[+\-*/×÷]\s*\d',arithmetic[1]):
        return False
    return True
