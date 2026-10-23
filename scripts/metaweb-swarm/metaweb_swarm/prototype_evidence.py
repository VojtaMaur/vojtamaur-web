"""Observable artifact facts and literal case evidence, not semantic certification."""
import ast
import hashlib
import json
import re
import textwrap
from .storage import canonical


def artifact_facts(api, receipt):
    from .prototype_review import artifact_bytes
    source = receipt['prototype_plan']['input']
    facts = []
    for artifact in receipt['artifacts']:
        body = artifact_bytes(api, receipt, artifact)
        fact = dict(artifact, matches_retained_input=(artifact['sha256']==source['sha256'] and artifact['bytes']==source['bytes']))
        try:
            text = body.decode('utf-8')
        except UnicodeError:
            fact.update(binary=True, required_read_chars=0)
            facts.append(fact); continue
        fact.update(binary=False, required_read_chars=len(text) if len(body)<=65536 else min(4096,len(text)))
        # These exact flags represent failed positive probes, not arbitrary False metadata.
        failure = re.compile(r'^(?:recovery_probe|round_trip|roundtrip|positive_test|positive_passed|decode_ok|integrity_ok|tests_passed)\s*=\s*(?:False|FAIL|FAILED|0)\s*$', re.I)
        fact['failed_positive_probes'] = [line for line in text.splitlines() if failure.fullmatch(line.strip())][:8]
        try: value = json.loads(text) if len(body)<=2_000_000 else None
        except ValueError: value = None
        if isinstance(value,dict):
            for key in ('recovery_probe','round_trip','roundtrip','positive_test','positive_passed','decode_ok','integrity_ok','tests_passed'):
                if key in value and (value[key] is False or value[key] in ('FAIL','FAILED',0)):
                    fact['failed_positive_probes'].append(key+'='+str(value[key]))
            fact['reported_input_hashes'] = [{'field':key,'value':value[key],'matches_retained_input':value[key]==source['sha256']}
                for key in ('input_sha256','source_sha256','source_manifest_sha256') if isinstance(value.get(key),str)]
        facts.append(fact)
    return {'retained_input':source,'artifacts':facts,
            'meaning':'Host hash/size/read facts. Different output bytes may be a deliberate transformation; they are not an exact original copy. Literal case evidence and reviewer interpretation are still required.'}


def code_case(script, snippet, negative=False):
    """Check quoted executable syntax and the presence of a real test operation."""
    if not isinstance(snippet,str) or not 5<=len(snippet)<=8000: return False
    try:
        full=ast.parse(script)
        quote=ast.parse(textwrap.dedent(snippet).strip())
    except (ValueError,SyntaxError): return False
    nodes={ast.dump(node,include_attributes=False) for node in ast.walk(full)}
    if not quote.body or any(ast.dump(node,include_attributes=False) not in nodes for node in quote.body): return False
    checks = any(isinstance(n,(ast.Assert,ast.Raise)) or isinstance(n,ast.Call)
                 and isinstance(n.func,ast.Attribute) and (n.func.attr.startswith('assert') or n.func.attr=='raises')
                 for n in ast.walk(quote))
    if not checks: return False
    if negative:
        # Quoting a successful-prefix assertion is not an altered-input test.
        altered = any(isinstance(n,ast.BinOp) and any(isinstance(v,ast.Name) for v in ast.walk(n))
                      and any(isinstance(v,ast.Constant) and isinstance(v.value,(bytes,str)) for v in ast.walk(n))
                      or isinstance(n,(ast.Slice,ast.AugAssign))
                      or isinstance(n,ast.Subscript) and isinstance(n.ctx,ast.Store)
                      for n in ast.walk(quote))
        deliberate_invalid = any(isinstance(n,ast.Call)
            and isinstance(n.func,(ast.Name,ast.Attribute))
            and re.search(r'decode|parse|loads|fromhex|decompress|recover|validate',
                          n.func.id if isinstance(n.func,ast.Name) else n.func.attr,re.I)
            and any(isinstance(arg,ast.Constant) and isinstance(arg.value,(bytes,str)) for arg in n.args)
            for n in ast.walk(quote))
        if not altered and not deliberate_invalid: return False
    return True


def reading_requirements(api, receipt):
    from .review_tasks import _subtract
    facts=artifact_facts(api,receipt)
    reads=api.agent.get('prototype_artifact_reads',{}).get(receipt['id'],{})
    checks=api.agent.get('prototype_artifact_checks',{}).get(receipt['id'],{})
    missing=[]
    for fact in facts['artifacts']:
        if fact['binary']:
            if checks.get(fact['path'])!=fact['sha256']: missing.append({'path':fact['path'],'offset':0,'limit':16000})
        else:
            needed=fact['required_read_chars']
            if fact['path']==receipt['prototype_plan']['script']['path']:
                from .prototype_review import artifact_bytes
                needed=len(artifact_bytes(api,receipt,fact).decode('utf-8'))
            remaining=_subtract([[0,needed]],reads.get(fact['path'],[]))
            if remaining:
                lo,hi=remaining[0]
                missing.append({'path':fact['path'],'offset':lo,'limit':min(16000,hi-lo)})
    return facts,missing


