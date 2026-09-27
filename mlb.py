#!/usr/bin/env python3
"""
mlb.py — Alfred keyword: mlb
Single entry-point router for all MLB commands.

  mlb           → Today's scores (live → upcoming → final)
  mlbs          → Standings by division
  mlbp {name}   → Player stats search
  mlbt {query}  → Team stats (browse or search)

Since Alfred's `withspace: false` means typing "mlbs" is treated as
keyword "mlb" + query "s", this script routes based on the query prefix.
"""
from __future__ import annotations

import json
import os
import sys
import traceback


def main():
    query = sys.argv[1].strip() if len(sys.argv) > 1 else ""

    # ── Route based on query prefix ──────────────────────────────────────────
    if query.startswith("s"):
        # mlbs → standings
        from mlb_standings import main as standings_main
        standings_main()

    elif query.startswith("p"):
        # mlbp {name} → player search
        player_query = query[1:].strip()
        sys.argv = [sys.argv[0], player_query]
        from mlb_player import main as player_main
        player_main()

    elif query.startswith("t"):
        # mlbt {query} → team search
        team_query = query[1:].strip()
        sys.argv = [sys.argv[0], team_query]
        from mlb_team import main as team_main
        team_main()

    else:
        # Default: show today's scores
        scores_main()


# ══════════════════════════════════════════════════════════════════════════════
# Scores logic
# ══════════════════════════════════════════════════════════════════════════════
from datetime import datetime

from utils import (
    alfred_error, alfred_output,
    api_get, cache_get, cache_get_stale, cache_set,
    team_logo_path, team_abbr_from_id,
    utc_to_local, current_season,
    CACHE_DIR, WORKFLOW_DIR,
)
from image_utils import make_matchup_icon

CACHE_TTL  = 30
RERUN_LIVE = 5.0


def matchup_icon(away_id: int, home_id: int, away_abbr: str, home_abbr: str) -> str:
    name = f"matchup_{away_abbr}_{home_abbr}.png"
    path = os.path.join(CACHE_DIR, name)
    if os.path.exists(path):
        return path
    away_logo = team_logo_path(away_id)
    home_logo = team_logo_path(home_id)
    if make_matchup_icon(away_logo, home_logo, path):
        return path
    return home_logo


def inning_label(ls: dict) -> str:
    half = ls.get("inningHalf", "").lower()
    num  = ls.get("currentInning", "")
    if not num:
        return ""
    return {"top": "Top", "bottom": "Bot", "middle": "Mid", "end": "End"}.get(
        half, half.capitalize()
    ) + f" {num}"


def sort_key(game: dict) -> int:
    return {"Live": 0, "Preview": 1, "Final": 2}.get(
        game.get("status", {}).get("abstractGameState", ""), 3
    )


def build_item(game: dict) -> dict:
    away      = game["teams"]["away"]
    home      = game["teams"]["home"]
    away_team = away["team"]
    home_team = home["team"]
    away_id   = away_team["id"]
    home_id   = home_team["id"]
    away_abbr = away_team.get("abbreviation", away_team["name"][:3].upper())
    home_abbr = home_team.get("abbreviation", home_team["name"][:3].upper())
    away_score = away.get("score", 0)
    home_score = home.get("score", 0)
    game_pk   = game["gamePk"]
    state     = game["status"]["abstractGameState"]
    detailed  = game["status"].get("detailedState", "")
    ls        = game.get("linescore", {})

    live_url    = f"https://www.mlb.com/gameday/{game_pk}/live/box-score"
    preview_url = f"https://www.mlb.com/gameday/{game_pk}/preview/box-score"
    icon_path   = matchup_icon(away_id, home_id, away_abbr, home_abbr)

    if state == "Live":
        outs    = ls.get("outs", 0)
        out_s   = f"  {outs} out{'s' if outs != 1 else ''}"
        title   = f"{away_abbr} {away_score}  {home_abbr} {home_score}  —  {inning_label(ls)}{out_s}"
        sub     = f"🔴 LIVE  ·  {away_team['name']} @ {home_team['name']}"
        url     = live_url

    elif state == "Final":
        extra  = "/OT" if "Extra" in detailed else ""
        winner = away_abbr if away_score > home_score else home_abbr
        title  = f"{away_abbr} {away_score}  {home_abbr} {home_score}  —  Final{extra}  ({winner} win)"
        sub    = f"✅ Final  ·  {away_team['name']} @ {home_team['name']}"
        url    = live_url

    else:
        game_time = utc_to_local(game["gameDate"])
        title = f"{away_abbr}  @  {home_abbr}  —  {game_time}"
        sub   = f"⏰ {detailed or 'Scheduled'}  ·  {away_team['name']} @ {home_team['name']}"
        url   = preview_url

    return {
        "title":    title,
        "subtitle": sub,
        "arg":      url,
        "icon":     {"path": icon_path},
        "mods": {
            "cmd": {
                "subtitle": "⌘  Open box score on MLB.com",
                "arg": live_url,
            }
        },
    }


def scores_main():
    today     = datetime.now().strftime("%Y-%m-%d")
    cache_key = f"scores_{today}"

    data = cache_get(cache_key, CACHE_TTL)

    if data is None:
        try:
            data = api_get("/schedule", params={
                "sportId": 1,
                "hydrate": "linescore,team",
                "date":    today,
            })
            cache_set(cache_key, data)
        except Exception as e:
            stale = cache_get_stale(cache_key)
            if stale:
                data = stale
            else:
                alfred_error("Could not fetch MLB scores", str(e))
                return

    dates = data.get("dates", [])
    if not dates or not dates[0].get("games"):
        alfred_output([{
            "title":    "⚾ No MLB games today",
            "subtitle": f"Nothing scheduled for {today}",
            "valid":    False,
            "icon":     {"path": os.path.join(WORKFLOW_DIR, "icon.png")},
        }])
        return

    games = sorted(dates[0]["games"], key=sort_key)
    items = [build_item(g) for g in games]

    has_live = any(
        g.get("status", {}).get("abstractGameState") == "Live"
        for g in games
    )
    alfred_output(items, rerun=RERUN_LIVE if has_live else None)


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(json.dumps({"items": [{
            "title": "⚠️ MLB script error",
            "subtitle": str(exc),
            "valid": False,
            "icon": {"path": "icon.png"},
            "text": {"copy": traceback.format_exc()},
        }]}))
        sys.exit(0)
