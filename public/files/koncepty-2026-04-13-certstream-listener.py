import asyncio
import websockets
import json
from datetime import datetime

WS_URL = "ws://localhost:8080/domains-only"
LOG_FILE = "certstream_listener_log.txt"


def log_line(line):
    with open(LOG_FILE, "a", encoding="utf-8") as f:
        f.write(line + "\n")


async def listen():
    async with websockets.connect(WS_URL) as ws:
        while True:
            msg = await ws.recv()
            data = json.loads(msg)

            if data.get("message_type") != "dns_entries":
                continue

            domains = data.get("data", [])

            for domain in domains:
                clean = domain[2:] if domain.startswith("*.") else domain
                url = f"https://{clean}"

                timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

                line = f"[{timestamp}] {url}"

                print(line)
                log_line(line)


asyncio.run(listen())
