#!/usr/bin/env python3
"""Family transport reminders: calendar for when/where, Life360 for what is
actually happening. Read-only against HA except for the phone push.

  family_transport.py plan     8 AM summary of today's drop-offs and pickups
  family_transport.py check    run every 5 min; pushes LEAD_MIN before each trip
  family_transport.py battery-evening   school nights: will the kids' phone last tomorrow?
  family_transport.py battery-morning   school mornings: will it last until pickup?
  family_transport.py test     self-check of the assignment and drain rules
  add --dry-run to print instead of pushing, --now 2026-10-06T17:00 to pretend

The school bus is not handled here: the published bus-time reminder stays the
baseline and automations/12_bus_pickup.yaml adds the live Life360 alerts.
"""
import json
import sys
import urllib.parse
import urllib.request
from datetime import datetime, timedelta
from pathlib import Path

HA = "http://localhost:8123"
NOTIFY = "mobile_app_cph2655"  # Arshad's OnePlus 13
KID_CALENDARS = {
    "Izaan": "calendar.summer_camp_shared",   # "Izaan's activities (shared)"
    "Mina": "calendar.mina_s_activities",
}
# Timed events here make that parent unavailable. All-day entries (bills,
# "L OFF", birthdays) are ignored. "Shared" is the family calendar, so it
# blocks both parents.
BUSY_CALENDARS = {
    "Arshad": ["calendar.carfi_arshad", "calendar.shared"],
    "Larissa": ["calendar.work_shared", "calendar.shared"],
}
TRACKERS = {
    "Arshad": "device_tracker.life360_arshad_kazi",
    "Larissa": "device_tracker.life360_larissa_kazi",
    "Kids": "device_tracker.life360_izaan_kazi",  # Izaan's phone; Mina has none
}
LEAD_MIN = 45        # push this long before each drop-off / pickup
CHECK_EVERY_MIN = 5  # must match the cron interval; one push per trip
BUFFER_MIN = 30      # a parent needs this much clear either side of a trip
STALE_MIN = 10       # older Life360 fixes are flagged, never hidden

# Kids' phone battery prediction (Izaan & Mina's Pixel 7 Pro, via Life360).
SCHOOL_HOURS = (8, 17)   # weekday hours the phone must survive; 17 = off the bus
MIN_AT_PICKUP = 20       # warn when the predicted level at 5 pm is below this
MIN_HISTORY_H = 12       # hours of not-charging history before trusting a rate
HISTORY_DAYS = 7


def _token():
    for line in (Path.home() / ".hermes/.env").read_text().splitlines():
        if line.startswith("HASS_TOKEN="):
            return line.split("=", 1)[1].strip().strip("'\"")
    sys.exit("HASS_TOKEN not found in ~/.hermes/.env")


