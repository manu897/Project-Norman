"""Simulate a Carl hub POSTing a batch upload to Norman.

End-state shape: one room + one room-node + one plant-node + one camera-node.

Usage:
    # After `make seed` writes the demo token:
    python scripts/fake_hub_post.py
    python scripts/fake_hub_post.py --url http://localhost:8000 --hub hub-001
"""

import argparse
import json
import math
import pathlib
import random
import sys
from datetime import datetime, timedelta, timezone


def _iso(dt: datetime) -> str:
    return dt.isoformat().replace("+00:00", "Z")


def _plant_samples(n: int, now: datetime) -> list[dict]:
    out: list[dict] = []
    for i in range(n):
        t = now - timedelta(minutes=(n - i))
        out.append(
            {
                "ts": _iso(t),
                "soil_pct": round(40 + 5 * math.sin(i / 30), 1),
                "temperature_c": round(22 + 1.5 * math.sin(i / 12), 2),
                "humidity_pct": round(55 + 5 * math.cos(i / 17), 2),
                "illuminance_lux": round(max(0.0, 200 + 600 * math.sin(i / 24)), 0),
                "battery_pct": max(0, 90 - i // 50),
            }
        )
    return out


def _room_samples(n: int, now: datetime) -> list[dict]:
    out: list[dict] = []
    for i in range(n):
        t = now - timedelta(minutes=(n - i))
        out.append(
            {
                "ts": _iso(t),
                "temperature_c": round(23 + 2.5 * math.sin(i / 12) + random.uniform(-0.2, 0.2), 2),
                "humidity_pct": round(58 + 8 * math.cos(i / 17) + random.uniform(-1, 1), 2),
                "pressure_hpa": round(1013 + random.uniform(-2, 2), 2),
                "illuminance_lux": round(max(0.0, 400 + 500 * math.sin(i / 20)), 0),
            }
        )
    return out


def _camera_samples(n: int, now: datetime) -> list[dict]:
    """Camera nodes only heartbeat battery — actual images stay on the hub."""
    return [
        {"ts": _iso(now - timedelta(minutes=(n - i))), "battery_pct": 100}
        for i in range(n)
    ]


def _build_batch(args: argparse.Namespace) -> dict:
    now = datetime.now(timezone.utc)
    return {
        "hub_version": "0.2.0-fake",
        "generated_at": _iso(now),
        "rooms": [{"id": args.room_id, "name": "Bedroom"}],
        "nodes": [
            {
                "id": args.room_id,
                "kind": "room",
                "mac": "11:22:33:44:55:66",
                "name": "Bedroom Thingy",
                "samples": _room_samples(args.samples, now),
            },
            {
                "id": args.plant_id,
                "kind": "plant",
                "mac": "AA:BB:CC:DD:EE:FF",
                "name": "Bedroom Monstera",
                "room_id": args.room_id,
                "species": "monstera_deliciosa",
                "calibration": {
                    "soil_dry_pct": 25.0,
                    "soil_wet_pct": 65.0,
                    "battery_low_pct": 15,
                    "offline_after_minutes": 30,
                },
                "samples": _plant_samples(args.samples, now),
            },
            {
                "id": args.camera_id,
                "kind": "camera",
                "mac": "AA:BB:CC:DD:EE:01",
                "name": "Window Cam",
                "samples": _camera_samples(min(args.samples, 3), now),
            },
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", default="http://localhost:8000")
    parser.add_argument("--hub", default="hub-001")
    parser.add_argument("--room-id", default="room-bedroom")
    parser.add_argument("--plant-id", default="aabbccddeeff")
    parser.add_argument("--camera-id", default="aabbccddee01")
    parser.add_argument("--samples", type=int, default=12)
    parser.add_argument(
        "--token-file",
        default=".demo-hub-token",
        help="File written by `make seed` containing the demo hub token",
    )
    parser.add_argument("--token", default=None)
    args = parser.parse_args()

    token = args.token
    if token is None:
        p = pathlib.Path(args.token_file)
        if not p.exists():
            print(
                f"token file {p} not found — run `make seed` first or pass --token",
                file=sys.stderr,
            )
            return 2
        token = p.read_text().strip()

    # Import lazily so `--help` works in a venv without httpx installed.
    import httpx

    body = _build_batch(args)
    url = f"{args.url}/v1/hubs/{args.hub}/batch"
    print(
        f"POST {url}\n  rooms={len(body['rooms'])} nodes={len(body['nodes'])} "
        f"samples_per_node={args.samples}"
    )
    resp = httpx.post(
        url, headers={"Authorization": f"Bearer {token}"}, json=body, timeout=10
    )
    print(f"  → {resp.status_code} {resp.reason_phrase}")
    print(json.dumps(resp.json(), indent=2))
    return 0 if resp.is_success else 1


if __name__ == "__main__":
    raise SystemExit(main())