def approval_gate(api, receipt, positive_code, negative_code, recovered_path):
    from .prototype_review import artifact_bytes
    facts,missing=reading_requirements(api,receipt)
    if missing:
        return {'status':'DEFERRED','reason':'OWN_TEST_OUTPUT_READ_REQUIRED','missing_paths':[m['path'] for m in missing],'missing_reads':missing,
                'next_action':'Read the actual generated reports/specimens with read_test_artifact, not just the script. Binary reads check hashes only. Compare emitted results and original byte identity before approving.'}
    failures=[{'path':f['path'],'flags':f['failed_positive_probes']} for f in facts['artifacts'] if f.get('failed_positive_probes')]
    if failures:
        return {'status':'DEFERRED','reason':'OBSERVED_PROTOTYPE_FAILURE','failures':failures,
                'next_action':'Record REVISE for the failed required probe. Other working pieces do not erase this execution result; fix the test and re-execute before certifying it.'}
    from .format_operation import validate as validate_format
    artifacts={a['path']:a for a in receipt['artifacts']}
    native=validate_format(api.idea(receipt['idea_id']),receipt['prototype_plan']['input'],
        receipt['prototype_plan']['output_paths'],lambda path:artifact_bytes(api,receipt,artifacts[path]))
    if native and not native['passed']:return native
    script=next(a for a in receipt['artifacts'] if a['path']==receipt['prototype_plan']['script']['path'])
    source=artifact_bytes(api,receipt,script).decode('utf-8')
    if api.engine.state['config'].get('coding_backend')=='sdk_shell':
        # Literal provenance is checkable. A Python AST pattern is not a semantic
        # test oracle and rejects valid subprocess/helper/non-Python tests.
        execution=next((e for e in api.engine.state.get('experiments',[]) if e.get('experiment_id')==receipt['experiment_id']),{})
        paths={receipt['prototype_plan']['script']['path'],*[a['path'] for a in execution.get('coding_sources',[])]}
        sources=[artifact_bytes(api,receipt,a).decode('utf-8',errors='replace').replace('\r\n','\n') for a in receipt['artifacts']
                 if a['path'] in paths and not a.get('binary')]
        cases=all(isinstance(quote,str) and 5<=len(quote.strip())<=8000
                  and any(quote.strip().replace('\r\n','\n') in code for code in sources) for quote in (positive_code,negative_code))
    else:
        cases=code_case(source,positive_code) and code_case(source,negative_code,True)
    if not cases:
        return {'status':'DEFERRED','reason':'ACTUAL_TEST_CASE_EVIDENCE_REQUIRED',
                'script_path':receipt['prototype_plan']['script']['path'],
                'next_action':'Select complete captured executable cases by numbered positive_refs/negative_refs. Negative code must construct altered/invalid input and assert rejection/recovery. Labels, printing, type checks or body.startswith(first_chunk) are not a damaged-input test. If absent, record REVISE.'}
    if recovered_path:
        recovered=next((f for f in facts['artifacts'] if f['path']==recovered_path),None)
        if not recovered or not recovered['matches_retained_input']:
            return {'status':'DEFERRED','reason':'RECOVERED_BYTES_DO_NOT_MATCH','recovered_path':recovered_path,
                    'retained_input':facts['retained_input'],'next_action':'Recovered bytes must match the original raw-byte SHA256 and length. Read with read_bytes; read_text/write_text may normalize newlines. A deliberate transformation is a different limited claim.'}
    return None


def review_failure(api, test_id, issue, positive_code, negative_code, recovered_path):
    fingerprint=hashlib.sha256(canonical({'reason':issue['reason'],'missing_paths':issue.get('missing_paths'),
        'positive_code':positive_code,'negative_code':negative_code,'recovered_path':recovered_path}).encode()).hexdigest()
    previous=api.agent.setdefault('prototype_review_repairs',{}).get(test_id,{})
    attempts=previous.get('attempts',0)+1 if previous.get('fingerprint')==fingerprint else 1
    record=dict(issue,test_id=test_id,fingerprint=fingerprint,attempts=attempts)
    api.agent['prototype_review_repairs'][test_id]=record
    api.event('prototype_review_revision_required',record)
    return record, attempts>=3
