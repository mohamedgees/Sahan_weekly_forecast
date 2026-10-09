"""Push alerts through Firebase Cloud Messaging topics.

Topics the app subscribes to:
  new_forecast              one message per calendar week, on the first run published that week
  heavy_rain_<pcode>        a region (pcode "SO24") or a district ("SO2401", the app's My place) whose
                            area mean forecast reaches ALERT_DAILY_MM in a day or ALERT_WEEKLY_MM in the week
  basin_juba, basin_shabelle  the upstream basin mean reaches ALERT_BASIN_WEEKLY_MM over the week
  test                      only on request (publish --test-alert), for checking phones
Every alert is sent twice: in English to the topics above, and in Somali to the same topics with an
"so_" prefix (app 1.2 and later subscribes to the topics of its language).

One message per area per forecast week, listing all its heavy days. It is sent again ("Update:") only
when the forecast gets worse: a higher level or heavy days not yet announced. What has been sent is
remembered in site/sent_alerts.json. Each message also carries a data payload (all strings) so the app
can show it in either language and open the place on the map.
Without the service account (local runs) the messages are only printed.
"""
from __future__ import annotations

import datetime as dt
import json
import math
import os
import re
from pathlib import Path

import requests

from . import config, labels

RIVERS_SO = {"Juba": "Jubba", "Shabelle": "Shabeelle"}
# Towns on each river where a rise shows first (named in river alerts)
RIVER_TOWNS = {"Juba": "Doolow, Luuq and Baardheere", "Shabelle": "Belet Weyne, Bulo Burto and Jowhar"}
RIVER_TOWNS_SO = {"Juba": "Doolow, Luuq iyo Baardheere", "Shabelle": "Beledweyne, Buulobarde iyo Jowhar"}
DAYS_SHORT = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
DAYS_SHORT_SO = ["Isn", "Tal", "Arb", "Kha", "Jim", "Sab", "Axd"]

ADVICE = {"rain": "Avoid crossing flooded roads and dry riverbeds (togga).",
          "river": "Follow river news; move people and livestock away from the banks if levels rise."}
ADVICE_SO = {"rain": "Ha ka gudbin waddooyinka biyuhu qariyeen iyo togagga.",
             "river": "La soco wararka webiga; dadka iyo xoolaha ka fogeeya hareeraha webiga haddii uu kaco."}


def topic_for(area: dict) -> str:
    key = area.get("pcode") or area["name"]
    return "heavy_rain_" + re.sub(r"[^a-z0-9]+", "_", key.lower()).strip("_")


# ---------- places ----------
def load_places(site: Path) -> list:
    """The settlements list written by export.export_settlements (empty when there is none)."""
    path = site / "static" / "settlements.json"
    return json.loads(path.read_text(encoding="utf-8"))["places"] if path.exists() else []


def nearest_place(places: list, lon: float, lat: float):
    """(name, km, district) of the nearest place, a bigger place within 1 km of the nearest winning,
    as in the app."""
    if not places:
        return None
    kx, ky = 111.32 * math.cos(math.radians(lat)), 110.57
    dist = [math.hypot((p[0] - lon) * kx, (p[1] - lat) * ky) for p in places]
    near = min(dist)
    best = min((i for i, d in enumerate(dist) if d <= near + 1), key=lambda i: (places[i][3], dist[i]))
    p = places[best]
    return p[2], dist[best], p[4] if len(p) > 4 else ""


# ---------- wording helpers ----------
def _days_text(dates: list[dt.date], so: bool = False) -> str:
    """'Tue 13 and Wed 14 Oct', 'Tue 13 to Thu 15 Oct', 'Sat 10, Mon 12 and Wed 14 Oct'."""
    names = DAYS_SHORT_SO if so else DAYS_SHORT
    month = (lambda d: labels.MONTHS_SO[d.month - 1]) if so else (lambda d: f"{d:%b}")
    one = lambda d, m: f"{names[d.weekday()]} {d.day}" + (f" {month(d)}" if m else "")
    same_month = len({d.month for d in dates}) == 1
    parts = [one(d, not same_month or i == len(dates) - 1) for i, d in enumerate(dates)]
    joiner, to = (" iyo ", " ilaa ") if so else (" and ", " to ")
    if len(dates) > 2 and all((b - a).days == 1 for a, b in zip(dates, dates[1:])):
        return parts[0] + to + parts[-1]
    return parts[0] if len(parts) == 1 else ", ".join(parts[:-1]) + joiner + parts[-1]


