"""Mechanism-specific independent test selection, not external approval."""
from .research_tasks import enabled,revision

def required(state): return enabled(state) and state['config'].get('require_prototype_focus',False)

def assessment(api,idea,scope,goal):
    if scope=='UNASSESSED' and not required(api.engine.state): return None
    if scope not in {'FULL_MECHANISM','SUBCOMPONENT','DEFER'} or not isinstance(goal,str) or not 20<=len(goal.strip())<=4000:
        return {'status':'DEFERRED','reason':'MECHANISM_TEST_FOCUS_REQUIRED',
            'next_action':'Include local_test_scope and local_test_goal in record_critique. Select the actual carrier/format operation and its failure test. '
            'For an unverified institution without a useful documented offline operation, DEFER and explain missing evidence. Parsing/copying a manifest is not a repository or decoder test. Select SUBCOMPONENT for locally testable parts of external custody/distribution; missing public deployment does not prevent useful local coverage.'}
    return {'scope':scope,'goal':goal,'research_revision':revision(idea),'agent_id':api.agent['id'],
            'meaning':'Independent relevance judgment; DEFER retains the idea and is not an approval or rejection.'}

def eligible(state,idea):
    if not required(state): return True
    focus=idea.get('prototype_focus',{})
    if state['config'].get('coding_backend')=='sdk_shell': return True  # Advice is not a pre-execution permission gate.
    return focus.get('scope') in {'FULL_MECHANISM','SUBCOMPONENT'} and focus.get('research_revision')==revision(idea)

def plan_issue(api,idea,scope):
    if not required(api.engine.state): return None
    if api.engine.state['config'].get('coding_backend')=='sdk_shell': return None
    focus=idea.get('prototype_focus',{})
    if not eligible(api.engine.state,idea):
        return {'status':'DEFERRED','reason':'CURRENT_MECHANISM_TEST_FOCUS_REQUIRED','prototype_focus':focus,
                'next_action':'Audit must identify a useful actual mechanism test first. Keep the hypothesis; do not substitute a generic manifest copy.'}
    if focus['scope']=='SUBCOMPONENT' and scope=='FULL_MECHANISM':
        return {'status':'DEFERRED','reason':'FOCUS_SCOPE_REQUIRED','prototype_focus':focus,
                'next_action':'Test the selected subcomponent and state untested custody/discovery. A local helper cannot certify the whole external mechanism.'}
    return None
