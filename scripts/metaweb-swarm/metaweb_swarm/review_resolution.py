"""Reopen contradictory legacy assessments, retaining their complete audit history."""
from .prototype_queue import enabled,latest,review,remaining


def recover(engine):
    state=engine.state
    if not enabled(state):return []
    reopened=[]
    for idea in state['ideas']:
        test=latest(state,idea['id'])
        if not test:continue
        record=review(state,test)
        if not record.get('review_unresolved') or record.get('reopened_protocol')=='host-evidence-0.7.9':continue
        # This is a protocol repair, not a new scientific verdict or a budget grant.
        record['reopened_protocol']='host-evidence-0.7.9'
        owner=next(a for a in state['agents'] if a['id']==test['agent_id'])
        for block in owner.get('research_task_blocks',[]):
            if block.get('test_id')==test['id'] and block.get('reason')=='INDEPENDENT_REVIEW_UNRESOLVED':
                block.update(resolved=True,resolution='Legacy contradictory assessment reopened; no implementation defect inferred')
        auditor=next((a for a in state['agents'] if a['id']==record.get('agent_id')),None)
        if auditor:
            auditor.get('prototype_review_repairs',{}).pop(test['id'],None)
            if auditor['status'] in {'PENDING','COMPLETED'} and remaining(state,auditor):
                auditor.update(status='PENDING',reason_for_stopping='Contradictory legacy review reopened within existing budget')
        reopened.append(test['id'])
    if reopened:
        engine.store.commit(state,'prototype_unresolved_reviews_reopened',{'tests':reopened,
            'meaning':'Historical assessments and artifacts retained; no verdict, code repair, limit extension or external action inferred'})
    return reopened
