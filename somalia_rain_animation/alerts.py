"""Push alerts through Firebase Cloud Messaging topics.

Topics the app subscribes to:
  new_forecast              one message per calendar week, on the first run published that week
  heavy_rain_<pcode>        a region's area mean forecast reaches ALERT_DAILY_MM in a day
                            or ALERT_WEEKLY_MM over the week
  basin_juba, basin_shabelle  the upstream basin mean reaches ALERT_BASIN_WEEKLY_MM over the week
  test                      only on request (publish --test-alert), for checking phones
Every alert is sent twice: in English to the topics above, and in Somali to the same topics with an
"so_" prefix (app 1.2 and later subscribes to the topics of its language).
Already sent alerts are remembered in site/sent_alerts.json, so daily runs do not repeat them.
Without the service account (local runs) the messages are only printed.
"""
from __future__ import annotations

import datetime as dt
import json
import os
import re
from pathlib import Path

import requests

from . import config, labels

RIVERS_SO = {"Juba": "Jubba", "Shabelle": "Shabeelle"}


def topic_for(region: dict) -> str:
    key = region.get("pcode") or region["name"]
    return "heavy_rain_" + re.sub(r"[^a-z0-9]+", "_", key.lower()).strip("_")


def plan_messages(meta: dict, summary: dict) -> list[dict]:
    msgs = []
    first = dt.date.fromisoformat(meta["first_day"])
    iso = first.isocalendar()
    msgs.append({"key": f"new:{iso[0]}-W{iso[1]:02d}", "topic": "new_forecast",
                 "title": "New weekly rainfall forecast",
                 "body": f"Somalia rainfall forecast for {meta['week_range']} is now available."})
    for r in summary["regions"]:
        hits = [(meta["days"][i], v) for i, v in enumerate(r["daily_mean"]) if v >= config.ALERT_DAILY_MM]
        for day, v in hits:
            msgs.append({"key": f"heavy:{r['name']}:{day['date']}", "topic": topic_for(r),
                         "title": f"{config.category(v)} rain forecast: {r['name']}",
                         "body": f"{config.category(v)} rain, around {v:.0f} mm on average, "
                                 f"forecast for {day['title']}."})
        if not hits and r["week_mean"] >= config.ALERT_WEEKLY_MM:
            msgs.append({"key": f"heavy_week:{r['name']}:{meta['first_day']}", "topic": topic_for(r),
                         "title": f"{config.category(r['week_mean'], config.WEEKLY_CATEGORIES)} rain this week: {r['name']}",
                         "body": f"Around {r['week_mean']:.0f} mm on average over {meta['week_range']}."})
    # Upstream basins: river flood early warning for the Juba and Shabelle
    for b in summary.get("basins", []):
        if b["part"] == "upstream_of_somalia" and b["week_mean"] >= config.ALERT_BASIN_WEEKLY_MM:
            msgs.append({"key": f"basin:{b['name']}:{meta['first_day']}",
                         "topic": f"basin_{b['name'].lower()}",
                         "title": f"{config.category(b['week_mean'], config.WEEKLY_CATEGORIES)} rain upstream "
                                  f"in the {b['name']} basin",
                         "body": f"Around {b['week_mean']:.0f} mm forecast over the upstream {b['name']} basin "
                                 f"for {meta['week_range']}. River levels in Somalia may rise in the following days."})
    msgs += _somali(meta, summary)
    for m in msgs:
        m["data"] = {"run_id": meta["run_id"]}
    return msgs


