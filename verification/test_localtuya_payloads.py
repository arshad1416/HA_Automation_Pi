"""Offline regressions against actual LocalTuya methods; no device/network access."""
import ast
import os
import asyncio
import enum
import json
import pathlib
import sys
import types
import unittest

ROOT = pathlib.Path(os.environ.get('LOCALTUYA_TEST_ROOT', str(pathlib.Path(__file__).resolve().parents[1])))
BASE = ROOT / 'custom_components/localtuya'
CANDIDATE = '--candidate' in sys.argv
sys.argv = [sys.argv[0]]

def extract(path, class_name, name):
    source = path.read_text()
    cls = next(n for n in ast.parse(source).body if isinstance(n, ast.ClassDef) and n.name == class_name)
    node = next(n for n in cls.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == name)
    return ast.get_source_segment(source, node)

class ColorMode(enum.StrEnum):
    BRIGHTNESS='brightness'; HS='hs'; COLOR_TEMP='color_temp'; WHITE='white'
class Features(enum.IntFlag):
    EFFECT=4

class Capture:
    async def set_dps(self, states):
        self.states=states

class PayloadTests(unittest.TestCase):
    def light(self, color_mode=None, on=True):
        ns={'ColorMode':ColorMode, 'LightEntityFeature':Features}
        for name in ('EFFECT','BRIGHTNESS','HS_COLOR','COLOR_TEMP_KELVIN','WHITE'):
            ns['ATTR_'+name]=name.lower()
        for name in ('COLOR','BRIGHTNESS','COLOR_MODE','SCENE','COLOR_TEMP'):
            ns['CONF_'+name]=name.lower()
        ns['SCENE_MUSIC']='music'
        ns['map_range']=lambda v,a,b,c,d: round(c+(v-a)*(d-c)/(b-a))
        config={'brightness':'2'}
        if color_mode is not None: config['color_mode']=color_mode
        stub=types.SimpleNamespace(is_on=on, _write_only=False, _dp_id='1', supported_features=Features(0), supported_color_modes={ColorMode.BRIGHTNESS}, is_color_mode=False, _hs=None, _lower_brightness=10, _upper_brightness=1000, _config=config, _modes=types.SimpleNamespace(white='white'), has_config=lambda k:k in config, _device=Capture())
        source=extract(BASE/'light.py','LocalTuyaLight','async_turn_on')
        if CANDIDATE:
            source=source.replace('if color_mode is not None:', 'if color_mode is not None and self.has_config(CONF_COLOR_MODE):')
        exec(source,ns)
        asyncio.run(ns['async_turn_on'](stub,brightness=230))
        return stub._device.states

    def protocol(self, typ='type_0a', command='CONTROL', node_id=None):
        const={}
        exec((BASE/'core/pytuya/const.py').read_text(),const)
        ns={'json':json,'time':types.SimpleNamespace(time=lambda:1700000000), **const}
        tree=ast.parse((BASE/'core/pytuya/__init__.py').read_text())
        assignment=next(n for n in tree.body if isinstance(n,ast.Assign) and any(isinstance(t,ast.Name) and t.id=='payload_dict' for t in n.targets))
        exec(compile(ast.Module(body=[assignment],type_ignores=[]),'payload_dict','exec'),ns)
        source=extract(BASE/'core/pytuya/__init__.py','TuyaProtocol','_generate_payload')
        if CANDIDATE:
            source=source.replace('json_data["uid"] = int(t) if json_data["t"] == "int" else str(int(t))', 'json_data["t"] = int(t) if json_data["t"] == "int" else str(int(t))')
        exec(source,ns)
        stub=types.SimpleNamespace(dev_type=typ,id='test-device-id',dps_to_request={'1':None},debug=lambda *a:None)
        msg=ns['_generate_payload'](stub,ns['CMDType'][command],data={'2':903},nodeId=node_id)
        return json.loads(msg.payload)

    def test_brightness_only_has_valid_datapoints(self):
        self.assertEqual(self.light(),{'2':903})
    def test_turning_on_includes_switch_datapoint(self):
        self.assertEqual(self.light(on=False),{'1':True,'2':903})
    def test_rgb_mode_datapoint_is_preserved(self):
        self.assertEqual(self.light(color_mode='21'),{'2':903,'21':'white'})
    def test_v33_control_timestamp_and_id(self):
        p=self.protocol()
        self.assertEqual(p['t'],'1700000000')
        self.assertEqual(p['uid'],'test-device-id')
        self.assertEqual(p['devId'],'test-device-id')
        self.assertEqual(p['dps'],{'2':903})
    def test_v34_integer_timestamp(self):
        p=self.protocol('v3.4')
        self.assertEqual(p['t'],1700000000)
        self.assertEqual(p['data']['dps'],{'2':903})
    def test_subdevice_timestamp_without_spurious_uid(self):
        p=self.protocol(node_id='test-subdevice')
        self.assertEqual(p['t'],'1700000000')
        self.assertNotIn('uid',p)
        self.assertEqual(p['cid'],'test-subdevice')

if __name__ == '__main__': unittest.main()
