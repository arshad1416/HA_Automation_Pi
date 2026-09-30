"""Containment tests: fixtures/fakes only; no HA, subprocess restart or network."""
import json
import pathlib
import sys
import tempfile
import unittest
from unittest.mock import patch
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / 'scripts'))
import localtuya_guard_source as source

ROOT = pathlib.Path(__file__).resolve().parents[1]

class SourceTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = pathlib.Path(self.tmp.name)
        self.fixture = json.loads((ROOT/'verification/localtuya_guard_fixture.json').read_text())
        for rel in (*source.FILES, source.CONST):
            p=self.root/rel; p.parent.mkdir(parents=True, exist_ok=True)
            p.write_bytes((ROOT/rel).read_bytes())
    def tearDown(self): self.tmp.cleanup()
    def old(self, index):
        p=self.root/source.FILES[index]
        p.write_text(p.read_text().replace(source.FIXES[index][1],source.FIXES[index][0]))
    def test_fixed(self):
        self.assertTrue(source.inspect(self.root)['recognized'])
        self.assertEqual(source.inspect(self.root)['defects'], [])
    def test_both_and_single(self):
        self.old(0); self.assertEqual(source.inspect(self.root)['defects'],[0])
        self.old(1); self.assertEqual(source.inspect(self.root)['defects'],[0,1])
        snapshot=source.snapshot(self.root)
        candidate=source.candidates(self.root,snapshot)
        for rel,data in candidate.items(): (self.root/rel).write_bytes(data)
        self.assertEqual(source.inspect(self.root)['defects'],[])
    def test_unknown_method_blocks(self):
        p=self.root/source.FILES[0]
        p.write_text(p.read_text().replace('states = {}','states = {"unexpected": True}',1))
        self.assertFalse(source.inspect(self.root)['recognized'])
    def test_unknown_payload_blocks(self):
        p=self.root/source.FILES[1]
        p.write_text(p.read_text().replace('payload_dict = {','payload_dict = {"unknown": {},',1))
        self.assertFalse(source.inspect(self.root)['recognized'])
    def test_concurrent_edit_blocks(self):
        self.old(0); snapshot=source.snapshot(self.root)
        p=self.root/source.FILES[0]; p.write_text(p.read_text()+'\n# concurrent edit\n')
        with self.assertRaises(RuntimeError): source.candidates(self.root,snapshot)
    def test_unrelated_module_edit_allowed(self):
        p=self.root/source.FILES[0]; p.write_text(p.read_text()+'\n# upstream documentation\n')
        self.assertTrue(source.inspect(self.root)['recognized'])


import localtuya_guard_live as live
import localtuya_guard_jev as jev
import localtuya_update_guard as daemon

class FakeHA:
    def __init__(self,brightness=180,off=False,lag=0,fail_restore=False,intervene=False):
        self.level=brightness;self.cloud=brightness;self.off=off;self.lag=lag
        self.commands=[];self.fail_restore=fail_restore;self.intervene=intervene
    def state(self,entity):
        if self.commands and self.intervene: self.level=99;self.cloud=99
        if entity==live.PAIRS['island'][1]:
            if self.lag: self.lag-=1
            elif not self.fail_restore or len(self.commands)<2: self.cloud=self.level
        return {'state':'off' if self.off else 'on','attributes':{'brightness': self.cloud if entity==live.PAIRS['island'][1] else self.level}}
    def service(self,domain,name,data):
        if domain!='light': return
        self.commands.append(data)
        if len(self.commands)==2 and self.fail_restore: return
        self.level=data['brightness']
    def request(self,path): return {}

class LiveTests(unittest.TestCase):
    def test_dim_restore_two_routes(self):
        api=FakeHA();r=live.test_pair(api,'island',sleep=lambda _:None,wait_seconds=5)
        self.assertEqual(r['result'],'passed');self.assertEqual(api.level,180)
        self.assertEqual([c['entity_id'] for c in api.commands],list(live.PAIRS['island']))
    def test_low_level_defers_without_brightening(self):
        api=FakeHA(brightness=2)
        self.assertEqual(live.test_pair(api,'island')['result'],'deferred_low');self.assertFalse(api.commands)
    def test_off_does_not_send(self):
        api=FakeHA(off=True);self.assertEqual(live.test_pair(api,'island')['result'],'deferred_off');self.assertFalse(api.commands)
    def test_lag(self):
        api=FakeHA(lag=3);self.assertEqual(live.test_pair(api,'island',sleep=lambda _:None,wait_seconds=6)['result'],'passed')
    def test_user_intervention_no_restore(self):
        api=FakeHA(intervene=True);r=live.test_pair(api,'island',sleep=lambda _:None,wait_seconds=3)
        self.assertEqual(r['result'],'user_intervention');self.assertEqual(len(api.commands),1);self.assertEqual(api.level,99)
    def test_failed_restore(self):
        api=FakeHA(fail_restore=True);self.assertEqual(live.test_pair(api,'island',sleep=lambda _:None,wait_seconds=3)['result'],'restoration_failed')
    def test_unavailable_no_command(self):
        api=FakeHA();api.state=lambda _: {'state':'unavailable'}
        self.assertEqual(live.test_pair(api,'island')['result'],'connectivity_failure');self.assertFalse(api.commands)
    def test_disagreement_no_command(self):
        api=FakeHA(lag=20);api.cloud=100
        self.assertEqual(live.test_pair(api,'island')['result'],'initial_disagreement');self.assertFalse(api.commands)
    def test_pending_saved_before_command(self):
        api=FakeHA();saved=[]
        real=api.service
        def service(*args): self.assertTrue(saved[-1]);real(*args)
        api.service=service
        live.test_pair(api,'island',save=lambda v:saved.append(None if v is None else dict(v)),sleep=lambda _:None)
        self.assertEqual(saved[0]['stage'],'dim_reserved');self.assertIsNone(saved[-1])
    def test_interrupted_test_does_not_overwrite_user_intent(self):
        api=FakeHA(brightness=154)
        r=live.recover_pending(api,{'pair':'island','original':180,'target':154})
        self.assertEqual(r['restore'],'owner_review_required');self.assertFalse(api.commands)

