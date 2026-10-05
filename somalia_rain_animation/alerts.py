"""Push alerts through Firebase Cloud Messaging topics.

Topics the app subscribes to:
  new_forecast              one message per calendar week, on the first run published that week
  heavy_rain_<pcode>        a region's area mean forecast reaches ALERT_DAILY_MM in a day
                            or ALERT_WEEKLY_MM over the week
  basin_juba, basin_shabelle  the upstream basin mean reaches ALERT_BASIN_WEEKLY_MM over the week
  test                      only on request (publish --test-alert), for checking phones
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

from . import config


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
    for m in msgs:
        m["data"] = {"run_id": meta["run_id"]}
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
    when = dt.datetime.now(dt.timezone.utc).strftime("%H:%M UTC, %d %B %Y")
    _send([{"key": "test", "topic": config.FCM_TEST_TOPIC,
            "title": "Test notification",
            "body": f"Sahan Rainfall alerts are working ({when})."
                    + (f" Latest forecast: {run['week_range']}." if run else ""),
            "data": {"run_id": latest.get("latest", "")}}])


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