def _area_event(area: dict, meta: dict):
    """Heavy days and level for a region or district, or None when it stays under the thresholds.
    Level: 3 Heavy, 4 Very heavy (daily scheme) or the weekly scheme's index (5 Extreme)."""
    days = [(dt.date.fromisoformat(meta["days"][i]["date"]), v)
            for i, v in enumerate(area["daily_mean"]) if v >= config.ALERT_DAILY_MM]
    weekly = area["week_mean"] >= config.ALERT_WEEKLY_MM
    if not days and not weekly:
        return None
    level = 0
    if days:
        level = [n for n, _a, _b in config.DAILY_CATEGORIES].index(config.category(max(v for _d, v in days)))
    if weekly:
        level = max(level, [n for n, _a, _b in config.WEEKLY_CATEGORIES].index(
            config.category(area["week_mean"], config.WEEKLY_CATEGORIES)))
    return {"days": [d for d, _v in days], "level": level, "day_idx": [i for i, v in enumerate(area["daily_mean"])
                                                                      if v >= config.ALERT_DAILY_MM]}


def _level_name(level: int, so: bool) -> str:
    names = config.WEEKLY_CATEGORIES_SO if so else [n for n, _a, _b in config.WEEKLY_CATEGORIES]
    return names[min(level, len(names) - 1)]


def _rain_message(kind: str, area: dict, ev: dict, meta: dict, summary: dict, places: list, so: bool) -> dict:
    """Region or district alert, in English or Somali."""
    level = _level_name(ev["level"], so)
    rain = level if so else f"{level} rain"
    where = area["name"] if kind == "region" else f"{area['name']}, {area['region']}"
    if ev["days"]:
        title = f"{rain} · {where} · {_days_text(ev['days'], so)}"
    else:
        title = f"{rain} toddobaadkan · {where}" if so else f"{rain} this week · {where}"

    at = area.get("week_max_at")
    # Name a place inside the area itself: by a border the nearest village may be across it
    if kind == "region":
        inside = {d["name"] for d in summary.get("districts", []) if d["region"] == area["name"]}
    else:
        inside = {area["name"]}
    own = [p for p in places if len(p) > 4 and p[4] in inside]
    near = nearest_place(own or places, *at) if at else None
    near_name = None
    if near:
        near_name = near[0] if kind == "district" or not near[2] else f"{near[0]} ({near[2]})"
    lines = []
    mx, mean = f"{area['week_max']:.0f}", f"{area['week_mean']:.0f}"
    # As in the app: "near" within 10 km, else the distance ("26 km from")
    close = near is not None and near[1] <= 10
    km = f"{near[1]:.0f}" if near else ""
    if so:
        where_so = f" agagaarka {near_name}" if close else (f", {km} km ka fog {near_name}" if near_name else "")
        lines.append(f"Ilaa {mx} mm{where_so}; celcelis ahaan {mean} mm toddobaadkan.")
    else:
        where_en = f" near {near_name}" if close else (f", {km} km from {near_name}" if near_name else "")
        lines.append(f"Up to {mx} mm{where_en}; about {mean} mm on average this week.")
    if not ev["days"]:   # spread over the week: name its wettest day
        i = max(range(len(area["daily_mean"])), key=lambda k: area["daily_mean"][k])
        wet = _days_text([dt.date.fromisoformat(meta["days"][i]["date"])], so)
        v = f"{area['daily_mean'][i]:.0f}"
        lines.append(f"Maalinta ugu roobka badan: {wet}, qiyaastii {v} mm." if so
                     else f"Wettest day: {wet}, about {v} mm on average.")
    if kind == "region":
        hit = [d for d in summary.get("districts", []) if d["region"] == area["name"] and _area_event(d, meta)]
        hit.sort(key=lambda d: -d["week_mean"])
        if hit:
            names = ", ".join(d["name"] for d in hit[:3])
            lines.append(f"Degmooyinka ugu saameynta badan: {names}." if so else f"Districts most affected: {names}.")
    if area.get("chance_week50") is not None:
        c = area["chance_week50"]
        unit = ("gobolka" if kind == "region" else "degmada") if so else ("region" if kind == "region" else "district")
        lines.append(f"{c}% fursad in {unit} uu helo 50 mm iyo ka badan." if so
                     else f"{c}% chance of 50 mm or more over the {unit}.")
    lines.append((ADVICE_SO if so else ADVICE)["rain"])
    data = {"type": kind, "area": area.get("pcode", ""), "name": area["name"], "region": area.get("region", area["name"]),
            "days": ",".join(str(i + 1) for i in ev["day_idx"]), "level": str(ev["level"]),
            "mean": mean, "max": mx, "near": near[0] if near else "", "km": km,
            "lon": str(at[0]) if at else "", "lat": str(at[1]) if at else "",
            "chance": "" if area.get("chance_week50") is None else str(area["chance_week50"])}
    return {"title": title, "body": "\n".join(lines), "data": data}


