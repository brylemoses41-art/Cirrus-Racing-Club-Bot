from __future__ import annotations

from constants import points_for_position
from storage import load_json, save_json

RANKS = (
    (0, "Rookie", "🟢"),
    (50, "Novice", "🔵"),
    (150, "Semi-Pro", "🟣"),
    (300, "Master", "🟠"),
    (500, "Elite", "🔴"),
)

RANK_ROLE_NAMES = tuple(rank[1] for rank in RANKS)
PARTICIPATION_XP = 5
QUALIFYING_BONUS_XP = 5
CLEAN_RACE_BONUS_XP = 5


def rank_for_xp(xp: int) -> tuple[str, str, int | None]:
    current_index = 0
    for index, (threshold, _name, _badge) in enumerate(RANKS):
        if xp >= threshold:
            current_index = index
    _threshold, name, badge = RANKS[current_index]
    next_threshold = RANKS[current_index + 1][0] if current_index + 1 < len(RANKS) else None
    return name, badge, next_threshold


def parse_lap_time(value: str) -> float | None:
    try:
        parts = str(value).strip().split(":")
        if len(parts) == 1:
            return float(parts[0])
        if len(parts) == 2:
            return float(parts[0]) * 60 + float(parts[1])
        if len(parts) == 3:
            return float(parts[0]) * 3600 + float(parts[1]) * 60 + float(parts[2])
    except (TypeError, ValueError):
        return None
    return None


def fastest_qualifying_driver(race: dict) -> str | None:
    best_driver = None
    best_time = None
    for entry in race.get("qualifying", []):
        lap = parse_lap_time(entry.get("lap_time", ""))
        driver = str(entry.get("driver", "")).strip()
        if lap is None or not driver:
            continue
        if best_time is None or lap < best_time:
            best_time = lap
            best_driver = driver
    return best_driver


def is_clean_race(race: dict, driver_name: str) -> bool:
    target = driver_name.strip().lower()
    reported = any(str(item.get("driver", "")).strip().lower() == target for item in race.get("reports", []))
    penalized = any(str(item.get("driver", "")).strip().lower() == target for item in race.get("penalties", []))
    return not reported and not penalized


def official_result_points(race: dict, result: dict) -> int:
    driver = str(result.get("driver", "")).strip()
    position = int(result.get("position", 0) or 0)
    points = points_for_position(position)
    fastest = fastest_qualifying_driver(race)
    if driver and fastest and fastest.strip().lower() == driver.lower():
        points += QUALIFYING_BONUS_XP
    if driver and is_clean_race(race, driver):
        points += CLEAN_RACE_BONUS_XP
    return points


def calculate_driver_xp(driver_name: str, races: list[dict]) -> int:
    target = driver_name.strip().lower()
    xp = 0
    for race in races:
        for result in race.get("results", []):
            if str(result.get("driver", "")).strip().lower() == target:
                xp += official_result_points(race, result)
                xp += PARTICIPATION_XP
    return xp


def reconcile_driver_records() -> dict[str, dict]:
    drivers_data = load_json("drivers.json", {"drivers": {}})
    races_data = load_json("races.json", {"races": []})
    drivers = drivers_data.setdefault("drivers", {})
    races = races_data.setdefault("races", [])

    races_changed = False
    for race in races:
        fastest = fastest_qualifying_driver(race)
        for result in race.get("results", []):
            new_points = official_result_points(race, result)
            if int(result.get("points", 0) or 0) != new_points:
                result["points"] = new_points
                races_changed = True
        if race.get("fastest_qualifying_driver") != fastest:
            race["fastest_qualifying_driver"] = fastest
            races_changed = True
    if races_changed:
        save_json("races.json", races_data)

    changed = {}
    for entry in drivers.values():
        name = str(entry.get("name", "")).strip()
        if not name:
            continue
        xp = calculate_driver_xp(name, races)
        rank, badge, next_xp = rank_for_xp(xp)
        old_xp = int(entry.get("xp", entry.get("rating", 0)) or 0)
        old_rank = str(entry.get("rank", ""))
        entry["xp"] = xp
        entry["rating"] = xp
        entry["rank"] = rank
        entry["rank_badge"] = badge
        entry["next_rank_xp"] = next_xp
        if old_xp != xp or old_rank != rank:
            changed[str(entry.get("discord_id", ""))] = {
                "name": name,
                "old_xp": old_xp,
                "xp": xp,
                "old_rank": old_rank or "Rookie",
                "rank": rank,
            }
    save_json("drivers.json", drivers_data)
    return changed
