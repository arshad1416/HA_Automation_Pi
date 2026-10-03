"""Offline full-script regressions; temporary Git remotes and fake notifications."""
import os
from pathlib import Path
import shutil
import shlex
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


class SyncTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name)
        self.origin = self.base / 'origin.git'
        self.repo = self.base / 'pi'
        self.git_binary = shutil.which('git')
        self.env = {**os.environ, 'GIT_CONFIG_NOSYSTEM': '1',
                    'GIT_CONFIG_GLOBAL': os.devnull, 'GIT_TERMINAL_PROMPT': '0'}
        self.command(['git', 'init', '-q', '--bare', str(self.origin)])
        self.command(['git', 'clone', '-q', str(self.origin), str(self.repo)])
        self.git('config', 'user.name', 'Offline Test')
        self.git('config', 'user.email', 'test@example.invalid')
        self.git('checkout', '-b', 'main')
        self.config = self.repo / 'configuration.yaml'
        self.config.write_text('setting: base\n')
        self.git('add', '.')
        self.git('commit', '-qm', 'base')
        self.git('push', '-u', 'origin', 'main')
        self.bin = self.base / 'bin'
        self.bin.mkdir()
        self.executable('python3', '#!/bin/sh\ncat >> "$NOTIFY_LOG"\nprintf "\\n---\\n" >> "$NOTIFY_LOG"\nexit "${NOTIFY_EXIT:-0}"\n')
        self.executable('git', '#!/bin/sh\nif [ "$1" = pull ] && [ "${FAIL_PULL:-0}" = 1 ]; then exit 1; fi\nexec "$REAL_GIT" "$@"\n')
        self.env.update(PATH=str(self.bin)+os.pathsep+self.env['PATH'],
                        NOTIFY_LOG=str(self.base/'notifications'), REAL_GIT=self.git_binary)
        source = (ROOT/'git-sync.sh').read_text()
        for old, new in [('/opt/homeassistant', str(self.repo)),
                         ('/var/log/ha-git-sync.log', str(self.base/'sync.log')),
                         ('/var/tmp/ha-git-sync', str(self.base/'ha-git-sync'))]:
            source = source.replace(old, new)
        self.script = self.base/'sync.sh'
        self.script.write_text(source)
        self.flag = self.base/'ha-git-sync.alerted'

    def executable(self, name, text):
        p=self.bin/name; p.write_text(text); p.chmod(0o755)

    def command(self, argv, cwd=None, check=True):
        return subprocess.run(argv, cwd=cwd or self.base, env=self.env,
                              capture_output=True, text=True, check=check, timeout=30)

    def git(self, *args):
        return self.command([self.git_binary, *args], self.repo).stdout.strip()

    def sync(self, **env):
        self.env.update(env)
        return self.command(['bash', str(self.script)], check=False)

    def commit(self, value):
        self.config.write_text('setting: '+value+'\n')
        self.git('commit', '-qam', value)

    def notifications(self):
        p=self.base/'notifications'
        return p.read_text().count('---') if p.exists() else 0

    def test_clean_tree_pushes_unpublished_commit(self):
        self.commit('pending')
        self.assertEqual(self.sync().returncode, 0)
        self.assertEqual(self.git('rev-list', '--count', 'origin/main..HEAD'), '0')

    def test_failed_push_reports_failure_and_retries_without_new_edits(self):
        hook=self.origin/'hooks/pre-receive'; hook.write_text('#!/bin/sh\nexit 1\n'); hook.chmod(0o755)
        self.config.write_text('setting: pending\n')
        self.assertNotEqual(self.sync().returncode, 0)
        hook.unlink()
        self.assertEqual(self.sync().returncode, 0)
        self.assertEqual(self.git('rev-list', '--count', 'origin/main..HEAD'), '0')

    def test_conflict_preserves_local_file_and_blocks_later_sync(self):
        writer=self.base/'writer'
        self.command([self.git_binary,'clone','-q','--branch','main',str(self.origin),str(writer)])
        for k,v in [('user.name','Offline Test'),('user.email','test@example.invalid')]:
            self.command([self.git_binary,'config',k,v],writer)
        (writer/'configuration.yaml').write_text('setting: remote\n')
        self.command([self.git_binary,'commit','-qam','remote'],writer)
        self.command([self.git_binary,'push','origin','main'],writer)
        staged='setting: staged-owner-edit\n'; self.config.write_text(staged)
        self.git('add','configuration.yaml')
        local='setting: owner-local\n'; self.config.write_text(local)
        self.assertNotEqual(self.sync().returncode, 0)
        self.assertEqual(self.config.read_text(),local)
        self.assertEqual(self.git('show',':configuration.yaml'),staged.strip())
        self.assertEqual(self.git('diff','--name-only','--diff-filter=U'),'')
        self.assertNotEqual(self.sync().returncode,0)
        self.assertEqual(self.config.read_text(),local)

    def test_failed_backlog_alert_retries_until_delivery(self):
        for i in range(5): self.commit(str(i))
        self.env['FAIL_PULL']='1'
        self.sync(NOTIFY_EXIT='1')
        self.assertFalse(self.flag.exists())
        self.sync(NOTIFY_EXIT='0')
        self.assertTrue(self.flag.exists())
        before=self.notifications();self.sync()
        self.assertEqual(self.notifications(),before)

    def test_failed_recovery_keeps_flag_until_delivery(self):
        self.flag.touch()
        self.sync(NOTIFY_EXIT='1')
        self.assertTrue(self.flag.exists())
        self.sync(NOTIFY_EXIT='0')
        self.assertFalse(self.flag.exists())

    def test_nonzero_backlog_does_not_announce_recovery(self):
        self.commit('still-pending')
        self.flag.touch()
        self.sync(FAIL_PULL='1')
        self.assertTrue(self.flag.exists())
        self.assertEqual(self.notifications(),0)

    def test_conflict_notification_failure_retries_without_changing_files(self):
        marker=self.repo/'.git/ha-git-sync.conflict'; marker.touch()
        original=self.config.read_text()
        self.assertNotEqual(self.sync(NOTIFY_EXIT='1').returncode,0)
        self.assertNotEqual(self.sync(NOTIFY_EXIT='0').returncode,0)
        self.assertEqual(self.notifications(),2)
        self.sync()
        self.assertEqual(self.notifications(),2)
        self.assertEqual(self.config.read_text(),original)

    def test_notification_helper_false_is_a_failed_process(self):
        block=(ROOT/'git-sync.sh').read_text().split('notify() {',1)[1].split('\n}',1)[0]
        line=block.split('python3 -c \\\n',1)[1].split(' \\\n',1)[0]
        code=shlex.split(line)[0]
        fake='import sys,types; m=types.ModuleType("tg_notify"); m.send_telegram=lambda _:False; sys.modules["tg_notify"]=m; '
        p=subprocess.run([sys.executable,'-c',fake+code],input='synthetic test',text=True,capture_output=True,timeout=10)
        self.assertEqual(p.returncode,1)

    def test_pull_failure_alert_retries_after_threshold_delivery_failure(self):
        self.env.update(FAIL_PULL='1',NOTIFY_EXIT='1')
        for _ in range(4): self.sync()
        before=self.notifications()
        self.sync(NOTIFY_EXIT='0')
        self.assertEqual(self.notifications(),before+1)
        self.sync()
        self.assertEqual(self.notifications(),before+1)


class PreflightTests(unittest.TestCase):
    def test_missing_yaml_parser_fails_closed(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp); (root/'verification').mkdir(); (root/'scripts').mkdir(); (root/'bin').mkdir()
            shutil.copy(ROOT/'verification/preflight.sh',root/'verification/preflight.sh')
            (root/'configuration.yaml').write_text('invalid: [\n')
            stub=root/'bin/python3';stub.write_text('#!/bin/sh\nexit 1\n');stub.chmod(0o755)
            env={**os.environ,'HOME':tmp,'PATH':str(root/'bin')+':/usr/bin:/bin','PREFLIGHT_PYTHON':''}
            p=subprocess.run(['bash',str(root/'verification/preflight.sh')],env=env,capture_output=True,text=True,timeout=10)
            self.assertNotEqual(p.returncode,0)
            self.assertNotIn('preflight OK',p.stdout)


if __name__=='__main__': unittest.main()