def _basin_message(b: dict, meta: dict, so: bool) -> dict:
    mean = b["week_mean"]
    warning = mean >= 2 * config.ALERT_BASIN_WEEKLY_MM
    river, river_so = b["name"], RIVERS_SO.get(b["name"], b["name"])
    i = max(range(len(b["daily_mean"])), key=lambda k: b["daily_mean"][k])
    wet = dt.date.fromisoformat(meta["days"][i]["date"])
    if so:
        title = f"{'Digniin' if warning else 'Feejignaan'} webiga {river_so} · {mean:.0f} mm Itoobiya toddobaadkan"
        lines = [f"Maalinta ugu roobka badan: {_days_text([wet], True)}, qiyaastii {b['daily_mean'][i]:.0f} mm."]
    else:
        title = f"River {'warning' if warning else 'watch'} · {river} · {mean:.0f} mm upstream this week"
        lines = [f"Wettest day in the Ethiopian highlands: {_days_text([wet])}, about {b['daily_mean'][i]:.0f} mm."]
    c50, c100 = b.get("chance_week50"), b.get("chance_week100")
    if c50 is not None:
        lines.append(f"{c50}% fursad heerka feejignaanta (50 mm), {c100 or 0}% heerka digniinta (100 mm)." if so
                     else f"{c50}% chance of Watch level (50 mm), {c100 or 0}% Warning (100 mm).")
    lines.append(f"Biyaha webiga ee {RIVER_TOWNS_SO[river]} ayaa kici kara maalmaha xiga." if so
                 else f"River levels at {RIVER_TOWNS[river]} may rise in the following days.")
    lines.append((ADVICE_SO if so else ADVICE)["river"])
    data = {"type": "basin", "area": river.lower(), "name": river, "region": "", "days": str(i + 1),
            "level": "2" if warning else "1", "mean": f"{mean:.0f}", "max": f"{b['week_max']:.0f}", "near": "",
            "lon": "", "lat": "", "chance": "" if c50 is None else str(c50),
            "chance100": "" if c100 is None else str(c100)}
    return {"title": title, "body": "\n".join(lines), "data": data}


def _new_forecast(meta: dict, summary: dict, so: bool) -> dict:
    first = dt.date.fromisoformat(meta["first_day"])
    last = dt.date.fromisoformat(meta["last_day"])
    wet = sorted((r for r in summary["regions"] if r["week_mean"] >= 50), key=lambda r: -r["week_mean"])
    rivers = [b["name"] for b in summary.get("basins", [])
              if b["part"] == "upstream_of_somalia" and b["week_mean"] >= config.ALERT_BASIN_WEEKLY_MM]
    if so:
        body = f"Saadaasha roobka Soomaaliya ee {labels.week_range_so(first, last)} waa diyaar."
        if wet:
            body += " Roob culus: " + ", ".join(r["name"] for r in wet[:3]) + "."
        if rivers:
            body += " Feejignaan webi: " + " iyo ".join(RIVERS_SO.get(r, r) for r in rivers) + "."
        title = "Saadaal cusub oo roobka toddobaadka"
    else:
        body = f"Somalia rainfall forecast for {meta['week_range']} is out."
        if wet:
            body += " Heavy rain expected in " + ", ".join(r["name"] for r in wet[:3]) + "."
        if rivers:
            body += " River watch: " + " and ".join(rivers) + "."
        title = "New weekly rainfall forecast"
    return {"title": title, "body": body, "data": {"type": "new"}}


# ---------- what to send ----------
def plan_messages(meta: dict, summary: dict, places: list | None = None) -> list[dict]:
    """All alerts this forecast calls for, English and Somali. Each has a `state` (area, level, days)
    that send_alerts compares with what was already sent."""
    places = places or []
    first = dt.date.fromisoformat(meta["first_day"])
    iso = first.isocalendar()
    msgs = []
    for so in (False, True):
        pre = "so_" if so else ""
        lang = "so" if so else "en"
        m = _new_forecast(meta, summary, so)
        msgs.append({**m, "topic": pre + "new_forecast",
                     "state": {"id": f"{lang}|new|{iso[0]}-W{iso[1]:02d}", "level": 0, "days": []}})
        for kind, areas in (("region", summary["regions"]), ("district", summary.get("districts", []))):
            for a in areas:
                ev = _area_event(a, meta)
                if ev:
                    m = _rain_message(kind, a, ev, meta, summary, places, so)
                    msgs.append({**m, "topic": pre + topic_for(a),
                                 "state": {"id": f"{lang}|{kind}|{a.get('pcode') or a['name']}|{meta['first_day']}",
                                           "level": ev["level"], "days": [d.isoformat() for d in ev["days"]],
                                           "legacy": [f"{'so:' if so else ''}heavy:{a['name']}:{d.isoformat()}"
                                                      for d in ev["days"]]
                                           + [f"{'so:' if so else ''}heavy_week:{a['name']}:{meta['first_day']}"]}})
        for b in summary.get("basins", []):
            if b["part"] == "upstream_of_somalia" and b["week_mean"] >= config.ALERT_BASIN_WEEKLY_MM:
                m = _basin_message(b, meta, so)
                level = int(m["data"]["level"])
                msgs.append({**m, "topic": f"{pre}basin_{b['name'].lower()}",
                             "state": {"id": f"{lang}|basin|{b['name']}|{meta['first_day']}", "level": level,
                                       "days": [], "legacy": [f"{'so:' if so else ''}basin:{b['name']}:{meta['first_day']}"]}})
    for m in msgs:
        m["data"] = {"run_id": meta["run_id"], "first_day": meta["first_day"],
                     "lang": "so" if m["topic"].startswith("so_") else "en", **m["data"]}
    return msgs


