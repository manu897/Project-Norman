"""Simulate a Carl hub POSTing a batch upload to Norman.

Usage:
    # After `make seed` writes the demo token:
    python scripts/fake_hub_post.py
    python scripts/fake_hub_post.py --url http://localhost:8000 --hub hub-001 --samples 60
"""

import argparse
import json
import math
import pathlib
import random
import sys
from datetime import datetime, timedelta, timezone

import httpx


def _build_batch(hub_id: str, n_samples: int, mac: str, name: str, node_id: str) -> dict:
    now = datetime.now(timezone.utc)
    samples = []
    for i in range(n_samples):
        t = now - timedelta(minutes=(n_samples - i))
        samples.append(
            {
                "ts": t.isoformat().replace("+00:00", "Z"),
                "temperature_c": round(22 + 3 * math.sin(i / 12) + random.uniform(-0.2, 0.2), 2),
                "humidity_pct": round(55 + 10 * math.cos(i / 17) + random.uniform(-1, 1), 2),
                "pressure_hpa": round(1013 + random.uniform(-2, 2), 2),
                "soil_pct": round(40 + 5 * math.sin(i / 30), 1),
                "illuminance_lux": round(max(0.0, 200 + 600 * math.sin(i / 24)), 0),
                "battery_pct": max(0, 90 - i // 50),
            }
        )
    return {
        "hub_version": "0.1.0-fake",
        "generated_at": now.isoformat().replace("+00:00", "Z"),
        "nodes": [
            {
                "id": node_id,
                "mac": mac,
                "name": name,
                "calibration": {
                    "soil_dry_pct": 25.0,
                    "soil_wet_pct": 65.0,
                    "battery_low_pct": 15,
                    "offline_after_minutes": 30,
                },
                "samples": samples,
            }
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", default="http://localhost:8000", help="Norman base URL")
    parser.add_argument("--hub", default="hub-001")
    parser.add_argument("--node-id", default="aabbccddeeff")
    parser.add_argument("--mac", default="AA:BB:CC:DD:EE:FF")
    parser.add_argument("--name", default="Bedroom Monstera")
    parser.add_argument("--samples", type=int, default=12)
    parser.add_argument(
        "--token-file",
        default=".demo-hub-token",
        help="File written by `make seed` containing the demo hub token",
    )
    parser.add_argument("--token", default=None, help="Override: pass the token directly")
    args = parser.parse_args()

    token = args.token
    if token is None:
        token_path = pathlib.Path(args.token_file)
        if not token_path.exists():
            print(
                f"token file {token_path} not found — run `make seed` first or pass --token",
                file=sys.stderr,
            )
            return 2
        token = token_path.read_text().strip()

    body = _build_batch(args.hub, args.samples, args.mac, args.name, args.node_id)
    url = f"{args.url}/v1/hubs/{args.hub}/batch"
    print(f"POST {url}  ({args.samples} samples for node {args.node_id})")
    resp = httpx.post(
        url,
        headers={"Authorization": f"Bearer {token}"},
        json=body,
        timeout=10,
    )
    print(f"  → {resp.status_code} {resp.reason_phrase}")
    print(json.dumps(resp.json(), indent=2))
    return 0 if resp.is_success else 1


if __name__ == "__main__":
    raise SystemExit(main())
