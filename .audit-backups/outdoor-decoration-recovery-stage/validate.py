import asyncio,copy,json,tempfile
from datetime import timedelta
from pathlib import Path
import yaml
from homeassistant.core import HomeAssistant,Context
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import script, config_validation as cv
from homeassistant.helpers.template import Template
from homeassistant.util import dt

async def main():
    config=yaml.safe_load(Path('/config/.audit-backups/outdoor-decoration-recovery-stage/candidate.yaml').read_text())[0]
    hass=HomeAssistant(tempfile.mkdtemp(prefix='outdoor-offline-validation-'))
    calls=[];logs=[];confirm=True
    async def send(call):
        calls.append(call.service)
        if confirm == 'error':raise HomeAssistantError('simulated dispatch failure')
        if confirm == 'race':hass.states.async_set('switch.outdoor_decoration_smartplug_socket_1','unavailable')
        elif confirm:hass.states.async_set('switch.outdoor_decoration_smartplug_socket_1','off' if call.service=='turn_off' else 'on')
    async def log(call):logs.append(call.data['message'])
    hass.services.async_register('switch','turn_on',send)
    hass.services.async_register('switch','turn_off',send)
    hass.services.async_register('system_log','write',log)
    sequence=await script.async_validate_actions_config(hass,cv.SCRIPT_SCHEMA(copy.deepcopy(config['actions'])))
    results=[]
    guard=Template(config['conditions'][0]['value_template'],hass)
    for trigger,expected in [(None,False),({'platform':'event','id':'scheduled_on'},False),({'platform':'time','id':'wrong'},False),({'platform':'time','id':'scheduled_on'},True)]:
        variables={} if trigger is None else {'trigger':trigger}
        assert guard.async_render(variables)==expected
        results.append({'case':'trigger_guard_'+str(trigger),'pass':True})
    async def run_case(name,initial,trigger_id,age,confirm_result,expect_calls,expect_warning,reconnect=False):
        nonlocal confirm
        calls.clear();logs.clear();confirm=confirm_result
        hass.states.async_set('switch.outdoor_decoration_smartplug_socket_1',initial)
        seq=await script.async_validate_actions_config(hass,cv.SCRIPT_SCHEMA(copy.deepcopy(config['actions'])))
        # Only shorten the post-command confirmation timeout in this offline test.
        seq[2]['choose'][0]['sequence'][1]['timeout']=timedelta(seconds=.04)
        runner=script.Script(hass,seq,name,'automation',script_mode='single')
        trigger={'platform':'time','id':trigger_id,'now':dt.utcnow()-timedelta(seconds=age)}
        if reconnect:
            async def reconnect_later():
                await asyncio.sleep(.02)
                hass.states.async_set('switch.outdoor_decoration_smartplug_socket_1','off')
            asyncio.create_task(reconnect_later())
        await asyncio.wait_for(runner.async_run({'trigger':trigger},Context()),2)
        assert calls==expect_calls,(name,calls)
        assert bool(logs)==expect_warning,(name,logs)
        results.append({'case':name,'pass':True,'command_attempts':len(calls),'warnings':len(logs)})
    await run_case('ready_on','off','scheduled_on',0,True,['turn_on'],False)
    await run_case('ready_off','on','scheduled_off',0,True,['turn_off'],False)
    await run_case('already_on','on','scheduled_on',0,True,['turn_on'],False)
    await run_case('unavailable_deadline','unavailable','scheduled_on',299.96,True,[],True)
    await run_case('unknown_deadline','unknown','scheduled_off',299.96,True,[],True)
    await run_case('invalid_state_deadline','invalid','scheduled_on',299.96,True,[],True)
    await run_case('late_ready','off','scheduled_on',301,True,[],True)
    await run_case('reconnect_before_deadline','unavailable','scheduled_on',299.7,True,['turn_on'],False,True)
    await run_case('no_reported_confirmation','off','scheduled_on',0,False,['turn_on'],True)
    await run_case('unavailable_at_dispatch','off','scheduled_on',0,'race',['turn_on'],True)
    await run_case('service_error_once','off','scheduled_on',0,'error',['turn_on'],True)
    print(json.dumps({'isolated_HA_script_tests':results,'passed':len(results),'physical_devices_used':False}))
    await hass.async_stop()
asyncio.run(main())