def _decide(msgs: list[dict], sent: dict) -> list[dict]:
    """Messages to send now: new areas, or areas whose level rose or that gained heavy days ("Update:").
    `sent` maps state id -> {"level", "days"}; old style keys (before grouping) count as sent at level 3."""
    todo = []
    for m in msgs:
        s = m["state"]
        prev = sent.get(s["id"])
        legacy = [k for k in s.get("legacy", []) if k in sent.get("_legacy", ())]
        if prev is None and legacy:
            prev = {"level": 3 if "|basin|" not in s["id"] else 1,
                    "days": [k.rsplit(":", 1)[1] for k in legacy if k.startswith(("heavy:", "so:heavy:"))]}
        if prev is None:
            todo.append(m)
        elif s["level"] > prev["level"] or set(s["days"]) - set(prev["days"]):
            so = s["id"].startswith("so|")
            todo.append({**m, "title": ("Cusboonaysiin: " if so else "Update: ") + m["title"]})
    return todo


def _access_token(info: dict) -> str:
    from google.auth.transport.requests import Request
    from google.oauth2 import service_account
    creds = service_account.Credentials.from_service_account_info(
        info, scopes=["https://www.googleapis.com/auth/firebase.messaging"])
    creds.refresh(Request())
    return creds.token


def _send(messages: list[dict]) -> set[str]:
    """Send through FCM; returns the state ids that were accepted. Dry run without the service account."""
    raw = os.environ.get(config.FCM_ENV)
    if not raw:
        for m in messages:
            print(f"  alert (dry run, no {config.FCM_ENV}): [{m['topic']}] {m['title']}\n    "
                  + m["body"].replace("\n", "\n    "))
        return set()
    info = json.loads(raw)
    url = f"https://fcm.googleapis.com/v1/projects/{info['project_id']}/messages:send"
    headers = {"Authorization": f"Bearer {_access_token(info)}"}
    ok = set()
    for m in messages:
        body = {"message": {"topic": m["topic"],
                            "notification": {"title": m["title"], "body": m["body"]},
                            "data": {"title": m["title"], "body": m["body"], **m["data"]},
                            "android": {"priority": "high",
                                        "notification": {"channel_id": config.FCM_CHANNEL}}}}
        r = requests.post(url, json=body, headers=headers, timeout=30)
        if r.ok:
            ok.add(m["state"]["id"])
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
    data = {"run_id": latest.get("latest", ""), "type": "test"}
    _send([{"state": {"id": "test"}, "topic": config.FCM_TEST_TOPIC,
            "title": "Test notification",
            "body": f"Sahan Rainfall alerts are working ({when})."
                    + (f" Latest forecast: {run['week_range']}." if run else ""),
            "data": data},
           {"state": {"id": "so:test"}, "topic": "so_" + config.FCM_TEST_TOPIC,
            "title": "Ogeysiis tijaabo ah",
            "body": f"Digniinaha Sahan way shaqeynayaan ({when_so})."
                    + (f" Saadaashii u dambeysay: {week_so}." if run else ""),
            "data": data}])


def _load_sent(path: Path) -> dict:
    """sent_alerts.json: {state id: {level, days}}; the older list of keys is kept under "_legacy"."""
    if not path.exists():
        return {}
    raw = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(raw, list):
        return {"_legacy": raw}
    return raw


def send_alerts(meta: dict, summary: dict, site: Path):
    state_path = site / "sent_alerts.json"
    sent = _load_sent(state_path)
    msgs = plan_messages(meta, summary, load_places(site))
    todo = _decide(msgs, sent)
    if not todo:
        print("  alerts: nothing new to send")
        return
    accepted = _send(todo)
    if accepted:
        for m in todo:
            if m["state"]["id"] in accepted:
                sent[m["state"]["id"]] = {"level": m["state"]["level"], "days": m["state"]["days"]}
        state_path.write_text(json.dumps(sent, indent=0), encoding="utf-8")
