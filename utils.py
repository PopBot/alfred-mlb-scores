#!/usr/bin/env python3
"""
Shared utilities for the MLB Alfred workflow.
Bundled lib/ is loaded first so requests always works regardless of
which Python version Alfred uses on the Mac.
"""
from __future__ import annotations

import json
import os
import sys
import time
from datetime import datetime

# ── Bundled dependencies ──────────────────────────────────────────────────────
_LIB = os.path.join(os.path.dirname(os.path.abspath(__file__)), "lib")
if _LIB not in sys.path:
    sys.path.insert(0, _LIB)

import requests

# ── Paths ─────────────────────────────────────────────────────────────────────
WORKFLOW_DIR = os.path.dirname(os.path.abspath(__file__))
CACHE_DIR    = os.environ.get("alfred_workflow_cache", os.path.join(WORKFLOW_DIR, ".cache"))
HEADSHOT_DIR = os.path.join(CACHE_DIR, "headshots")
LOGO_DIR     = os.path.join(WORKFLOW_DIR, "mlb_logos")
TEAMS_FILE   = os.path.join(WORKFLOW_DIR, "data", "teams.json")

os.makedirs(CACHE_DIR,    exist_ok=True)
os.makedirs(HEADSHOT_DIR, exist_ok=True)

# ── Teams ──────────────────────────────────────────────────────────────────────
with open(TEAMS_FILE) as f:
    TEAMS: list[dict] = json.load(f)

TEAM_BY_ID:   dict[int, dict] = {t["id"]: t for t in TEAMS}
TEAM_BY_ABBR: dict[str, dict] = {t["abbreviation"]: t for t in TEAMS}


def team_logo_path(team_id: int) -> str:
    team = TEAM_BY_ID.get(team_id)
    if team:
        path = os.path.join(LOGO_DIR, f"{team['abbreviation']}.png")
        if os.path.exists(path):
            return path
    return os.path.join(WORKFLOW_DIR, "icon.png")


def team_name_from_id(team_id: int) -> str:
    """Look up team name from our local teams.json — no extra API call needed."""
    t = TEAM_BY_ID.get(team_id)
    return t["name"] if t else "—"


def team_abbr_from_id(team_id: int) -> str:
    t = TEAM_BY_ID.get(team_id)
    return t["abbreviation"] if t else "—"


# ── File Cache ─────────────────────────────────────────────────────────────────
def cache_get(key: str, ttl: int):
    """Return cached data only if younger than ttl seconds, else None."""
    path = os.path.join(CACHE_DIR, f"{key}.json")
    if os.path.exists(path) and time.time() - os.path.getmtime(path) < ttl:
        try:
            with open(path) as f:
                return json.load(f)
        except Exception:
            pass
    return None


def cache_get_stale(key: str):
    """Return cached data regardless of age (stale-while-revalidate). None if missing."""
    path = os.path.join(CACHE_DIR, f"{key}.json")
    if os.path.exists(path):
        try:
            with open(path) as f:
                return json.load(f)
        except Exception:
            pass
    return None


def cache_set(key: str, data) -> None:
    path = os.path.join(CACHE_DIR, f"{key}.json")
    with open(path, "w") as f:
        json.dump(data, f)


# ── HTTP ───────────────────────────────────────────────────────────────────────
BASE_URL = "https://statsapi.mlb.com/api/v1"
HEADERS  = {"User-Agent": "Alfred-MLB-Workflow/1.0"}


def api_get(endpoint: str, params: dict | None = None) -> dict:
    r = requests.get(f"{BASE_URL}{endpoint}", params=params,
                     headers=HEADERS, timeout=5)
    r.raise_for_status()
    return r.json()


def current_season() -> int:
    return datetime.now().year


# ── Timezone ───────────────────────────────────────────────────────────────────
def utc_to_local(utc_str: str) -> str:
    """Convert '2026-04-05T00:10:00Z' → local time like '8:10 PM'."""
    dt    = datetime.fromisoformat(utc_str.replace("Z", "+00:00"))
    local = dt.astimezone()   # reads macOS system timezone automatically
    return local.strftime("%-I:%M %p")


# ── Player Headshots ───────────────────────────────────────────────────────────
HEADSHOT_TTL = 7 * 24 * 3600

MLB_HEADSHOT = (
    "https://img.mlbstatic.com/mlb-photos/image/upload"
    "/d_people:generic:headshot:67:current.png"
    "/w_180,q_auto:best/v1/people/{player_id}/headshot/67/current"
)


def player_headshot_path(player_id: int) -> str:
    """Local path to cached player headshot. Downloads on first use."""
    path = os.path.join(HEADSHOT_DIR, f"{player_id}.png")
    if os.path.exists(path) and time.time() - os.path.getmtime(path) < HEADSHOT_TTL:
        return path
    url = MLB_HEADSHOT.format(player_id=player_id)
    try:
        r = requests.get(url, headers=HEADERS, timeout=4)
        if r.status_code == 200 and "image" in r.headers.get("Content-Type", ""):
            with open(path, "wb") as f:
                f.write(r.content)
            return path
    except Exception:
        pass
    return os.path.join(WORKFLOW_DIR, "icon.png")


# ── Alfred Output ──────────────────────────────────────────────────────────────
def alfred_error(message: str, detail: str = "") -> None:
    items = [{"title": f"⚠️ {message}", "subtitle": detail, "valid": False,
              "icon": {"path": os.path.join(WORKFLOW_DIR, "icon.png")}}]
    print(json.dumps({"items": items}))
    sys.exit(0)


def alfred_output(items: list, rerun: float | None = None) -> None:
    out: dict = {"items": items}
    if rerun:
        out["rerun"] = rerun
    print(json.dumps(out))
