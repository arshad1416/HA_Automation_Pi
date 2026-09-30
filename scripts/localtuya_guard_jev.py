"""System One evidence interpretation only; no repair or execution authority."""
import json
import math
import urllib.request

MODEL='typesafe/jev-1.13'
CRITERIA={
 'healthy':'Recognized fixed source and successful bidirectional functional tests.',
 'known_patch_overwritten':'Exact audited payload regression is recognized and remains unrepaired; no inference from mere state disagreement.',
 'connectivity_failure':'Healthy source but a device or HA transport is unavailable or a live command fails.',
 'needs_review':'Unrecognized source, deferred/incomplete tests, restoration uncertainty or conflicting evidence.',
}
class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self,*args,**kwargs): return None

def valid_probability(v): return type(v) in (int,float) and math.isfinite(v) and 0<=v<=1

def assess(raw):
    try:
        model=raw['model']; a=raw['answers']['assessment']; p=a['probabilities']; c=a['choice']
        if not (model==MODEL or model.startswith(MODEL+'-')): raise ValueError()
        if a['type']!='choice' or c not in CRITERIA or set(p)!=set(CRITERIA): raise ValueError()
        if not valid_probability(a['confidence']) or not all(valid_probability(v) for v in p.values()): raise ValueError()
        if abs(sum(p.values())-1)>.02 or p[c]!=max(p.values()): raise ValueError()
        return {'available':True,'model':model,'choice':c,'confidence':a['confidence'],
                'probabilities':p,'uncertain':a['confidence']<.9 or p[c]<.9,
                'usage':{k:v for k,v in raw.get('usage',{}).items() if k in ('input_tokens','output_tokens','cost') and type(v) in (int,float) and math.isfinite(v) and v>=0}}
    except (KeyError,TypeError,ValueError,AttributeError): return {'available':False,'reason':'invalid_response'}

def classify(evidence,key):
    if not key: return {'available':False,'reason':'missing_credentials'}
    # Construct a fresh allowlist: never forward journal/source files/entity IDs.
    safe={'recognized_source':bool(evidence.get('recognized')),
          'known_defects_count':len(evidence.get('defects',[])),
          'repair_applied':bool(evidence.get('repaired')),
          'test_results':[r.get('result','not_tested') for r in evidence.get('tests',{}).values()]}
    body={'model':MODEL,'state':safe,'questions':{'assessment':{'type':'choice','criteria':CRITERIA,
          'instructions':'Interpret measured evidence only. Deferred tests are incomplete. Exact source recognition establishes a known regression; repair_applied means it was corrected. Mismatching reports alone do not. You have no control or repair authority.'}}}
    try:
        req=urllib.request.Request('https://openrouter.ai/api/v1/systemone',data=json.dumps(body).encode(),
             headers={'Authorization':'Bearer '+key,'Content-Type':'application/json'})
        with urllib.request.build_opener(NoRedirect).open(req,timeout=8) as r:
            data=r.read(65537)
            if len(data)>65536: raise ValueError()
            return assess(json.loads(data))
    except Exception: return {'available':False,'reason':'transport_failed'}