class JevTests(unittest.TestCase):
    def raw(self):
        return {'model':jev.MODEL,'answers':{'assessment':{'type':'choice','choice':'healthy','confidence':.95,
          'probabilities':{'healthy':.95,'known_patch_overwritten':.02,'connectivity_failure':.01,'needs_review':.02}}}}
    def test_valid(self): self.assertTrue(jev.assess(self.raw())['available'])
    def test_uncertain(self):
        r=self.raw();r['answers']['assessment']['confidence']=.4
        self.assertTrue(jev.assess(r)['uncertain'])
    def test_invalid(self):
        for bad in ({}, {'model':'other'},None): self.assertFalse(jev.assess(bad)['available'])
        r=self.raw();r['answers']['assessment']['probabilities']['healthy']=float('nan')
        self.assertFalse(jev.assess(r)['available'])
    def test_missing_key_no_network(self): self.assertEqual(jev.classify({},'')['reason'],'missing_credentials')
    def test_transport_failed(self):
        with patch('urllib.request.build_opener',side_effect=OSError):
            self.assertEqual(jev.classify({'recognized':True},'dummy')['reason'],'transport_failed')

class DaemonTests(SourceTests):
    def setUp(self):
        super().setUp()
        p=self.root/'verification';p.mkdir()
        shutil=__import__('shutil');shutil.copy(ROOT/'verification/test_localtuya_payloads.py',p)
        self.started='before';self.calls=[];self.blobs={};self.fail_gate=None
        def runner(argv,root,timeout=120,input=None):
            self.calls.append(argv)
            if self.fail_gate and self.fail_gate in argv: raise RuntimeError('fake_gate_failure')
            if argv[:2]==['git','hash-object']:
                key=source.sha(input);self.blobs[key]=input;return key.encode()
            if argv[:2]==['git','cat-file']: return self.blobs[argv[-1]]
            if argv[:2]==['docker','inspect']: return self.started.encode()
            if argv[:2]==['docker','restart']: self.started='after'
            return b''
        self.guard=daemon.Guard(self.root,self.root/'runtime',FakeHA(),runner=runner)
        self.interpret=patch.object(jev,'classify',return_value={'available':False,'reason':'test'});self.interpret.start()
        self.testlive=patch.object(live,'test_pair',return_value={'result':'passed','restore':'verified'});self.testlive.start()
    def tearDown(self): self.interpret.stop();self.testlive.stop();super().tearDown()
    def test_no_repeated_fingerprint_commands_or_model(self):
        fp=source.package_fingerprint(self.root);self.guard.process(fp);count=len(self.calls)
        self.assertFalse(self.guard.process(fp));self.assertEqual(count,len(self.calls))
        self.assertEqual(self.guard.data['event']['restart_count'],0)
    def test_repair_and_single_restart(self):
        self.old(0);self.old(1);self.guard.process(source.package_fingerprint(self.root))
        self.assertEqual(self.guard.data['event']['status'],'healthy')
        self.assertEqual(self.guard.data['event']['restart_count'],1)
        self.assertFalse(source.inspect(self.root)['defects'])
        self.assertEqual(sum(c[:2]==['docker','restart'] for c in self.calls),1)
        self.assertFalse(self.guard.process(source.package_fingerprint(self.root)))
    def test_config_failure_rolls_back_no_restart(self):
        self.old(0);self.fail_gate='check_config';self.guard.process(source.package_fingerprint(self.root))
        self.assertEqual(source.inspect(self.root)['defects'],[0])
        self.assertFalse(any(c[:2]==['docker','restart'] for c in self.calls))
        self.assertEqual(self.guard.data['event']['status'],'needs_review')
    def test_unknown_does_not_test_or_restart(self):
        p=self.root/source.FILES[0];p.write_text(p.read_text().replace('states = {}','states = {"unknown": True}',1))
        with patch.object(live,'test_pair') as call:
            self.guard.process(source.package_fingerprint(self.root));call.assert_not_called()
        self.assertFalse(self.calls)
    def test_reinstall_same_version_is_new_event(self):
        self.guard.process(source.package_fingerprint(self.root));first=self.guard.data['event']['id']
        self.old(0);self.guard.process(source.package_fingerprint(self.root))
        self.assertNotEqual(first,self.guard.data['event']['id']);self.assertEqual(self.guard.data['event']['restart_count'],1)
    def test_restart_failure_is_reserved_no_retry(self):
        self.old(0);self.fail_gate='restart';self.guard.process(source.package_fingerprint(self.root))
        self.assertEqual(self.guard.data['event']['restart_count'],1)
        self.guard.resume();self.guard.process(source.package_fingerprint(self.root))
        self.assertEqual(sum(c[:2]==['docker','restart'] for c in self.calls),1)
    def test_recover_after_restart_no_second_restart(self):
        self.guard.data['event']={'id':'test','stage':'restart_reserved','started_before':'before','restart_count':1,
            'expected_fingerprint':source.package_fingerprint(self.root),'recognized':True,'defects':[0]}
        self.started='after';self.guard.resume()
        self.assertEqual(self.guard.data['event']['status'],'healthy')
        self.assertFalse(any(c[:2]==['docker','restart'] for c in self.calls))
    def test_partial_write_syntax_blocks(self):
        p=self.root/source.FILES[0];p.write_text('class incomplete(')
        self.guard.process(source.package_fingerprint(self.root))
        self.assertEqual(self.guard.data['event']['status'],'needs_review');self.assertFalse(self.calls)
    def test_rollback_preserves_concurrent_edit(self):
        self.old(0);original=source.snapshot(self.root);candidate=source.candidates(self.root,original)
        rel=source.FILES[0];self.blobs['blob']=original[rel]
        (self.root/rel).write_bytes(candidate[rel]+b'\n# owner change\n')
        e={'recovery':{rel:{'blob':'blob','original_hash':source.sha(original[rel]),'candidate_hash':source.sha(candidate[rel])}}}
        self.guard.rollback(e);self.assertIn(b'# owner change',(self.root/rel).read_bytes())
        self.assertEqual(e['rollback'][rel],'preserved_concurrent_change')

