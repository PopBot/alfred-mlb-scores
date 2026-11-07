#!/usr/bin/env python3
"""
mlb_player.py — Alfred keyword: mlbp {name}
Search MLB players for current season stats.
Player headshots loaded live from MLB CDN and cached for 7 days.
Hitters: AVG / HR / RBI / OPS / SB
Pitchers: ERA / WHIP / K / W-L / IP
"""
from __future__ import annotations

import os
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed

from utils import (
    alfred_error, alfred_output,
    api_get, cache_get, cache_get_stale, cache_set,
    player_headshot_path, current_season,
    TEAM_BY_ID, WORKFLOW_DIR,
)

ROSTER_TTL  = 3600   # 1 hour
STATS_TTL   = 300    # 5 minutes
MAX_RESULTS = 9
PITCHER_POS = {"P", "SP", "RP", "CL"}


# ── Format helpers ─────────────────────────────────────────────────────────────
def fmt_avg(v) -> str:
    try:    return f".{int(round(float(v) * 1000)):03d}"
    except: return ".---"

def fmt_ops(v) -> str:
    try:
        f = float(v)
        return f"{f:.3f}" if f >= 1 else f".{int(round(f * 1000)):03d}"
    except: return ".---"

def fmt_float(v, decimals=2) -> str:
    try:    return f"{float(v):.{decimals}f}"
    except: return "—"


# ── Roster ─────────────────────────────────────────────────────────────────────
def fetch_roster(season: int) -> list[dict]:
    key  = f"roster_{season}"
    data = cache_get(key, ROSTER_TTL)
    if data:
        return data
    stale = cache_get_stale(key)
    try:
        raw = api_get("/sports/1/players", params={"season": season})
        people = [p for p in raw.get("people", []) if p.get("active", True)]
        if not people and season > 2020:
            raw = api_get("/sports/1/players", params={"season": season - 1})
            people = [p for p in raw.get("people", []) if p.get("active", True)]
        cache_set(key, people)
        return people
    except Exception:
        if stale:
            return stale
        raise


def search_players(roster: list[dict], query: str) -> list[dict]:
    words = query.lower().split()
    hits  = []
    for p in roster:
        name = p.get("fullName", "").lower()
        if all(w in name for w in words):
            hits.append(p)
    return hits[:MAX_RESULTS]


# ── Stats ──────────────────────────────────────────────────────────────────────
def fetch_stats(player_id: int, group: str, season: int) -> dict:
    key  = f"pstat_{player_id}_{group}_{season}"
    data = cache_get(key, STATS_TTL)
    if data is not None:
        return data
    stale = cache_get_stale(key)
    try:
        raw    = api_get(f"/people/{player_id}/stats", params={
            "stats": "season", "season": season, "group": group,
        })
        splits = raw.get("stats", [{}])[0].get("splits", [])
        stat   = splits[0].get("stat", {}) if splits else {}
        cache_set(key, stat)
        return stat
    except Exception:
        return stale if stale is not None else {}


# ── Item builders ──────────────────────────────────────────────────────────────
def player_team_name(player: dict) -> str:
    """Get team name from our local JSON — no extra API call."""
    tid = player.get("currentTeam", {}).get("id")
    if tid:
        t = TEAM_BY_ID.get(int(tid))
        if t:
            return t["abbreviation"]
    return "—"


def player_profile_url(player: dict) -> str:
    pid  = player["id"]
    slug = player.get("nameSlug", "")
    if slug:
        # MLB Stats API `nameSlug` already ends with `-{pid}` (e.g. `shohei-ohtani-660271`)
        return f"https://www.mlb.com/player/{slug}"
    return f"https://www.mlb.com/player/{pid}"


