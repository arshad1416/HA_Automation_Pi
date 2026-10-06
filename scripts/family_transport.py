#!/usr/bin/env python3
"""Family transport reminders: calendar for when/where, Life360 for what is
actually happening. Read-only against HA except for the phone push.

  family_transport.py plan     8 AM summary of today's drop-offs and pickups
  family_transport.py check    run every 5 min; pushes LEAD_MIN before each trip
  family_transport.py test     self-check of the assignment rule
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
        print("ok")
    elif mode == "plan":
        today = trips(now)
        if today:  # no activities, no push
            push("Today's drop-offs and pickups", "\n".join(line(t) for t in today), dry)
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
