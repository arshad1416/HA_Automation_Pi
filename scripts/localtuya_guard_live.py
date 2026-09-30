"""Bounded on-only local dim/cloud restore tests, with injectable HA transport."""
import time
PAIRS = {
 'island':('light.island_light_light','light.island_light_kitchen_island_light'),
 'kitchen':('light.kitchen_light_light_1','light.kitchen_light'),
}

def value(state):
    if state.get('state')!='on': return None
    b=state.get('attributes',{}).get('brightness')
    return b if type(b) is int and 1<=b<=255 else None

def agrees(states,target):
    return all(value(s) is not None and abs(value(s)-target)<=1 for s in states)

def intervention(states,original,target):
    # Original may persist briefly in cloud while a local command propagates.
    for s in states:
        b=value(s)
        if s.get('state')=='off': return True
        if b is not None and min(abs(b-original),abs(b-target))>1: return True
    return False

def test_pair(api,pair,save=lambda _:None,sleep=time.sleep,wait_seconds=25):
    ids=PAIRS[pair]
    states=[api.state(e) for e in ids]
    if any(s.get('state') in ('unavailable','unknown') for s in states):
        return {'result':'connectivity_failure','restore':'not_needed'}
    if any(s.get('state')=='off' for s in states):
        return {'result':'deferred_off','restore':'not_needed'}
    original=value(states[0])
    if original is None or not agrees(states,original):
        return {'result':'initial_disagreement','restore':'not_needed'}
    if original<=3:
        return {'result':'deferred_low','restore':'not_needed'}
    target=max(1,original-26)
    pending={'pair':pair,'original':original,'target':target,'stage':'dim_reserved'}
    # Persist intent before the first physical command, for crash recovery.
    save(pending)
    api.service('light','turn_on',{'entity_id':ids[0],'brightness':target})
    pending['stage']='dim_sent';save(pending)
    dim_ok=False
    for _ in range(wait_seconds):
        states=[api.state(e) for e in ids]
        if intervention(states,original,target):
            save(None)
            return {'result':'user_intervention','restore':'preserved_new_intent'}
        if agrees(states,target): dim_ok=True;break
        sleep(1)
    # Check current intent immediately before restoring; never turn on an off lamp.
    states=[api.state(e) for e in ids]
    if intervention(states,original,target):
        save(None)
        return {'result':'user_intervention','restore':'preserved_new_intent'}
    if value(states[0]) is None or abs(value(states[0])-target)>1:
        save(None)
        return {'result':'dim_failed','restore':'not_needed_or_ambiguous'}
    pending['stage']='restore_reserved';save(pending)
    api.service('light','turn_on',{'entity_id':ids[1],'brightness':original})
    for _ in range(wait_seconds):
        states=[api.state(e) for e in ids]
        if intervention(states,original,target):
            save(None)
            return {'result':'user_intervention','restore':'preserved_new_intent'}
        if agrees(states,original):
            save(None)
            return {'result':'passed' if dim_ok else 'dim_failed','restore':'verified',
                    'original':original,'test_brightness':target}
        sleep(1)
    save(None)
    return {'result':'restoration_failed','restore':'unverified'}

def recover_pending(api,pending):
    """An interrupted test cannot safely infer whether a user adopted its level."""
    states=[api.state(e) for e in PAIRS[pending['pair']]]
    if agrees(states,pending['original']):
        return {'result':'interrupted_test','restore':'already_original'}
    return {'result':'interrupted_test','restore':'owner_review_required'}
