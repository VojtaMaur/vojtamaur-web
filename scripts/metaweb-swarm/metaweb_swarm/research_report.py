"""Finishing a report does not require finishing its unresolved research."""
from .storage import now


def record(api, idea_ids, conclusion, limitations):
    from .research_tasks import enabled
    from .deposit_handoff import report_revision
    state = api.engine.state
    if not enabled(state) or api.agent.get('work_kind')!='SYNTHESIS':
        return {'status':'DEFERRED','reason':'RESEARCH_REPORTER_REQUIRED'}
    revision = report_revision(state)
    if api.agent.get('research_report_revision')!=revision:
        return {'status':'DEFERRED','reason':'CURRENT_REPORT_PACKET_REQUIRED','next_action':'Read get_research_task first, then finish this report.'}
    expected = [i['id'] for i in state['ideas']]
    if not isinstance(idea_ids,list) or any(not isinstance(x,str) for x in idea_ids) or len(idea_ids)!=len(set(idea_ids)) or set(idea_ids)!=set(expected):
        return {'status':'DEFERRED','reason':'ALL_CURRENT_IDEAS_REQUIRED','expected_ids':expected,
                'next_action':'Cover every current IDEA, including unresolved/rejected candidates; an empty run uses [].'}
    if not isinstance(conclusion,str) or not 30<=len(conclusion.strip())<=8000:
        raise ValueError('Report conclusion needs 30..8000 characters')
    if not isinstance(limitations,list) or len(limitations)>16 or any(not isinstance(x,str) or not 5<=len(x)<=2000 for x in limitations):
        raise ValueError('Provide up to 16 concrete report limitations')
    receipt = {'agent_id':api.agent['id'],'revision':revision,'idea_ids':expected,
               'conclusion':conclusion,'limitations':limitations,'time':now(),
               'facts':{'recorded_tests':len(state.get('tests',[])),
                        'pending_test_reviews':sum(t.get('prototype_review_required',False) and not t.get('prototype_review') for t in state.get('tests',[])),
                        'full_mechanism_reviews':sum(r['verdict']=='FULL_MECHANISM' for r in state.get('prototype_reviews',[])),
                        'subcomponent_reviews':sum(r['verdict']=='SUBCOMPONENT' for r in state.get('prototype_reviews',[])),
                        'revise_reviews':sum(r['verdict']=='REVISE' for r in state.get('prototype_reviews',[])),
                        'experiment_count':len(state.get('experiments',[])),
                        'candidate_statuses':{i['id']:i['status'] for i in state['ideas']}},
               'meaning':'Reporter completion receipt. Model conclusion is judgment; candidate statuses, approvals and run limits are unchanged.'}
    api.agent['research_report_receipt'] = receipt
    api.event('research_report_recorded',receipt)
    return dict(receipt,status='COMPLETED',next_action='Finish YOUR reporter assignment now. Unresolved research belongs in handoff_leads; it does not require more reporter rounds.')