def ha(path, payload=None):
    req = urllib.request.Request(
        HA + path,
        data=json.dumps(payload).encode() if payload is not None else None,
        headers={"Authorization": "Bearer " + _token(), "Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.load(r)


def timed_events(calendar, day):
    """Today's events that have a clock time, as (start, end, summary, location)."""
    start = day.replace(hour=0, minute=0, second=0, microsecond=0)
    q = urllib.parse.urlencode({"start": start.isoformat(), "end": (start + timedelta(days=1)).isoformat()})
    out = []
    for e in ha(f"/api/calendars/{calendar}?{q}"):
        if "dateTime" not in e["start"]:
            continue  # all-day
        out.append((datetime.fromisoformat(e["start"]["dateTime"]),
                    datetime.fromisoformat(e["end"]["dateTime"]),
                    e.get("summary") or "(untitled)", e.get("location") or ""))
    return out


def free(busy, when):
    lo, hi = when - timedelta(minutes=BUFFER_MIN), when + timedelta(minutes=BUFFER_MIN)
    return not any(s < hi and e > lo for s, e, *_ in busy)


def assign(arshad_free, larissa_free):
    if arshad_free and larissa_free:
        return "either of you (both free)"
    if larissa_free:
        return "Larissa (Arshad has a calendar conflict)"
    if arshad_free:
        return "Arshad (Larissa is busy)"
    return "NOBODY FREE - both calendars conflict, sort this out"


def trips(now):
    """Every drop-off and pickup today, oldest first."""
    busy = {p: [ev for c in cals for ev in timed_events(c, now)] for p, cals in BUSY_CALENDARS.items()}
    out = []
    for kid, cal in KID_CALENDARS.items():
        for start, end, summary, location in timed_events(cal, now):
            for kind, when in (("Drop-off", start), ("Pickup", end)):
                # The activity itself must not make a parent look busy for its own trips.
                who = assign(free(busy["Arshad"], when), free(busy["Larissa"], when))
                out.append((when, kind, kid, summary, location, who))
    return sorted(out)


def where(name, now):
    s = ha("/api/states/" + TRACKERS[name])
    a = s.get("attributes", {})
    if s.get("state") in (None, "unknown", "unavailable"):
        return f"{name}: location unknown"
    spot = "home" if s["state"] == "home" else (a.get("place") or "away, no named place")
    if a.get("driving"):
        spot += ", driving"
    seen = a.get("last_seen")
    age = (now - datetime.fromisoformat(seen)).total_seconds() / 60 if seen else None
    if age is None or age > STALE_MIN:
        spot += " (UNCERTAIN: last fix %s)" % (f"{age:.0f} min ago" if age is not None else "time unknown")
    return f"{name}: {spot}"


def line(t):
    when, kind, kid, summary, location, who = t
    place = f" at {location.split(',')[0].rstrip('.')}" if location else ""
    return f"{when:%-I:%M %p} {kind}: {kid}, {summary}{place}. Handling: {who}."


def battery_history(now):
    """[(time, level, charging)] for the kids' phone from HA's recorder."""
    start = now - timedelta(days=HISTORY_DAYS)
    q = urllib.parse.urlencode({"filter_entity_id": TRACKERS["Kids"], "end_time": now.isoformat()})
    rows = ha(f"/api/history/period/{urllib.parse.quote(start.isoformat())}?{q}")
    out = []
    for r in rows[0] if rows else []:
        level = r.get("attributes", {}).get("battery_level")
        if level is not None:
            out.append((datetime.fromisoformat(r["last_updated"]).astimezone(),
                        float(level), bool(r["attributes"].get("battery_charging"))))
    return out


def in_school(t):
    return t.weekday() < 5 and SCHOOL_HOURS[0] <= t.hour < SCHOOL_HOURS[1]


def drain_rates(samples):
    """Average %/hour lost while not charging: (school hours, other hours, hours of data).

    ponytail: plain averages over a week, split only into school vs other
    hours. Falls back to the combined rate when a bucket has under 3 h of
    data. Upgrade to a recency-weighted fit if predictions keep missing.
    """
    drop, hours = {True: 0.0, False: 0.0}, {True: 0.0, False: 0.0}
    for (t0, l0, c0), (t1, l1, c1) in zip(samples, samples[1:]):
        h = (t1 - t0).total_seconds() / 3600
        if c0 or c1 or l1 > l0 or h > 3:  # charging, topped up, or a tracking gap
            continue
        drop[in_school(t0)] += l0 - l1
        hours[in_school(t0)] += h
    total_h = hours[True] + hours[False]
    overall = (drop[True] + drop[False]) / total_h if total_h else 0.0
    rate = lambda b: drop[b] / hours[b] if hours[b] >= 3 else overall
    return rate(True), rate(False), total_h


def predict_at_pickup(level, now, school_rate, other_rate):
    """Level at the end of the next school day if the phone is never charged."""
    end = now.replace(hour=SCHOOL_HOURS[1], minute=0)
    if now >= end:
        end += timedelta(days=1)
    t = now
    while t < end:  # step to each hour boundary so the school/other split is exact
        step = min((t + timedelta(hours=1)).replace(minute=0) - t, end - t)
        level -= (school_rate if in_school(t) else other_rate) * step.total_seconds() / 3600
        t += step
    return max(level, 0.0)


def battery_check(now, evening, dry):
    s = ha("/api/states/" + TRACKERS["Kids"])
    a = s.get("attributes", {})
    level = a.get("battery_level")
    if level is None or a.get("battery_charging"):
        return  # nothing to say while it is on the charger or unknown
    if evening and level < 50:
        return  # the fixed 8 pm HA reminder already covers this
    school_rate, other_rate, hours = drain_rates(battery_history(now))
    if hours < MIN_HISTORY_H:
        if not evening and level < 30:
            push("Kids' phone is low", f"It is at {level:.0f}% and not charging. Not enough "
                 "history yet to predict whether it lasts until pickup.", dry)
        elif dry:
            print(f"(quiet: only {hours:.1f} h of history, level {level:.0f}%)")
        return
    at_pickup = predict_at_pickup(level, now, school_rate, other_rate)
    detail = (f"It is at {level:.0f}% and usually loses {school_rate:.1f}%/h at school and "
              f"{other_rate:.1f}%/h otherwise, so it would be around {at_pickup:.0f}% by 5 pm"
              f"{' tomorrow' if evening else ''}.")
    if at_pickup < MIN_AT_PICKUP:
        push("Charge the kids' phone tonight" if evening else "Kids' phone won't last the day",
             detail + (" Plug it in overnight." if evening else " Top it up before they leave."), dry)
    elif dry:
        print("(quiet) " + detail)


def push(title, message, dry):
    if dry:
        print(f"[{title}]\n{message}\n")
    else:
        ha(f"/api/services/notify/{NOTIFY}", {"title": title, "message": message})


def main(argv):
    mode = argv[1] if len(argv) > 1 else ""
    dry = "--dry-run" in argv
    now = datetime.now().astimezone()
    if "--now" in argv:
        now = datetime.fromisoformat(argv[argv.index("--now") + 1]).astimezone()
    now = now.replace(second=0, microsecond=0)

    if mode == "test":
        b = [(now, now + timedelta(hours=1), "x", "")]
        assert not free(b, now + timedelta(minutes=80))   # inside the buffer
        assert free(b, now + timedelta(minutes=91))
        assert assign(True, False).startswith("Arshad")
        assert assign(False, True).startswith("Larissa")
        assert assign(False, False).startswith("NOBODY")
        mon = datetime(2026, 10, 5, 8, 0).astimezone()  # a Monday
        hist = [(mon + timedelta(hours=h), 100 - 4 * h, False) for h in range(10)]      # 4%/h at school
        hist += [(mon + timedelta(hours=9 + h), 64 - h, False) for h in range(1, 13)]   # 1%/h evening
        hist += [(mon + timedelta(hours=22), 100, True)]                                # charging: ignored
        sr, orate, hrs = drain_rates(hist)
        assert abs(sr - 4) < 0.01 and abs(orate - 1) < 0.01 and abs(hrs - 21) < 0.01, (sr, orate, hrs)
        # 8 pm Monday at 60%: 12 h overnight at 1 + 9 h school at 4 = 48 lost
        assert abs(predict_at_pickup(60, mon.replace(hour=20), 4, 1) - 12) < 0.01
        # 7:30 am Tuesday at 60%: 0.5 h at 1 + 9 h at 4
        tue = (mon + timedelta(days=1)).replace(hour=7, minute=30)
        assert abs(predict_at_pickup(60, tue, 4, 1) - 23.5) < 0.01
        print("ok")
    elif mode == "plan":
        today = trips(now)
        if today:  # no activities, no push
            push("Today's drop-offs and pickups", "\n".join(line(t) for t in today), dry)
    elif mode in ("battery-evening", "battery-morning"):
        battery_check(now, mode == "battery-evening", dry)
    elif mode == "check":
        for t in trips(now):
            mins = (t[0] - now).total_seconds() / 60
            if LEAD_MIN <= mins < LEAD_MIN + CHECK_EVERY_MIN:
                locs = "\n".join(where(n, now) for n in TRACKERS)
                push(f"{t[1]} in {mins:.0f} min: {t[2]}", f"{line(t)}\n{locs}", dry)
    else:
        sys.exit(__doc__)


if __name__ == "__main__":
    main(sys.argv)
