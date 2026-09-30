#!/usr/bin/env python3
"""Approved LocalTuya update guard. Exact repairs; bounded tests; no restart loops."""
import argparse
import fcntl
import json
import os
import signal
from pathlib import Path
import subprocess
import tempfile
import time
import urllib.parse
import urllib.request
import uuid

import localtuya_guard_source as source
import localtuya_guard_live as live
import localtuya_guard_jev as jev


def atomic(path,data,mode=0o600,owner=None):
    path=Path(path); path.parent.mkdir(parents=True,exist_ok=True)
    fd,tmp=tempfile.mkstemp(prefix='.guard-',dir=path.parent)
    try:
        with os.fdopen(fd,'wb') as out:
            os.fchmod(out.fileno(),mode)
            if owner is not None: os.fchown(out.fileno(),*owner)
            out.write(data);out.flush();os.fsync(out.fileno())
        os.replace(tmp,path)
        d=os.open(path.parent,os.O_RDONLY)
        try: os.fsync(d)
        finally: os.close(d)
    finally:
        if os.path.exists(tmp): os.unlink(tmp)


def replace_owned(path,expected,new):
    path=Path(path)
    if path.is_symlink() or path.read_bytes()!=expected: raise RuntimeError('concurrent_source_change')
    st=path.stat()
    if st.st_uid!=os.getuid(): raise RuntimeError('unexpected_file_owner')
    atomic(path,new,st.st_mode & 0o777,(st.st_uid,st.st_gid))


def credentials(path):
    # Existing owner-held .env only; no shell evaluation or credential logging.
    result={}
    for line in Path(path).read_text().splitlines():
        key,sep,value=line.partition('=');key=key.strip()
        if sep and key in ('HASS_URL','HASS_TOKEN','OPENROUTER_API_KEY'):
            result[key]=value.strip().strip('"').strip("'")
    return result


class HA:
    def __init__(self,env):
        # This service runs beside the live HA container; always use its loopback API.
        self.url='http://127.0.0.1:8123'
        self.token=env['HASS_TOKEN']
        parsed=urllib.parse.urlparse(self.url)
        if parsed.hostname not in ('localhost','127.0.0.1','192.168.0.102'):
            raise RuntimeError('unexpected_HA_endpoint')
    def request(self,path,body=None):
        req=urllib.request.Request(self.url+'/api/'+path,
             data=None if body is None else json.dumps(body).encode(),
             headers={'Authorization':'Bearer '+self.token,'Content-Type':'application/json'})
        with urllib.request.build_opener(jev.NoRedirect).open(req,timeout=8) as r:
            data=r.read(2000001)
            if len(data)>2000000: raise RuntimeError('oversized_HA_response')
            return json.loads(data) if data else None
    def state(self,entity): return self.request('states/'+entity)
    def service(self,domain,service,data): return self.request('services/'+domain+'/'+service,data)
    def updating(self):
        return any(s.get('entity_id','').startswith('update.') and s.get('attributes',{}).get('in_progress')
                   for s in self.request('states'))


def command(argv,root,timeout=120,input=None):
    env=dict(os.environ)
    env['SMOKE_PI_HOST']='__local__'
    # The required broad smoke suite must not load a multi-GB local model for a light repair.
    env['SMOKE_SKIP_LOCAL_INFERENCE']='1'
    with subprocess.Popen(argv,cwd=root,stdin=subprocess.PIPE,stdout=subprocess.PIPE,
                          stderr=subprocess.PIPE,start_new_session=True,env=env) as p:
        try: out,_=p.communicate(input=input,timeout=timeout)
        except subprocess.TimeoutExpired:
            os.killpg(p.pid,signal.SIGKILL);p.communicate()
            raise RuntimeError('gate_timeout')
        # Household config can occur in command output. Never log it.
        if p.returncode: raise RuntimeError('gate_failed:'+Path(argv[0]).name)
        return out


