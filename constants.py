POINTS_BY_POSITION = {
    1: 5,
    2: 4,
    3: 3,
    4: 2,
}

MAX_POINTS_POSITION = 20
EVENT_CATEGORY_NAME = "CRC Events"
RACE_CONTROL_ROLE = "Race Control"
REMINDER_WINDOWS = (24 * 60 * 60, 60 * 60)


def points_for_position(position: int) -> int:
    if position in POINTS_BY_POSITION:
        return POINTS_BY_POSITION[position]
    if 5 <= position <= MAX_POINTS_POSITION:
        return 1
    return 0
