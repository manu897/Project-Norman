"""Simulate a Carl hub publishing BME680 readings via MQTT.

Usage:
    python scripts/fake_publisher.py --hub hub-001 --sensor node-3
"""

import argparse
import asyncio
import json
import math
import random
from datetime import datetime, timezone

from aiomqtt import Client


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="localhost")
    parser.add_argument("--port", type=int, default=1883)
    parser.add_argument("--hub", default="hub-001")
    parser.add_argument("--sensor", default="node-3")
    parser.add_argument("--interval", type=float, default=5.0, help="seconds between samples")
    args = parser.parse_args()

    topic = f"carl/{args.hub}/sensor/{args.sensor}/telemetry"
    print(f"publishing to {topic} every {args.interval}s on {args.host}:{args.port}")

    async with Client(hostname=args.host, port=args.port) as client:
        i = 0
        while True:
            t = datetime.now(timezone.utc)
            payload = {
                "ts": t.isoformat().replace("+00:00", "Z"),
                "hub_id": args.hub,
                "sensor_id": args.sensor,
                "metrics": {
                    "temperature_c": round(22 + 3 * math.sin(i / 12) + random.uniform(-0.2, 0.2), 2),
                    "humidity_pct": round(55 + 10 * math.cos(i / 17) + random.uniform(-1, 1), 2),
                    "pressure_hpa": round(1013 + random.uniform(-2, 2), 2),
                    "voc_index": round(120 + 40 * math.sin(i / 5), 0),
                    "battery_v": round(3.85 - i * 0.0001, 3),
                    "rssi_dbm": random.randint(-80, -55),
                },
            }
            await client.publish(topic, payload=json.dumps(payload).encode("utf-8"), qos=1)
            print(f"[{t.isoformat()}] published {len(payload['metrics'])} metrics")
            i += 1
            await asyncio.sleep(args.interval)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
