from services.incident.app.detection import AnomalyDetector, DetectionSignal


def signal(status: str, sensor_type: str = "bearing_temperature") -> DetectionSignal:
    return DetectionSignal(
        equipment_id="PRESS-001",
        sensor_type=sensor_type,
        status=status,
    )


def test_critical_sample_triggers_incident_immediately() -> None:
    detector = AnomalyDetector()

    assert detector.evaluate(signal("critical")) == "AUTO-CRITICAL"


def test_three_consecutive_warnings_trigger_incident() -> None:
    detector = AnomalyDetector(warning_streak_threshold=3)

    assert detector.evaluate(signal("warning")) is None
    assert detector.evaluate(signal("warning")) is None
    assert detector.evaluate(signal("warning")) == "AUTO-WARNING-STREAK"


def test_normal_sample_resets_warning_streak_per_sensor() -> None:
    detector = AnomalyDetector(warning_streak_threshold=2)

    assert detector.evaluate(signal("warning")) is None
    assert detector.evaluate(signal("normal")) is None
    assert detector.evaluate(signal("warning")) is None
    assert detector.evaluate(signal("warning", "vibration_rms")) is None
