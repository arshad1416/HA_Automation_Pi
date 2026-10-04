"""Pure forecast validation and transport contract; no HA or device bindings."""
from datetime import datetime, timezone
from math import isfinite
from email.utils import parsedate_to_datetime
from copy import deepcopy
import asyncio

URL = 'https://api.met.no/weatherapi/locationforecast/2.0/complete'

def epoch(value):
    if not isinstance(value, str): raise ValueError('missing_timestamp')
    d = datetime.fromisoformat(value.replace('Z', '+00:00'))
    if d.tzinfo is None: raise ValueError('naive_timestamp')
    return d.timestamp()

def number(value):
    if type(value) not in (int, float) or not isfinite(value) or value < 0:
        raise ValueError('invalid_precipitation')
    return float(value)

def evaluate(body, now, validated_at, hours=24, threshold=2, max_age=5400):
    """Conservative total of whole 1h bins overlapping [now,now+horizon)."""
    age = now - validated_at
    if not isfinite(age) or not 0 <= age <= max_age: raise ValueError('stale_response')
    props = body['properties']; meta = props['meta']
    issued = epoch(meta['updated_at'])
    if issued > now + 300: raise ValueError('future_issue_time')
    unit = meta['units']['precipitation_amount']
    factor = {'mm': 1, 'in': 25.4, 'inches': 25.4}.get(unit)
    if factor is None: raise ValueError('unsupported_unit')
    end = now + hours*3600; bins=[]; starts=set()
    for row in props['timeseries']:
        start=epoch(row['time'])
        if start in starts: raise ValueError('duplicate_interval')
        starts.add(start)
        stop=start+3600
        if start >= end or stop <= now: continue
        # Never substitute overlapping next_6_hours/next_12_hours amounts.
        mm=number(row['data']['next_1_hours']['details']['precipitation_amount'])*factor
        bins.append((start, stop, mm))
    bins.sort(); cursor=now
    for start, stop, mm in bins:
        if start > cursor: raise ValueError('coverage_gap')
        if cursor > now and start < cursor: raise ValueError('overlap_interval')
        cursor=stop
    if cursor < end or not bins: raise ValueError('incomplete_horizon')
    total=sum(x[2] for x in bins)
    return {'decision':'allow' if total < threshold else 'block',
            'reason':'below_threshold' if total < threshold else 'rain_forecast',
            'precipitation_upper_bound_mm':round(total,6), 'period_count':len(bins),
            'requested_start':now,'requested_end':end,
            'coverage_start':bins[0][0],'coverage_end':bins[-1][1],
            'validated_at':validated_at,'source_issued_at':issued,
            'source_age_seconds':now-issued,'response_age_seconds':age}

class Cache:
    """No disk persistence: restart must obtain a new validated response."""
    def __init__(self):
        self.body=None;self.validated_at=None;self.last_modified=None;self.next_request_at=0

    async def fetch(self, session, latitude, longitude, user_agent, clock,
                    hours=24, threshold=2, max_age=5400):
        now=clock()
        if now < self.next_request_at:
            if self.body is None: raise ValueError('no_valid_cache')
            return evaluate(self.body,now,self.validated_at,hours,threshold,max_age)
        # Limit errors and retries too; timestamps only advance on validated success.
        self.next_request_at=now+3600
        headers={'User-Agent':user_agent}
        if self.body is not None and self.last_modified:
            headers['If-Modified-Since']=self.last_modified
        async def request():
            async with session.get(URL,params={'lat':f'{latitude:.4f}','lon':f'{longitude:.4f}'},
                                   headers=headers,allow_redirects=False) as response:
                status=response.status
                if status == 200: body=await response.json()
                elif status == 304 and self.body is not None and 'If-Modified-Since' in headers:
                    body=self.body
                else: raise ValueError('http_'+str(status))
                finished=clock()
                result=evaluate(body,finished,finished,hours,threshold,max_age)
                expires=response.headers.get('Expires')
                if expires:
                    try:self.next_request_at=max(self.next_request_at,parsedate_to_datetime(expires).timestamp())
                    except (TypeError,ValueError,OverflowError):pass
                self.body=deepcopy(body);self.validated_at=finished
                self.last_modified=response.headers.get('Last-Modified',self.last_modified)
                return result
        return await asyncio.wait_for(request(),timeout=20)
