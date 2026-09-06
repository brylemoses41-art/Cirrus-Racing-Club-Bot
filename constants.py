POINTS_BY_POSITION = {
    1: 15,
    2: 12,
    3: 10,
    4: 8,
    5: 6,
    6: 5,
    7: 4,
    8: 3,
    9: 2,
    10: 1,
}

MAX_POINTS_POSITION = 10
QUALIFYING_BONUS = 5
CLEAN_RACE_BONUS = 5
EVENT_CATEGORY_NAME = "CRC Events"
RACE_CONTROL_ROLE = "Race Control"
REMINDER_WINDOWS = (24 * 60 * 60, 60 * 60)


def points_for_position(position: int) -> int:
    return POINTS_BY_POSITION.get(position, 0)
