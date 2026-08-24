"""Simulate a Carl hub publishing to Norman over MQTT.

Mirrors `firmware/hub/main/norman_uplink.c::publish_node()` — flat single-node
JSON on `carl/{site_id}/{node_id}`, no `ts` field, repeats every N seconds.

Usage (after `make dev` brings up postgres + mosquitto + api + ingest, and
`make seed` registers hub-001):
    python scripts/fake_hub_publish.py
    python scripts/fake_hub_publish.py --site hub-001 --node aabbccddeeff --interval 5
"""

import argparse
import asyncio
import json
import math
import random
from datetime import datetime, timezone


async def main_async(args: argparse.Namespace) -> None:
    # Lazy import so `--help` works without aiomqtt installed.
    from aiomqtt import Client

    topic = f"carl/{args.site}/{args.node}"
    print(
        f"connecting to {args.host}:{args.port} as fake hub "
        f"(site={args.site}, node={args.node}, interval={args.interval}s)"
    )

    async with Client(
        hostname=args.host,
        port=args.port,
        username=args.username or None,
        password=args.password or None,
    ) as client:
        i = 0
        while True:
            payload = {
                "node": args.node,
                "mac": args.mac,
                "name": args.name,
                "online": True,
                "soil_pct": round(40 + 5 * math.sin(i / 30), 1),
                "temperature_c": round(22 + 3 * math.sin(i / 12), 2),
                "humidity_pct": round(55 + 10 * math.cos(i / 17), 2),
                "pressure_hpa": round(1013 + random.uniform(-2, 2), 2),
                "illuminance_lux": round(max(0.0, 200 + 600 * math.sin(i / 24)), 0),
                "battery_pct": max(0, 90 - i // 50),
            }
            await client.publish(topic, payload=json.dumps(payload).encode("utf-8"), qos=1)
            ts = datetime.now(timezone.utc).isoformat()
            print(f"[{ts}] published to {topic}: soil={payload['soil_pct']}")
            i += 1
            await asyncio.sleep(args.interval)


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--host", default="localhost")
    p.add_argument("--port", type=int, default=1883)
    p.add_argument("--username", default=None)
    p.add_argument("--password", default=None)
    p.add_argument("--site", default="hub-001", help="Carl's CONFIG_CARL_NORMAN_SITE_ID")
    p.add_argument("--node", default="aabbccddeeff")
    p.add_argument("--mac", default="AA:BB:CC:DD:EE:FF")
    p.add_argument("--name", default="Bedroom Monstera")
    p.add_argument("--interval", type=float, default=5.0)
    args = p.parse_args()
    try:
        asyncio.run(main_async(args))
    except KeyboardInterrupt:
        pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
