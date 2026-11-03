"""Clearly labelled offline fixtures that exercise orchestration, not research."""


class DemoBackend:
    async def step(self, agent, prompt, history, tools_api, config):
        if config.get('task_style')=='brainstorming':
            return self.brainstorming_step(agent,history,tools_api)
        role = agent["role"]
        tools_api.note("DEMO fixture: no API call, no search, no preservation claim.")
        if "Meta-Archivist" in role:
            tools_api.spawn_agent({"role": "Demo Optical Decoder Specialist", "mission": "Create a labelled local fixture to demonstrate patch export.",
                "reason": "Offline smoke test of emergent roles", "unique_expertise": "Demonstrate a distinct copy and artifact", "question": "Does the system keep the origin unchanged?", "expected_output": "A fixture patch, no archival result"})
        if "Loophole" in role:
            idea = tools_api.submit_idea(self.idea("[DEMO] Account-gated example", "DEMO mechanism A", "FREE", "BLOCKED", "ACCOUNT_REQUIRED"))
            tools_api.request_approval({"idea_id": idea["id"], "kind": "ACCOUNT", "description": "Demo registration intent; do not create a real account", "target": "https://example.com/demo", "payload": {"fixture": True}})
        if "Format Mutant" in role:
            idea = tools_api.submit_idea(self.idea("[DEMO] One-time archival fee", "DEMO mechanism B", "ONE_TIME", "BLOCKED", "PAYMENT_REQUIRED"))
            tools_api.request_approval({"idea_id": idea["id"], "kind": "ONE_TIME_PAYMENT", "description": "Demo one-time payment intent; no payment executor exists", "target": "https://example.com/demo-fee", "payload": {"amount": 25, "currency": "EUR", "fixture": True}})
        if "Failure-Domain" in role:
            tools_api.submit_idea(self.idea("[DEMO] Subscription provider", "DEMO mechanism B", "RECURRING", "DISCOVERED"))
        if "Future Archaeologist" in role:
            tools_api.submit_idea(self.idea("[DEMO] PiqlFilm / Arctic World Archive", "PiqlFilm", "ONE_TIME", "DISCOVERED"))
        if "Demo Optical" in role:
            path = "source/vojtamaur-web/scripts/swarm-demo-example.txt"
            tools_api.write_file(path, "DEMO ONLY: local artifact generated in an isolated copy.\n")
            data = self.idea("[DEMO] Local prototype fixture", "DEMO mechanism C", "FREE", "PROTOTYPED")
            data["artifacts"] = [path]
            tools_api.submit_idea(data)
        return {"output": {"status": "COMPLETED", "reason_for_stopping": "Offline demo fixture finished; no research was performed.",
                           "summary": f"DEMO fixture for {role}", "unexplored_leads": [], "blind_spots": ["Live API/search and Docker execution have not been exercised."]},
                "history": history, "usage": {"requests": 0, "input_tokens": 0, "output_tokens": 0, "total_tokens": 0, "web_search_calls": 0},
                "raw": {"demo": True}}

    def brainstorming_step(self,agent,history,api):
        """Exercise the research handoff without the legacy execution fixture."""
        api.note('DEMO brainstorming fixture: no search, execution or preservation claim.')
        if agent['role']=='Loophole Archivist':
            api.submit_idea(self.idea('[DEMO] Research proposal retained for human evaluation',
                                     'demo brainstorming mechanism','FREE','INVESTIGATING'))
        if agent.get('work_kind')=='REVIEW':
            task=api.get_review_task()
            if task.get('kind')=='RESEARCH_IDEA':
                api.record_critique(task['target_id'],'REVISE',
                    'Offline fixture has no observed primary evidence; retain the research hypothesis.',
                    decision_basis='EVIDENCE_GAP')
        if agent.get('work_kind')=='SYNTHESIS':
            api.get_research_task()
            api.record_research_report([i['id'] for i in api.engine.state['ideas']],
                'DEMO only: one research hypothesis and its evidence gaps were retained for human evaluation. No code, packages or deposit was executed.',
                ['Offline fixture, not a live model or web research result.'])
        return {'output':{'status':'COMPLETED','reason_for_stopping':'Offline research assignment recorded.',
                          'summary':'DEMO brainstorming fixture; realization deferred.',
                          'unexplored_leads':[],'blind_spots':[],
                          'handoff_leads':['Human evaluation of the retained research proposal.']},
                'history':history,'usage':{},'raw':{'demo':True}}

    @staticmethod
    def idea(title, mechanism, payment, status, blocker=""):
        return {"title": title, "mechanism": mechanism, "provider": "example.com (fixture)",
                "summary": "DEMO fixture used to test policy and reporting; not a discovered mechanism.", "status": status,
                "payment": payment, "novelty": "DEMO ONLY", "evidence": [], "failure_domains": ["demo"],
                "scores": {"novelty": 0}, "blocker": blocker, "next_action": "Inspect the fixture; do not execute it externally.",
                "rejection_reason": "", "artifacts": []}
