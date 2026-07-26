from collections import defaultdict
from dataclasses import dataclass


@dataclass(frozen=True)
class DetectionSignal:
    equipment_id: str
    sensor_type: str
    status: str


class AnomalyDetector:
    """Detect critical samples and repeated warnings for each equipment sensor."""

    def __init__(self, warning_streak_threshold: int = 3) -> None:
        self._warning_streak_threshold = warning_streak_threshold
        self._warning_streaks: dict[tuple[str, str], int] = defaultdict(int)

    def evaluate(self, signal: DetectionSignal) -> str | None:
        key = (signal.equipment_id, signal.sensor_type)
        if signal.status == "critical":
            self._warning_streaks[key] = 0
            return "AUTO-CRITICAL"
        if signal.status != "warning":
            self._warning_streaks[key] = 0
            return None

        self._warning_streaks[key] += 1
        if self._warning_streaks[key] < self._warning_streak_threshold:
            return None

        self._warning_streaks[key] = 0
        return "AUTO-WARNING-STREAK"
