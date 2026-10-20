"""Research steering after known-layer deferral, without changing HTTP permissions."""
from urllib.parse import urlsplit


def enabled(api):
    from .research_tasks import enabled as research_enabled
    return research_enabled(api.engine.state) and api.agent.get('work_kind')=='DISCOVERY'


def event(api, kind, data):
    if not enabled(api): return
    if kind=='known_candidate_deferred':
        providers=api.agent.setdefault('known_discovery_directions',[])
        name=data['provider']
        if name not in providers and len(providers)<32: providers.append(name)
        api.agent['discovery_pivot']={'provider':name,'avoided_providers':list(providers),
            'next_action':'Choose a DIFFERENT provider/mechanism family now, read its external primary sources and create an honest hypothesis or specific exclusion. Re-reading quotas of a known layer or writing a note about a future pivot is not this action. A concrete improvement needs actual BASE evidence and a precise change.'}
    elif kind=='idea_recorded':
        api.agent.pop('discovery_pivot',None)
    elif kind=='http_document_read':
        try: host=urlsplit(data['url']).hostname or ''
        except ValueError: return
        from .carrier_screening import registry_matches
        if host and not registry_matches(api.engine.baseline,'',host):
            api.agent.pop('discovery_pivot',None)


def complete(state, agent, output):
    from .research_tasks import enabled as research_enabled
    pivot=agent.get('discovery_pivot')
    if research_enabled(state) and agent.get('work_kind')=='DISCOVERY' and pivot and output['status'] in {'COMPLETED','CONTINUE','REJECTED'}:
        output.update(status='CONTINUE',reason_for_stopping='KNOWN_LAYER_PIVOT_PENDING',unexplored_leads=[pivot['next_action']])
    return output