class Guard:
    def __init__(self,root,state,api,key='',runner=command):
        self.root=Path(root);self.directory=Path(state);self.directory.mkdir(parents=True,exist_ok=True,mode=0o700)
        self.path=self.directory/'checkpoint.json';self.api=api;self.key=key;self.run=runner
        self.data=json.loads(self.path.read_text()) if self.path.exists() else {'completed_fingerprint':None,'event':None}
    def save(self): atomic(self.path,(json.dumps(self.data,indent=2,allow_nan=False)+'\n').encode())
    def started(self):
        return self.run(['docker','inspect','--format','{{.State.StartedAt}}','homeassistant'],self.root,30).decode().strip()
    def pending(self,value):
        self.data['event']['pending_test']=value;self.save()
    def notify(self,message):
        try:
            self.api.service('persistent_notification','create',{
                'notification_id':'localtuya_update_guard','title':'LocalTuya update verification','message':message})
            self.data['event']['notification_delivered']=True
        except Exception: self.data['event']['notification_delivered']=False
        self.save()
    def report(self):
        e=self.data['event']
        e['jev']=jev.classify(e,self.key)
        e['deterministic_result']=e['status']
        self.save()
        atomic(self.directory/'events'/(e['id']+'.json'), (json.dumps(e,indent=2,allow_nan=False)+'\n').encode())
        print(json.dumps({'event':e['id'],'status':e['status'],'tests':e.get('tests',{}),'jev':e['jev']}),flush=True)
        if e['status'] not in ('healthy','deferred') or e.get('repaired'):
            self.notify('Result: '+e['status']+'. '+
                ('Recognized payload fix restored; HA restarted once. ' if e.get('repaired') else '')+
                ('Functional verification deferred until the lights are already on. ' if e['status']=='deferred' else '')+
                ('Review the Pi guard checkpoint/journal. If a live test was interrupted or restoration failed, check the light brightness manually. A controller power cycle may be needed if it remains unresponsive.' if e['status'] not in ('healthy','deferred') else ''))
    def offline(self,snapshot,candidate):
        # Execute only after all method/const/payload fingerprints are recognized.
        with tempfile.TemporaryDirectory(prefix='payload-fixture-',dir=self.directory) as tmp:
            root=Path(tmp)
            for rel,data in {**snapshot,**candidate}.items():
                p=root/rel;p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(data)
            if not source.inspect(root)['recognized'] or source.inspect(root)['defects']:
                raise RuntimeError('unsafe_candidate')
            p=subprocess.run(['python3',str(self.root/'verification/test_localtuya_payloads.py')],
                 env={**os.environ,'LOCALTUYA_TEST_ROOT':tmp},capture_output=True,timeout=30)
            if p.returncode: raise RuntimeError('payload_regressions_failed')
    def rollback(self,e):
        results={}
        for rel,item in e.get('recovery',{}).items():
            try:
                current=(self.root/rel).read_bytes()
                if source.sha(current)!=item['candidate_hash']:
                    results[rel]='preserved_concurrent_change';continue
                original=self.run(['git','cat-file','blob',item['blob']],self.root,30)
                if source.sha(original)!=item['original_hash']: raise RuntimeError('recovery_hash')
                replace_owned(self.root/rel,current,original);results[rel]='restored'
            except Exception: results[rel]='recovery_failed'
        e['rollback']=results;self.save()
    def repair(self,fingerprint,e):
        original=source.snapshot(self.root);candidate=source.candidates(self.root,original)
        self.offline(original,candidate)
        e['recovery']={}
        for rel,data in candidate.items():
            blob=self.run(['git','hash-object','-w','--stdin'],self.root,30,input=original[rel]).decode().strip()
            self.run(['git','update-ref','refs/localtuya-guard/'+e['id']+'/'+str(source.FILES.index(rel)),blob],self.root,30)
            e['recovery'][rel]={'blob':blob,'original_hash':source.sha(original[rel]),'candidate_hash':source.sha(data)}
        e['stage']='write_reserved';self.save()
        if source.package_fingerprint(self.root)!=fingerprint: raise RuntimeError('package_changed_before_write')
        for rel,data in candidate.items(): replace_owned(self.root/rel,original[rel],data)
        e['stage']='patched';e['expected_fingerprint']=source.package_fingerprint(self.root);self.save()
        try:
            self.run(['bash','verification/preflight.sh'],self.root,120)
            self.run(['docker','exec','homeassistant','python','-m','homeassistant','--script','check_config','--config','/config'],self.root,180)
        except Exception:
            self.rollback(e);raise
        if source.package_fingerprint(self.root)!=e['expected_fingerprint'] or not source.inspect(self.root)['recognized'] or source.inspect(self.root)['defects']:
            raise RuntimeError('source_changed_after_validation')
        # Reserve before dispatch: interruption cannot cause a second restart.
        e['started_before']=self.started();e['restart_count']=1;e['stage']='restart_reserved';self.save()
        self.run(['docker','restart','homeassistant'],self.root,120)
        e['repaired']=True;e['stage']='waiting_ready';self.save()
        self.ready(e)
    def ready(self,e):
        for _ in range(60):
            try:
                if self.started()!=e['started_before'] and source.package_fingerprint(self.root)==e['expected_fingerprint']:
                    self.api.request('config')
                    e['stage']='live';self.save()
                    # Required post-restart smoke gate is bounded; unrelated stalls are reported.
                    try:
                        self.run(['bash','verification/smoke-tests.sh'],self.root,45)
                        e['smoke']='passed_with_local_inference_skipped'
                    except Exception:
                        e['smoke']='failed_or_timed_out'
                    self.save();return
            except Exception: pass
            time.sleep(2)
        raise RuntimeError('restart_readiness_failed')
    def functional(self,e):
        e.setdefault('tests',{})
        if e.get('repaired') and not e['tests']:
            for _ in range(30):
                if all(self.api.state(i).get('state') not in ('unavailable','unknown') for ids in live.PAIRS.values() for i in ids): break
                time.sleep(2)
        for pair in live.PAIRS:
            previous=e['tests'].get(pair,{})
            if previous.get('result') not in (None,'deferred_off','deferred_low'): continue
            e['tests'][pair]=live.test_pair(self.api,pair,self.pending);self.save()
        outcomes=[r['result'] for r in e['tests'].values()]
        e['status']='healthy' if all(s=='passed' for s in outcomes) else ('deferred' if all(s in ('passed','deferred_off','deferred_low') for s in outcomes) else 'needs_review')
        e['stage']='complete';self.data['completed_fingerprint']=source.package_fingerprint(self.root);self.save();self.report()
    def process(self,fingerprint):
        if self.data['completed_fingerprint']==fingerprint: return False
        e={'id':uuid.uuid4().hex,'observed_fingerprint':fingerprint,'stage':'source','status':'in_progress',
           'restart_count':0,'repaired':False,'time':time.time()}
        self.data['event']=e;self.save()
        try:
            findings=source.inspect(self.root);e.update(findings);self.save()
            if not findings['recognized']:
                e['status']='needs_review';e['stage']='complete';self.data['completed_fingerprint']=fingerprint;self.save();self.report();return True
            if findings['defects']: self.repair(fingerprint,e)
            else: self.offline(source.snapshot(self.root),{})
            self.functional(e)
        except Exception as exc:
            # No arbitrary exception/config/HTTP response text in logs.
            if e['stage'] in ('write_reserved','patched'): self.rollback(e)
            if e.get('pending_test'):
                e.setdefault('tests',{})[e['pending_test']['pair']]={'result':'interrupted_test','restore':'owner_review_required'}
            e['status']='needs_review';e['failure_type']=type(exc).__name__;e['stage']='complete'
            self.data['completed_fingerprint']=source.package_fingerprint(self.root)
            self.save();self.report()
        return True
    def resume(self):
        e=self.data.get('event')
        if not e or e.get('stage')=='complete': return
        try:
            if e.get('pending_test'):
                e.setdefault('tests',{})[e['pending_test']['pair']]=live.recover_pending(self.api,e['pending_test'])
                e['pending_test']=None
                raise RuntimeError('interrupted_live_test')
            if e['stage'] in ('restart_reserved','waiting_ready'):
                # Reconcile an already-issued restart only; never issue another.
                self.ready(e);e['repaired']=True;self.functional(e);return
            if e['stage']=='live': self.functional(e);return
            self.rollback(e)
        except Exception: pass
        e['stage']='complete';e['status']='needs_review';e['failure_type']='interrupted_event'
        self.data['completed_fingerprint']=source.package_fingerprint(self.root);self.save();self.report()
    def deferred(self):
        e=self.data.get('event')
        if not e or e.get('status')!='deferred': return
        # No repeated commands/model calls while off. Retry only when both are on.
        if any(r.get('result') in ('deferred_off','deferred_low') and all((live.value(self.api.state(i)) or 0)>3 for i in live.PAIRS[p]) for p,r in e.get('tests',{}).items()):
            e['stage']='live';self.save()
            try: self.functional(e)
            except Exception as exc:
                if e.get('pending_test'):
                    e.setdefault('tests',{})[e['pending_test']['pair']]={'result':'interrupted_test','restore':'owner_review_required'}
                e['stage']='complete';e['status']='needs_review';e['failure_type']=type(exc).__name__
                self.save();self.report()


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--root',default='/opt/homeassistant')
    p.add_argument('--state-dir',default=str(Path.home()/'.local/state/localtuya-update-guard'))
    p.add_argument('--env-file',default=str(Path.home()/'.hermes/.env'))
    p.add_argument('--inspect',action='store_true',help='Read source only; no credentials, tests, writes or network')
    p.add_argument('--once',action='store_true',help='Process one stable event, then exit')
    p.add_argument('--stable-seconds',type=int,default=120)
    args=p.parse_args()
    if args.inspect:
        print(json.dumps(source.inspect(args.root),indent=2));return
    env=credentials(args.env_file);g=Guard(args.root,args.state_dir,HA(env),env.get('OPENROUTER_API_KEY',''))
    with open(g.directory/'process.lock','a') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        g.resume();observed=None;since=time.monotonic()
        while True:
            try:
                fingerprint=source.package_fingerprint(g.root)
                if fingerprint!=observed: observed=fingerprint;since=time.monotonic()
                if time.monotonic()-since>=args.stable_seconds and not g.api.updating():
                    if fingerprint==source.package_fingerprint(g.root):
                        g.process(fingerprint);g.deferred()
                        e=g.data.get('event')
                        if e and e.get('notification_delivered') is False:
                            g.notify('LocalTuya guard result: '+e['status']+'. Check the guard checkpoint/journal; manual review may be required.')
                        if args.once: return
            except Exception as exc:
                print(json.dumps({'watch_error':type(exc).__name__}),flush=True)
            time.sleep(15)

if __name__=='__main__': main()