class AdditionalTests(unittest.TestCase):
    def test_deferred_transport_failure_does_not_repeat_controls(self):
        with tempfile.TemporaryDirectory() as d:
            g=daemon.Guard(ROOT,d,FakeHA())
            g.data['event']={'id':'deferred','stage':'complete','status':'deferred',
                            'tests':{'island':{'result':'deferred_off'}}}
            with patch.object(g,'functional',side_effect=OSError) as f,patch.object(g,'report'):
                g.deferred();g.deferred()
                self.assertEqual(f.call_count,1)
                self.assertEqual(g.data['event']['status'],'needs_review')
    def test_gate_transport_disables_unrelated_local_model_inference(self):
        import os
        raw=daemon.command(['python3','-c',
            'import os; print(os.environ["SMOKE_SKIP_LOCAL_INFERENCE"], os.environ["SMOKE_PI_HOST"])'],ROOT)
        self.assertEqual(raw.strip(),b'1 __local__')
    def test_atomic_replacement_checks_owner_and_expected_bytes(self):
        with tempfile.TemporaryDirectory() as d:
            p=pathlib.Path(d)/'file';p.write_bytes(b'old');p.chmod(0o640)
            daemon.replace_owned(p,b'old',b'new')
            self.assertEqual(p.read_bytes(),b'new');self.assertEqual(p.stat().st_mode & 0o777,0o640)
            with self.assertRaises(RuntimeError): daemon.replace_owned(p,b'old',b'bad')
    def test_symlink_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            p=pathlib.Path(d)/'file';p.write_bytes(b'old');link=pathlib.Path(d)/'link';link.symlink_to(p)
            with self.assertRaises(RuntimeError): daemon.replace_owned(link,b'old',b'new')
            self.assertEqual(p.read_bytes(),b'old')
    def test_fingerprint_changes_on_non_method_update(self):
        with tempfile.TemporaryDirectory() as d:
            p=pathlib.Path(d)/'custom_components/localtuya/new.py';p.parent.mkdir(parents=True);p.write_text('a=1')
            first=source.package_fingerprint(d);p.write_text('a=2')
            self.assertNotEqual(first,source.package_fingerprint(d))
    def test_restart_reserved_before_dispatch_recovers_without_retry(self):
        with tempfile.TemporaryDirectory() as d:
            g=daemon.Guard(ROOT,d,FakeHA(),runner=lambda *args,**kw: self.fail('No restart should be dispatched'))
            g.data['event']={'id':'interrupted','stage':'restart_reserved','restart_count':1,'started_before':'before'}
            with patch.object(g,'ready',side_effect=RuntimeError),patch.object(g,'report'):
                g.resume()
            self.assertEqual(g.data['event']['status'],'needs_review')
            self.assertEqual(g.data['event']['restart_count'],1)

if __name__=='__main__': unittest.main()
