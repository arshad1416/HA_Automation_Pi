"""Recognize only audited LocalTuya payload code; never import vendor modules."""
import ast
import hashlib
import json
from pathlib import Path

FILES = ('custom_components/localtuya/light.py', 'custom_components/localtuya/core/pytuya/__init__.py')
CONST = 'custom_components/localtuya/core/pytuya/const.py'
METHODS = (('LocalTuyaLight','async_turn_on'), ('TuyaProtocol','_generate_payload'))
FIXES = (
 ('if color_mode is not None:', 'if color_mode is not None and self.has_config(CONF_COLOR_MODE):'),
 ('json_data["uid"] = int(t) if json_data["t"] == "int" else str(int(t))',
  'json_data["t"] = int(t) if json_data["t"] == "int" else str(int(t))'),
)
FIXTURE = Path(__file__).resolve().parents[1]/'verification/localtuya_guard_fixture.json'

def sha(data): return hashlib.sha256(data).hexdigest()

def canonical(node):
    # Python 3.12+ adds empty type_params and 3.14 removes Constant.kind.
    # Normalize these syntax-neutral fields so Mac/Pi use identical fingerprints.
    def normalize(value):
        if isinstance(value,ast.AST):
            return [type(value).__name__,[[k,normalize(v)] for k,v in ast.iter_fields(value)
                    if not (k=='type_params' and not v) and not (k=='kind' and v is None)]]
        if isinstance(value,list): return [normalize(v) for v in value]
        return value
    return sha(json.dumps(normalize(node),separators=(',',':'),ensure_ascii=True).encode())

def method(text,index):
    cls=next(n for n in ast.parse(text).body if isinstance(n,ast.ClassDef) and n.name==METHODS[index][0])
    return next(n for n in cls.body if isinstance(n,(ast.FunctionDef,ast.AsyncFunctionDef)) and n.name==METHODS[index][1])

def payload(text):
    return next(n for n in ast.parse(text).body if isinstance(n,ast.Assign) and any(isinstance(t,ast.Name) and t.id=='payload_dict' for t in n.targets))

def snapshot(root): return {rel:(Path(root)/rel).read_bytes() for rel in (*FILES,CONST)}

def inspect(root):
    fixture=json.loads(FIXTURE.read_text())
    try:
        data=snapshot(root); statuses=[]
        for i,rel in enumerate(FILES):
            digest=canonical(method(data[rel].decode(),i))
            statuses.append(next((s for s in ('fixed','old') if fixture['methods'][i][s]==digest),'unknown'))
        safe=(sha(data[CONST])==fixture['const_sha256'] and canonical(payload(data[FILES[1]].decode()))==fixture['payload_ast'])
        return {'recognized':safe and 'unknown' not in statuses,'methods':statuses,
                'defects':[i for i,s in enumerate(statuses) if s=='old'],
                'hashes':{p:sha(b) for p,b in data.items()}}
    except (OSError,UnicodeError,SyntaxError,StopIteration,ValueError):
        return {'recognized':False,'methods':['unknown'],'defects':[],'hashes':{}}

def candidates(root,original):
    if snapshot(root)!=original: raise RuntimeError('concurrent_source_change')
    result=inspect(root)
    if not result['recognized']: raise RuntimeError('unrecognized_source')
    candidate={}
    for i in result['defects']:
        rel=FILES[i]; text=original[rel].decode(); node=method(text,i)
        segment=ast.get_source_segment(text,node)
        if segment.count(FIXES[i][0])!=1: raise RuntimeError('ambiguous_patch')
        # Replace exclusively within the verified method's source segment.
        replacement=segment.replace(*FIXES[i])
        if text.count(segment)!=1: raise RuntimeError('ambiguous_method')
        patched=text.replace(segment,replacement,1)
        if canonical(method(patched,i))!=json.loads(FIXTURE.read_text())['methods'][i]['fixed']:
            raise RuntimeError('candidate_mismatch')
        candidate[rel]=patched.encode()
    return candidate

def package_fingerprint(root):
    """Include every vendor source file: detect same-version reinstalls/partial copies."""
    base=Path(root)/'custom_components/localtuya'; h=hashlib.sha256()
    paths=sorted(p for p in base.rglob('*') if p.is_file() and '__pycache__' not in p.parts and p.suffix in ('.py','.json'))
    if not paths: raise RuntimeError('missing_package')
    for p in paths: h.update(str(p.relative_to(base)).encode()+b'\0'+p.read_bytes()+b'\0')
    return h.hexdigest()
