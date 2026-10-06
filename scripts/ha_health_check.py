#!/usr/bin/env python3
"""Weekly Home Assistant health report -> health/weekly.md (read-only against HA).

Opens the recorder DB with mode=ro and reads home-assistant.log and the registries;
writes only health/weekly.md and health/last_run.json. Cron: Sundays 07:40.
"""
import collections
import json
import os
import re
import shutil
import sqlite3
import time
from datetime import datetime

B = "/opt/homeassistant/"
OUT = B + "health/"
WEEK = 7 * 86400
BAD = ("unavailable", "unknown")
now = time.time()
C = collections.Counter


def main():
    os.makedirs(OUT, exist_ok=True)
    ents = {e["entity_id"]: e for e in json.load(open(B + ".storage/core.entity_registry"))["data"]["entities"]}
    enabled = {k for k, v in ents.items() if not v.get("disabled_by")}
    c = sqlite3.connect(f"file:{B}home-assistant_v2.db?mode=ro", uri=True, timeout=60)
    meta = dict(c.execute("select metadata_id, entity_id from states_meta"))

    latest = {meta.get(m): s for m, s in c.execute(
        "select metadata_id, state from states where state_id in (select max(state_id) from states group by metadata_id)")}
    unavail = sorted(e for e, s in latest.items() if s == "unavailable" and e in enabled)

    try:
        prev = json.load(open(OUT + "last_run.json"))
    except (OSError, ValueError):
        prev = {}
    new_unavail = sorted(set(unavail) - set(prev.get("unavailable", unavail)))

    # availability flaps in the last 7 days
    flaps, last = C(), {}
    for m, s in c.execute("select metadata_id, state from states where last_updated_ts > ? order by metadata_id, last_updated_ts",
                          (now - WEEK,)):
        if m in last and (s == "unavailable") != (last[m] == "unavailable"):
            flaps[meta.get(m)] += 1
        last[m] = s

    # automations: this week vs the week before
    def runs(a, b):
        n = C()
        for (d,) in c.execute(
                "select ed.shared_data from events e join event_types et using(event_type_id) join event_data ed using(data_id) "
                "where et.event_type='automation_triggered' and e.time_fired_ts > ? and e.time_fired_ts <= ?", (a, b)):
            n[json.loads(d).get("entity_id")] += 1
        return n
    this, before = runs(now - WEEK, now), runs(now - 2 * WEEK, now - WEEK)
    stopped = sorted(((before[a], a) for a in before if this[a] == 0 and a in enabled), reverse=True)
    oldest = c.execute("select min(time_fired_ts) from events").fetchone()[0] or now

    batteries = []
    for e in sorted(enabled):
        r = ents[e]
        if e.startswith("sensor.") and (r.get("device_class") or r.get("original_device_class")) == "battery":
            try:
                v = float(latest.get(e, ""))
            except ValueError:
                continue
            # 0 on these is a charge-session value, not a dying battery
            if v < 30 and r.get("platform") != "vinfast":
                batteries.append((v, e))

    pat = re.compile(r"^\d{4}-\d\d-\d\d [\d:.]+ (WARNING|ERROR|CRITICAL) \(\S+\) \[([^\]]+)\] (.*)")
    errs, sample = C(), {}
    try:
        for line in open(B + "home-assistant.log", errors="replace"):
            m = pat.match(line)
            if m:
                k = (m.group(1), m.group(2))
                errs[k] += 1
                sample.setdefault(k, re.sub(r"\d+\.\d+\.\d+\.\d+", "<ip>", m.group(3))[:140])
    except OSError:
        pass

    try:
        temp = int(open("/sys/class/thermal/thermal_zone0/temp").read()) / 1000
    except (OSError, ValueError):
        temp = float("nan")
    du = shutil.disk_usage(B)
    db_mb = os.path.getsize(B + "home-assistant_v2.db") / 1e6

    L = [f"# Home Assistant weekly health — {datetime.now():%Y-%m-%d %H:%M}", "",
         "## System",
         f"- Pi CPU {temp:.1f}°C · disk {du.used/1e9:.0f} GB used, {du.free/1e9:.0f} GB free · recorder DB {db_mb:.0f} MB",
         f"- Recorder history reaches back {(now-oldest)/86400:.1f} days", "",
         f"## Unavailable entities: {len(unavail)} (previous run: {len(prev.get('unavailable', [])) if prev else 'n/a'})",
         f"New since last run: {len(new_unavail)}"]
    L += [f"- {e}" for e in new_unavail[:40]] + ["", "## Top availability flaps (7 days)"]
    L += [f"- {n} · {e}" for e, n in flaps.most_common(15) if n >= 10] or ["- none over 10"]
    L += ["", "## Automations that fired the week before but not this week"]
    if now - oldest < 2 * WEEK - 3600:
        L.append("- not enough history yet (needs 14 days)")
    else:
        L += [f"- {a} (was {n}/week)" for n, a in stopped[:30]] or ["- none"]
    L += ["", "## Batteries below 30%"] + ([f"- {v:.0f}% · {e}" for v, e in sorted(batteries)] or ["- none"])
    L += ["", "## Top log warnings/errors (current home-assistant.log)"]
    L += [f"- {n} · {k[0]} · {k[1]} · {sample[k]}" for k, n in errs.most_common(12)] or ["- none"]
    open(OUT + "weekly.md", "w").write("\n".join(L) + "\n")
    json.dump({"ts": now, "unavailable": unavail}, open(OUT + "last_run.json", "w"))
    print(f"wrote {OUT}weekly.md: {len(unavail)} unavailable, {len(new_unavail)} new")


if __name__ == "__main__":
    main()
