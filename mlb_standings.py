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
    team_logo_path, current_season, TEAM_BY_ID, WORKFLOW_DIR,
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
    t_meta  = TEAM_BY_ID.get(tid, {})
    slug    = t_meta.get("mlb_slug") or name.lower().replace(" ", "-")

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


def build_items(data: dict, query: str = "") -> list:
    div_map: dict[str, list] = {d: [] for d in DIVISION_ORDER}
    for group in data.get("records", []):
        div_id   = group.get("division", {}).get("id")
        div_name = DIVISION_IDS.get(div_id)
        if div_name:
            div_map[div_name].extend(group.get("teamRecords", []))

    q_words = query.lower().split() if query else []
    items = []
    for div in DIVISION_ORDER:
        teams = div_map.get(div, [])
        if not teams:
            continue
        if q_words and not all(w in div.lower() for w in q_words):
            matching_teams = []
            for rank, rec in enumerate(teams, 1):
                t = rec.get("team", {})
                t_meta = TEAM_BY_ID.get(t.get("id"), {})
                haystack = f"{div} {t.get('name', '')} {t_meta.get('abbreviation', '')} {t_meta.get('city', '')}".lower()
                if all(w in haystack for w in q_words):
                    matching_teams.append((rank, rec))
            if not matching_teams:
                continue
            items.append(header(div))
            for rank, rec in matching_teams:
                items.append(team_item(rank, rec))
            continue

        items.append(header(div))
        for rank, rec in enumerate(teams, 1):
            items.append(team_item(rank, rec))
    return items


def main():
    query     = sys.argv[1].strip() if len(sys.argv) > 1 else ""
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
        stale = cache_get_stale(cache_key)
        try:
            data = api_get("/standings", params=params)
            # If early in calendar year and regularSeason has no records yet, fallback to previous season
            if not data.get("records") and season > 2020:
                params["season"] = season - 1
                data = api_get("/standings", params=params)
            cache_set(cache_key, data)
        except Exception as e:
            if stale:
                data = stale
            else:
                alfred_error("Could not fetch MLB standings", str(e))
                return

    items = build_items(data, query)
    if not items:
        if query:
            alfred_output([{
                "title": f"⚾ No MLB standings matching '{query}'",
                "subtitle": "Try e.g. 'mlbs al east', 'mlbs nl west', or 'mlbs dodgers'",
                "valid": False,
                "icon": {"path": os.path.join(WORKFLOW_DIR, "icon.png")},
            }])
        else:
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
