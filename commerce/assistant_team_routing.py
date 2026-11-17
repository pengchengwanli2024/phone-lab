"""Bounded local responder selection, independent of models and credentials."""
import re

MODES = ('all', 'auto', 'collaborate')


def keywords(value):
    if not isinstance(value, list) or len(value) > 16 or any(
            not isinstance(s, str) or not s.strip() or len(s) > 40 or
            any(ord(c) < 32 for c in s) for s in value):
        raise ValueError('team_invalid_keywords')
    result = [s.strip() for s in value]
    if len({s.casefold() for s in result}) != len(result):
        raise ValueError('team_invalid_keywords')
    return result


def normalize_routing(value, members):
    if value is None:
        value = {}
    if not isinstance(value, dict) or set(value) - {'mode', 'lead_id', 'rules', 'max_rounds', 'mentions_only'}:
        raise ValueError('team_invalid_routing')
    mode = value.get('mode', 'all')
    lead = value.get('lead_id') or members[0]
    rounds = value.get('max_rounds', 1)
    rules = value.get('rules', [])
    mentions_only = value.get('mentions_only', False)
    if mode not in MODES or lead not in members or type(rounds) is not int or not 1 <= rounds <= 3 or type(mentions_only) is not bool:
        raise ValueError('team_invalid_routing')
    if not isinstance(rules, list) or len(rules) > 12:
        raise ValueError('team_invalid_routing')
    normalized = []
    for rule in rules:
        if not isinstance(rule, dict) or set(rule) != {'keywords', 'member_ids'}:
            raise ValueError('team_invalid_routing')
        terms = keywords(rule['keywords'])
        targets = rule['member_ids']
        if (not terms or not isinstance(targets, list) or not 1 <= len(targets) <= 4 or
                any(not isinstance(s, str) or s not in members for s in targets) or len(set(targets)) != len(targets)):
            raise ValueError('team_invalid_routing')
        normalized.append({'keywords': terms, 'member_ids': targets})
    return {'mode': mode, 'lead_id': lead, 'rules': normalized, 'max_rounds': rounds, 'mentions_only': mentions_only}


def choose_members(channel, profiles, question, mode=None):
    config = normalize_routing(channel.get('routing'), channel['member_ids'])
    mode = config['mode'] if mode is None else mode
    if mode not in MODES:
        raise ValueError('team_invalid_routing')
    roster = {p['id']: p for p in profiles}
    selected = set(channel['member_ids'])
    reason = 'all_members'
    matched = []
    if mode == 'auto':
        selected = set()
        if '@' in question:
            # Names can contain spaces. Match the longest declared name first,
            # then reject any remaining @ token rather than choosing a guess.
            remaining = question
            if re.search(r'@(?:all|所有人)(?![\w])', question, re.I):
                selected.update(channel['member_ids'])
                remaining = re.sub(r'@(?:all|所有人)(?![\w])', '', remaining, flags=re.I)
            names = sorted({p['name'] for p in profiles} | set(roster), key=len, reverse=True)
            for name in names:
                pattern = r'@' + re.escape(name) + r'(?![\w])'
                if not re.search(pattern, remaining):
                    continue
                targets = [p['id'] for p in profiles if name in (p['name'], p['id'])]
                if len(targets) != 1:
                    raise ValueError('team_ambiguous_mention')
                selected.update(targets)
                remaining = re.sub(pattern, '', remaining)
            if re.search(r'@[^\s@，。！？,!?;；]+', remaining):
                raise ValueError('team_unknown_mention')
            if selected:
                reason = 'explicit_mentions'
        if not selected and config['mentions_only']:
            raise ValueError('team_no_recipient')
        if not selected:
            folded = question.casefold()
            for rule in config['rules']:
                hits = [s for s in rule['keywords'] if s.casefold() in folded]
                if hits:
                    selected.update(rule['member_ids']); matched.extend(hits)
            if selected:
                reason = 'keyword_rules'
            else:
                scores = {p['id']: [s for s in keywords(p.get('expertise', [])) if s.casefold() in folded] for p in profiles}
                best = max((len(v) for v in scores.values()), default=0)
                if best:
                    selected = {key for key, hits in scores.items() if len(hits) == best}
                    matched = [s for key in selected for s in scores[key]]
                    reason = 'member_expertise'
                else:
                    selected = {config['lead_id']}; reason = 'lead_fallback'
    ids = [key for key in channel['member_ids'] if key in selected]
    if any(not roster[key].get('enabled') for key in ids):
        raise ValueError('team_profile_disabled')
    return {'selected_member_ids': ids, 'selected_member_names': [roster[key]['name'] for key in ids],
            'lead_id': config['lead_id'], 'reason': reason, 'matched_keywords': sorted(set(matched))}


def collaboration_plan(profiles, lead_id, rounds):
    if type(rounds) is not int or not 1 <= rounds <= 3 or not 1 <= len(profiles) <= 4:
        raise ValueError('team_invalid_routing')
    roster = {p['id']: p for p in profiles}
    if lead_id not in roster:
        raise ValueError('team_invalid_routing')
    plan = [{'round': r, 'profile_id': p['id'], 'name': p['name'], 'kind': 'contribution'}
            for r in range(1, rounds + 1) for p in profiles]
    plan.append({'round': rounds + 1, 'profile_id': lead_id, 'name': roster[lead_id]['name'], 'kind': 'synthesis'})
    return [dict(step, index=i, status='pending') for i, step in enumerate(plan)]
