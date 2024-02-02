

from pydantic import BaseModel, ValidationError, model_validator, field_validator
from typing import Optional, TypeVar, Type, Tuple

# Initialize console logging
import logging
logging.basicConfig(level=logging.WARNING)
logger = logging.getLogger(__name__)


def update_time(time: str, hours_passed: int = 0, minutes_passed: int = 0) -> str:
    """
    Update the date/time based on the old time and the number of minutes passed.

    Args:
        time (str): Current time in the format "Day #, HH:MM".
        hours_passed (int): Number of hours to add.
        minutes_passed (int): Number of minutes to add.

    Returns:
        str: Updated time in the same format.
    """

    # Extract current day, hour, and minute
    day, current_time = time.split(", ")
    day_num = int(day.split(" ")[1])
    current_hour, current_minute = map(int, current_time.split(":"))

    # Calculate total minutes and hours
    total_minutes = current_minute + minutes_passed
    total_hours = current_hour + hours_passed + total_minutes // 60

    # Calculate new minutes and handle overflow into hours
    new_minute = total_minutes % 60

    # Calculate new hours and handle overflow into days
    new_hour = total_hours % 24
    additional_days = total_hours // 24

    # Increment day
    day_num += additional_days

    # Construct new time string
    new_time = f"Day {day_num}, {new_hour:02d}:{new_minute:02d}"
    return new_time
