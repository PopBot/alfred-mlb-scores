#!/usr/bin/env python3
"""
mlb_standings.py — Alfred keyword: mlbs
Standings by division. Cached for 5 min.
Uses stale-while-revalidate for instant response on repeat views.
"""
from __future__ import annotations

import os
import sys

from utils import (
    alfred_error, alfred_output,
    api_get, cache_get, cache_get_stale, cache_set,
    team_logo_path, current_season, WORKFLOW_DIR,
)

CACHE_TTL = 300   # 5 minutes

DIVISION_ORDER = [
    "AL East", "AL Central", "AL West",
    "NL East", "NL Central", "NL West",
]
DIVISION_IDS = {
    200: "AL West",  201: "AL East",  202: "AL Central",
    203: "NL West",  204: "NL East",  205: "NL Central",
}


def gb_display(gb) -> str:
    if gb in ("-", "", None):
        return "—"
    s = str(gb)
    return f"+{s}" if not s.startswith("-") else s


def header(division_name: str) -> dict:
    return {
        "title":    f"── {division_name} ──",
        "subtitle": "",
        "valid":    False,
        "icon":     {"path": os.path.join(WORKFLOW_DIR, "icon.png")},
    }


def team_item(rank: int, record: dict) -> dict:
    team    = record["team"]
    tid     = team["id"]
    name    = team["name"]
    wins    = record.get("wins", 0)
    losses  = record.get("losses", 0)
    gb      = gb_display(record.get("gamesBack", "-"))
    streak  = record.get("streak", {}).get("streakCode", "—")
    gp      = record.get("gamesPlayed", 1) or 1
    rs_g    = record.get("runsScored",  0) / gp
    ra_g    = record.get("runsAllowed", 0) / gp
    pct     = record.get("winningPercentage", ".000")
    slug    = team.get("teamCode", name.lower().replace(" ", "-"))

    return {
        "title":    f"{rank}. {name}",
        "subtitle": (
            f"{wins}-{losses}  ({pct})  GB: {gb}  "
            f"Streak: {streak}  RS/G: {rs_g:.1f}  RA/G: {ra_g:.1f}"
        ),
        "arg":  f"https://www.mlb.com/{slug}/schedule",
        "icon": {"path": team_logo_path(tid)},
        "mods": {
            "cmd": {
                "subtitle": f"⌘  Open {name} schedule",
                "arg":      f"https://www.mlb.com/{slug}/schedule",
            },
            "alt": {
                "subtitle": f"⌥  Open {name} roster",
                "arg":      f"https://www.mlb.com/{slug}/roster",
            },
        },
    }


def build_items(data: dict) -> list:
    div_map: dict[str, list] = {d: [] for d in DIVISION_ORDER}
    for group in data.get("records", []):
        div_id   = group.get("division", {}).get("id")
        div_name = DIVISION_IDS.get(div_id)
        if div_name:
            div_map[div_name].extend(group.get("teamRecords", []))

    items = []
    for div in DIVISION_ORDER:
        teams = div_map.get(div, [])
        if teams:
            items.append(header(div))
            for rank, rec in enumerate(teams, 1):
                items.append(team_item(rank, rec))
    return items


def main():
    season    = current_season()
    cache_key = f"standings_{season}"
    params    = {
        "leagueId":      "103,104",
        "season":        season,
        "standingsTypes":"regularSeason",
        "hydrate":       "team,division",
    }

    # Fresh cache → instant return
    data = cache_get(cache_key, CACHE_TTL)

    if data is None:
        # Stale cache → return immediately, rerun fetches fresh
        stale = cache_get_stale(cache_key)
        if stale:
            items = build_items(stale)
            if items:
                alfred_output(items)
                return

        # No cache → fetch now
        try:
            data = api_get("/standings", params=params)
            cache_set(cache_key, data)
        except Exception as e:
            alfred_error("Could not fetch MLB standings", str(e))
            return

    items = build_items(data)
    if not items:
        alfred_error("No standings data available", f"Season {season}")
        return

    alfred_output(items)


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        import json as _json, traceback
        print(_json.dumps({"items": [{
            "title": "⚠️ MLB Standings script error",
            "subtitle": str(exc),
            "valid": False,
            "icon": {"path": "icon.png"},
            "text": {"copy": traceback.format_exc()},
        }]}))
        sys.exit(0)
