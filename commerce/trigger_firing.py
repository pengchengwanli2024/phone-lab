"""Tell a model that a scheduled trigger turn is the scheduled work itself.

Studied from CopilotKit/openbot shared/routine-firing.ts. Its comment records a
live failure: a routine instruction written in schedule-speak ("every run ...")
was read by the model as a request to check whether a schedule was set up; it
found the routine, answered "already configured", did nothing, and the run was
recorded as successful.

Independent implementation with one structural difference: the frame is never
written into the stored question. The discussion keeps exactly what the person
wrote; the frame is attached to the per-turn prompt binding only, so nothing has
to be stripped back out for the transcript, titles or hashes.

This is presentation. It grants no tool, approval or business execution.
"""

KINDS = ('once', 'interval', 'weekly', 'webhook', 'after_discussion', 'manual')
LABELS = {'once': '一次性定时', 'interval': '固定间隔', 'weekly': '每周定时', 'webhook': '外部事件',
          'after_discussion': '前一次讨论结束后', 'manual': '手动触发'}


def frame(kind):
    """The fixed sentences for one trigger kind, or None when nothing should be added."""
    if kind not in KINDS:
        raise ValueError('firing_invalid_kind')
    if kind == 'manual':
        # A person pressed run: this is an ordinary request, not unattended work.
        return None
    return ('本轮由“' + LABELS[kind] + '”触发器自动发起，就是该触发器这一次的执行。'
            '请在本轮直接处理下面的问题并说明实际结果；不要去查看、创建或修改触发器设置，除非问题本身要求。'
            '若资料不足或做不到，请明确说明未完成及原因，不要把“已配置”当作完成。')


def binding(trigger_id, kind, event_id):
    """Per-turn prompt context for a trigger-started discussion."""
    if not isinstance(trigger_id, str) or not trigger_id or not isinstance(event_id, str) or not event_id:
        raise ValueError('firing_invalid_reference')
    text = frame(kind)
    if text is None:
        return None
    return {'trigger_id': trigger_id, 'kind': kind, 'event_id': event_id, 'instruction': text}
