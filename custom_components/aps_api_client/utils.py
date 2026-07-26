import hmac
import pytz
from datetime import datetime, date, time


def add_hmac_signature(params):
    hasher = hmac.new("aps2020".encode(), digestmod="SHA1")
    output = {}
    for k, v in sorted(params.items()):
        hasher.update(f"{k}{v}".encode())
        output[k] = v

    hash = hasher.hexdigest()
    output["checkcode"] = hash.upper()
    return output


def get_todays_midnight():
    today = date.today()
    return datetime.combine(today, datetime.min.time())