def _somali(meta: dict, summary: dict) -> list[dict]:
    """The same alerts in Somali, for the so_ topics. Keys and conditions match plan_messages."""
    first = dt.date.fromisoformat(meta["first_day"])
    last = dt.date.fromisoformat(meta["last_day"])
    week = labels.week_range_so(first, last)
    iso = first.isocalendar()
    W = config.WEEKLY_CATEGORIES
    msgs = [{"key": f"so:new:{iso[0]}-W{iso[1]:02d}", "topic": "so_new_forecast",
             "title": "Saadaal cusub oo roobka toddobaadka",
             "body": f"Saadaasha roobka Soomaaliya ee {week} waa diyaar."}]
    for r in summary["regions"]:
        hits = [(meta["days"][i], v) for i, v in enumerate(r["daily_mean"]) if v >= config.ALERT_DAILY_MM]
        for day, v in hits:
            cat = config.category(v, so=True)
            when = labels.fmt_date_so(dt.date.fromisoformat(day["date"]))
            msgs.append({"key": f"so:heavy:{r['name']}:{day['date']}", "topic": "so_" + topic_for(r),
                         "title": f"{cat} ayaa la filayaa: {r['name']}",
                         "body": f"{cat}, celcelis ahaan {v:.0f} mm, {when}."})
        if not hits and r["week_mean"] >= config.ALERT_WEEKLY_MM:
            cat = config.category(r["week_mean"], W, so=True)
            msgs.append({"key": f"so:heavy_week:{r['name']}:{meta['first_day']}", "topic": "so_" + topic_for(r),
                         "title": f"{cat} toddobaadkan: {r['name']}",
                         "body": f"Celcelis ahaan {r['week_mean']:.0f} mm, {week}."})
    for b in summary.get("basins", []):
        if b["part"] == "upstream_of_somalia" and b["week_mean"] >= config.ALERT_BASIN_WEEKLY_MM:
            cat = config.category(b["week_mean"], W, so=True)
            name = RIVERS_SO.get(b["name"], b["name"])
            msgs.append({"key": f"so:basin:{b['name']}:{meta['first_day']}",
                         "topic": f"so_basin_{b['name'].lower()}",
                         "title": f"{cat}: dooxada {name} (Itoobiya)",
                         "body": f"{b['week_mean']:.0f} mm ayaa la filayaa dooxada {name} ee Itoobiya, {week}. "
                                 "Webiyada Soomaaliya ayaa kici kara maalmaha xiga."})
    return msgs


def _access_token(info: dict) -> str:
    from google.auth.transport.requests import Request
    from google.oauth2 import service_account
    creds = service_account.Credentials.from_service_account_info(
        info, scopes=["https://www.googleapis.com/auth/firebase.messaging"])
    creds.refresh(Request())
    return creds.token


def _send(messages: list[dict]) -> set[str]:
    """Send through FCM; returns the keys that were accepted. Dry run without the service account."""
    raw = os.environ.get(config.FCM_ENV)
    if not raw:
        for m in messages:
            print(f"  alert (dry run, no {config.FCM_ENV}): [{m['topic']}] {m['title']}: {m['body']}")
        return set()
    info = json.loads(raw)
    url = f"https://fcm.googleapis.com/v1/projects/{info['project_id']}/messages:send"
    headers = {"Authorization": f"Bearer {_access_token(info)}"}
    ok = set()
    for m in messages:
        body = {"message": {"topic": m["topic"],
                            "notification": {"title": m["title"], "body": m["body"]},
                            "data": m["data"],
                            "android": {"priority": "high",
                                        "notification": {"channel_id": config.FCM_CHANNEL}}}}
        r = requests.post(url, json=body, headers=headers, timeout=30)
        if r.ok:
            ok.add(m["key"])
            print(f"  alert sent: [{m['topic']}] {m['title']}")
        else:
            print(f"  alert FAILED ({r.status_code}): [{m['topic']}] {r.text[:200]}")
    return ok


def send_test(site: Path):
    """A test notification to the `test` topic (phones with 'Test alerts' switched on)."""
    man_path = site / "manifest.json"
    latest = json.loads(man_path.read_text(encoding="utf-8")) if man_path.exists() else {}
    run = next((r for r in latest.get("runs", []) if r["id"] == latest.get("latest")), None)
    now = dt.datetime.now(dt.timezone.utc)
    when = now.strftime("%H:%M UTC, %d %B %Y")
    when_so = f"{now:%H:%M} UTC, {now.day} {labels.MONTHS_SO[now.month - 1]} {now.year}"
    week_so = (labels.week_range_so(dt.date.fromisoformat(run["first_day"]), dt.date.fromisoformat(run["last_day"]))
               if run else "")
    data = {"run_id": latest.get("latest", "")}
    _send([{"key": "test", "topic": config.FCM_TEST_TOPIC,
            "title": "Test notification",
            "body": f"Sahan Rainfall alerts are working ({when})."
                    + (f" Latest forecast: {run['week_range']}." if run else ""),
            "data": data},
           {"key": "so:test", "topic": "so_" + config.FCM_TEST_TOPIC,
            "title": "Ogeysiis tijaabo ah",
            "body": f"Digniinaha Sahan way shaqeynayaan ({when_so})."
                    + (f" Saadaashii u dambeysay: {week_so}." if run else ""),
            "data": data}])


def send_alerts(meta: dict, summary: dict, site: Path):
    state_path = site / "sent_alerts.json"
    sent = set(json.loads(state_path.read_text(encoding="utf-8"))) if state_path.exists() else set()
    todo = [m for m in plan_messages(meta, summary) if m["key"] not in sent]
    if not todo:
        print("  alerts: nothing new to send")
        return
    accepted = _send(todo)
    if accepted:
        state_path.write_text(json.dumps(sorted(sent | accepted), indent=0), encoding="utf-8")
