"""Placeholder inference. Real model loading comes once train.py produces real artifacts."""


def predict_health(readings: list[dict]) -> dict:
    return {"status": "unknown", "confidence": 0.0, "note": "ML pipeline not yet implemented"}