def build_hitter_item(player: dict, stat: dict, season: int, icon_path: str) -> dict:
    name = player.get("fullName", "Unknown")
    team = player_team_name(player)
    pos  = player.get("primaryPosition", {}).get("abbreviation", "—")
    url  = player_profile_url(player)

    avg = fmt_avg(stat.get("avg", 0))
    hr  = stat.get("homeRuns",    "—")
    rbi = stat.get("rbi",         "—")
    ops = fmt_ops(stat.get("ops", 0))
    sb  = stat.get("stolenBases", "—")
    gp  = stat.get("gamesPlayed", "—")

    return {
        "title":    f"{name}  ·  {team}  ({pos})",
        "subtitle": f"{season}  ·  {avg} AVG  {hr} HR  {rbi} RBI  {ops} OPS  {sb} SB  {gp} G",
        "arg":      url,
        "icon":     {"path": icon_path},
        "mods":     {"cmd": {"subtitle": "⌘  Open player profile on MLB.com", "arg": url}},
    }


def build_pitcher_item(player: dict, stat: dict, season: int, icon_path: str) -> dict:
    name = player.get("fullName", "Unknown")
    team = player_team_name(player)
    pos  = player.get("primaryPosition", {}).get("abbreviation", "—")
    url  = player_profile_url(player)

    era  = fmt_float(stat.get("era",           "—"))
    whip = fmt_float(stat.get("whip",          "—"))
    k    = stat.get("strikeOuts",    "—")
    w    = stat.get("wins",          "—")
    l    = stat.get("losses",        "—")
    ip   = stat.get("inningsPitched","—")
    gs   = stat.get("gamesStarted",  "—")

    return {
        "title":    f"{name}  ·  {team}  ({pos})",
        "subtitle": f"{season}  ·  {era} ERA  {whip} WHIP  {k} K  {w}-{l} W-L  {ip} IP  {gs} GS",
        "arg":      url,
        "icon":     {"path": icon_path},
        "mods":     {"cmd": {"subtitle": "⌘  Open player profile on MLB.com", "arg": url}},
    }


# ── Main ──────────────────────────────────────────────────────────────────────
def main():
    query  = sys.argv[1].strip() if len(sys.argv) > 1 else ""
    season = current_season()

    if len(query) < 2:
        alfred_output([{
            "title":    "👤 Type a player name…",
            "subtitle": "e.g.  mlbp trout   or   mlbp ohtani",
            "valid":    False,
            "icon":     {"path": os.path.join(WORKFLOW_DIR, "icon.png")},
        }])
        return

    try:
        roster = fetch_roster(season)
    except Exception as e:
        alfred_error("Could not fetch player roster", str(e))
        return

    matches = search_players(roster, query)
    if not matches:
        alfred_output([{
            "title":    f"No players found for \"{query}\"",
            "subtitle": "Try a different spelling — last name usually works best",
            "valid":    False,
            "icon":     {"path": os.path.join(WORKFLOW_DIR, "icon.png")},
        }])
        return

    # Fetch stats and headshots in parallel
    def fetch_for(player: dict):
        pid       = player["id"]
        pos       = player.get("primaryPosition", {}).get("abbreviation", "")
        group     = "pitching" if pos in PITCHER_POS else "hitting"
        stat      = fetch_stats(pid, group, season)
        icon_path = player_headshot_path(pid)
        return player, group, stat, icon_path

    order = {p["id"]: i for i, p in enumerate(matches)}
    results = []
    with ThreadPoolExecutor(max_workers=5) as pool:
        futures = {pool.submit(fetch_for, p): p for p in matches}
        for future in as_completed(futures):
            results.append(future.result())

    results.sort(key=lambda r: order.get(r[0]["id"], 999))

    items = []
    for player, group, stat, icon_path in results:
        if group == "pitching":
            items.append(build_pitcher_item(player, stat, season, icon_path))
        else:
            items.append(build_hitter_item(player, stat, season, icon_path))

    alfred_output(items)


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        import json as _json, traceback
        print(_json.dumps({"items": [{
            "title": "⚠️ MLB Player script error",
            "subtitle": str(exc),
            "valid": False,
            "icon": {"path": "icon.png"},
            "text": {"copy": traceback.format_exc()},
        }]}))
        sys.exit(0)
