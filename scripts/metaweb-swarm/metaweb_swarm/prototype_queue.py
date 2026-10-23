"""Finish one coding/audit cycle before admitting another; never enlarge budgets."""


def enabled(state):
    from .research_tasks import enabled as research
    return research(state) and state['config'].get('coding_backend') == 'sdk_shell'


def latest(state, idea_id):
    from .research_tasks import revision
    idea=next((i for i in state['ideas'] if i['id']==idea_id),None)
    if not idea:return None
    return next((t for t in reversed(state.get('tests',[])) if t.get('idea_id')==idea_id
                 and t.get('host_execution_verified')
                 and t.get('prototype_plan',{}).get('research_revision')==revision(idea)),None)


def review(state, test):
    return next((r for r in reversed(state.get('prototype_reviews',[])) if r.get('test_id')==test['id']),
                test.get('prototype_review',{}))


def awaiting(state, owner=None):
    result=[]
    for idea in state['ideas']:
        t=latest(state,idea['id'])
        if not t or idea.get('status')=='REJECTED' or owner and t.get('agent_id')!=owner['id']:continue
        r=review(state,t)
        if not r or r.get('review_unresolved'):result.append(t)
    return result


def receipt_excludes(state, idea):
    t=latest(state,idea['id'])
    return bool(t and review(state,t).get('verdict')!='REVISE')


def select_candidates(state, agent, choices):
    if awaiting(state,agent):return []
    # A REVISE is still the same unfinished job, even after a repaired receipt.
    repairs=[i for i in choices if (t:=latest(state,i['id'])) and review(state,t).get('verdict')=='REVISE']
    return repairs[:1] if repairs else choices


def remaining(state, agent):
    from .config import round_allowance
    return max(0,round_allowance(state['config'],agent)-agent['rounds'])


def capacity(state, worker, idea):
    t=latest(state,idea['id'])
    audit_slots=1 if t and review(state,t).get('verdict')=='REVISE' else 2
    reviewers=[a for a in state['agents'] if a.get('work_kind')=='REVIEW'
               and a['id'] not in {worker['id'],idea.get('agent_id')}
               and a['status'] in {'PENDING','COMPLETED'}]
    if not any(remaining(state,a)>=audit_slots for a in reviewers):return 'PROTOTYPE_AUDIT_ROUNDS_REQUIRED'
    # One coding quantum, audit/re-audit quanta and a final report. Requests,
    # tokens, wall time and USD remain checked by the existing budget machinery.
    if state['config']['max_steps']-state['steps'] < 1+audit_slots+1:return 'PROTOTYPE_CLOSURE_STEPS_REQUIRED'
    return None


def synchronize(engine):
    state=engine.state
    if not enabled(state):return
    from .research_tasks import local_candidates
    for a in state['agents']:
        if a.get('work_kind')!='LOCAL' or a['status'] not in {'PENDING','COMPLETED','BLOCKED'}:continue
        held=a.get('prototype_queue_hold')
        if a['status']=='BLOCKED' and not held:continue  # Preserve unrelated technical/human blockers.
        from .coding_session import command_limit
        exhausted=command_limit(state,a)
        if exhausted and (a['status']=='PENDING' or held):
            a.pop('prototype_queue_hold',None)
            a.update(status='LIMIT_REACHED',reason_for_stopping='MAX_CODING_COMMANDS; files retained, no paid dispatch')
            engine.store.commit(state,'coding_commands_exhausted',exhausted,a['id'])
            continue
        waiting=awaiting(state,a)
        choices=local_candidates(state,a)
        reason='AWAITING_INDEPENDENT_PROTOTYPE_REVIEW' if waiting else capacity(state,a,choices[0]) if choices else None
        if reason:
            if held!=reason:
                a.update(status='BLOCKED',reason_for_stopping=reason,prototype_queue_hold=reason)
                engine.store.commit(state,'prototype_queue_held',{'reason':reason,'tests':[t['id'] for t in waiting]},a['id'])
                if getattr(engine,'console_enabled',False) and not waiting:
                    print(f"  {a['id']} | Queue: {reason}; retained for resume, no new coding dispatch",flush=True)
        elif held:
            a.pop('prototype_queue_hold',None)
            from .research_recovery import active_blocks
            finished='BLOCKED' if active_blocks(state,a,'LOCAL') or a.get('research_blockers') else 'COMPLETED'
            a.update(status=('PENDING' if remaining(state,a) else 'LIMIT_REACHED') if choices else 'COMPLETED',
                     reason_for_stopping='Prototype queue reopened within existing limits' if choices else 'Independent prototype reviews recorded; no remaining local assignment')
            if not choices and finished=='BLOCKED':
                a.update(status='BLOCKED',reason_for_stopping='Current local assignments finished or retained with concrete blockers')
            engine.store.commit(state,'prototype_queue_released',{'status':a['status']},a['id'])


def schedule(state, pending, steps_left, concurrency):
    from .config import schedule_batch
    from .review_tasks import pending as review_pending
    from .research_tasks import local_candidates
    reporters=[a for a in pending if a.get('work_kind')=='SYNTHESIS']
    if reporters and steps_left<=len(reporters):return reporters[:1]
    audits=[a for a in pending if a.get('work_kind')=='REVIEW' and
            any(t['kind'].startswith('PROTOTYPE_') for t in review_pending(state,a))]
    if audits:return sorted(audits,key=lambda a:(a['rounds'],a['id']))[:1]
    # Old checkpoints may contain an unreviewed backlog: drain it, never grow it.
    if awaiting(state):return reporters[:1]
    locals=[]
    for a in pending:
        if a.get('work_kind')!='LOCAL':continue
        choices=local_candidates(state,a)
        if choices and not capacity(state,a,choices[0]):locals.append(a)
    if locals:return sorted(locals,key=lambda a:(a['rounds'],a['id']))[:1]
    # Keep two auditor quanta for execution coverage and one repair review.
    research_only=state['config'].get('run_mode')=='supervised' and not any(
        c.get('decision')=='implement' for c in state.get('implementation_choices',{}).values())
    pool=[a for a in pending if a.get('work_kind') not in {'LOCAL','SYNTHESIS'} and
          (a.get('work_kind')!='REVIEW' or research_only or remaining(state,a)>2)]
    if not research_only and (steps_left<=4 or any(a.get('prototype_queue_hold') for a in state['agents'])):
        return reporters[:1]
    return schedule_batch(pool+reporters,steps_left,concurrency) if pool else reporters[:1]


def assessment_blocked(state):
    waiting=awaiting(state)
    return bool(waiting and (any(review(state,t).get('review_unresolved') for t in waiting) or
        any(a.get('work_kind')=='REVIEW' and a['status']=='BLOCKED' for a in state['agents'])))
