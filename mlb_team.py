#!/usr/bin/env python3
"""
mlb_team.py — Alfred keyword: mlbt {query}
Shows team season record by default.
  ⌘  → Team batting stats (AVG / HR / RBI / OPS / SB)
  ⌥  → Team pitching stats (ERA / WHIP / K / SV)
No query → all 30 teams sorted by win %.
"""
from __future__ import annotations

import os
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed

from utils import (
    alfred_error, alfred_output,
    api_get, cache_get, cache_get_stale, cache_set,
    team_logo_path, current_season,
    TEAMS, WORKFLOW_DIR,
)

CACHE_TTL = 300   # 5 minutes


# ── Team search ────────────────────────────────────────────────────────────────
def search_teams(query: str) -> list[dict]:
    q = query.lower().strip()
    if not q:
        return TEAMS
    return [
        t for t in TEAMS
        if q in t["name"].lower()
        or q in t["city"].lower()
        or q in t["abbreviation"].lower()
        or q in t["division"].lower()
        or q in t.get("mlb_slug", "").lower()
    ]


# ── Standings ──────────────────────────────────────────────────────────────────
def fetch_standings(season: int) -> dict[int, dict]:
    key = f"standings_{season}"
    data = cache_get(key, CACHE_TTL) or cache_get_stale(key)
    if not data:
        data = api_get("/standings", params={
            "leagueId": "103,104", "season": season,
            "standingsTypes": "regularSeason", "hydrate": "team",
        })
        cache_set(key, data)
    result: dict[int, dict] = {}
    for group in data.get("records", []):
        for tr in group.get("teamRecords", []):
            result[tr["team"]["id"]] = tr
    return result


# ── Team stats ─────────────────────────────────────────────────────────────────
def fetch_team_stats(team_id: int, group: str, season: int) -> dict:
    key  = f"team_{group}_{team_id}_{season}"
    data = cache_get(key, CACHE_TTL) or cache_get_stale(key)
    if data:
        return data
    try:
        raw    = api_get(f"/teams/{team_id}/stats", params={
            "stats": "season", "season": season, "group": group,
        })
        splits = raw.get("stats", [{}])[0].get("splits", [])
        data   = splits[0].get("stat", {}) if splits else {}
    except Exception:
        data = {}
    cache_set(key, data)
    return data


# ── Format ─────────────────────────────────────────────────────────────────────
def fmt_avg(v) -> str:
    try:    return f".{int(round(float(v) * 1000)):03d}"
    except: return ".---"

def fmt_ops(v) -> str:
    try:
        f = float(v)
        return f"{f:.3f}" if f >= 1 else f".{int(round(f * 1000)):03d}"
    except: return ".---"

def fmt_float(v, d=2) -> str:
    try:    return f"{float(v):.{d}f}"
    except: return "—"

def gb_display(gb) -> str:
    if gb in ("-", "", None): return "—"
    s = str(gb)
    return f"+{s}" if not s.startswith("-") else s


# ── Item builder ───────────────────────────────────────────────────────────────
def build_item(team: dict, standings: dict, bat: dict, pit: dict, season: int) -> dict:
    tid  = team["id"]
    name = team["name"]
    slug = team["mlb_slug"]

    sr     = standings.get(tid, {})
    w      = sr.get("wins",   "—")
    l      = sr.get("losses", "—")
    gb     = gb_display(sr.get("gamesBack", "-"))
    pct    = sr.get("winningPercentage", ".---")
    streak = sr.get("streak", {}).get("streakCode", "—")
    gp     = sr.get("gamesPlayed", 1) or 1
    rs_g   = sr.get("runsScored",  0) / gp
    ra_g   = sr.get("runsAllowed", 0) / gp
    div    = team.get("division", "")

    # ── Default subtitle: season record
    default_sub = (
        f"{w}-{l}  ({pct})  GB: {gb}  "
        f"Streak: {streak}  RS/G: {rs_g:.1f}  RA/G: {ra_g:.1f}  [{div}]"
    )

    # ── ⌘ Batting
    avg = fmt_avg(bat.get("avg", 0))
    hr  = bat.get("homeRuns",    "—")
    rbi = bat.get("rbi",         "—")
    ops = fmt_ops(bat.get("ops", 0))
    sb  = bat.get("stolenBases", "—")
    bat_sub = (
        f"⌘ Batting {season}  ·  "
        f"{avg} AVG  {hr} HR  {rbi} RBI  {ops} OPS  {sb} SB"
    )

    # ── ⌥ Pitching
    era  = fmt_float(pit.get("era",  "—"))
    whip = fmt_float(pit.get("whip", "—"))
    k    = pit.get("strikeOuts", "—")
    sv   = pit.get("saves",      "—")
    pit_sub = (
        f"⌥ Pitching {season}  ·  "
        f"{era} ERA  {whip} WHIP  {k} K  {sv} SV"
    )

    return {
        "title":    name,
        "subtitle": default_sub,
        "arg":      f"https://www.mlb.com/{slug}",
        "icon":     {"path": team_logo_path(tid)},
        "mods": {
            "cmd": {
                "subtitle": bat_sub,
                "arg":      f"https://www.mlb.com/{slug}/stats",
            },
            "alt": {
                "subtitle": pit_sub,
                "arg":      f"https://www.mlb.com/{slug}/stats/pitching",
            },
        },
    }


# ── Main ──────────────────────────────────────────────────────────────────────
def main():
    query  = sys.argv[1].strip() if len(sys.argv) > 1 else ""
    season = current_season()
    teams  = search_teams(query)

    if not teams:
        alfred_output([{
            "title":    f"No teams found for \"{query}\"",
            "subtitle": "Try: city, name, abbreviation, or division (e.g. LAD, dodgers, NL West)",
            "valid":    False,
            "icon":     {"path": os.path.join(WORKFLOW_DIR, "icon.png")},
        }])
        return

    try:
        standings = fetch_standings(season)
    except Exception as e:
        alfred_error("Could not fetch standings", str(e))
        return

    def fetch_team(team: dict):
        tid = team["id"]
        bat = fetch_team_stats(tid, "hitting",  season)
        pit = fetch_team_stats(tid, "pitching", season)
        return team, bat, pit

    results = []
    with ThreadPoolExecutor(max_workers=8) as pool:
        futures = {pool.submit(fetch_team, t): t for t in teams}
        for future in as_completed(futures):
            results.append(future.result())

    # Sort by win percentage descending
    def sort_key(r):
        tid = r[0]["id"]
        try:    return -float(standings.get(tid, {}).get("winningPercentage", "0"))
        except: return 0

    results.sort(key=sort_key)
    items = [build_item(t, standings, bat, pit, season) for t, bat, pit in results]
    alfred_output(items)


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        import json as _json, traceback
        print(_json.dumps({"items": [{
            "title": "⚠️ MLB Team script error",
            "subtitle": str(exc),
            "valid": False,
            "icon": {"path": "icon.png"},
            "text": {"copy": traceback.format_exc()},
        }]}))
        sys.exit(0)
