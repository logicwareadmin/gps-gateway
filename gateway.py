"""
Gateway TCP de equipos GPS/M2M → LogicWare (Traza).

Escucha el puerto donde "marca a casa" el equipo, AUTO-DETECTA el protocolo entre
los más usados del mercado M2M, parsea posición + telemetría y reenvía a la puerta
única de ingesta del backend: POST /tracking/ingest (auth X-API-Key).

Protocolos: Teltonika (Codec 8/8E), GT06/Concox, Queclink, Coban/GPS103.
El equipo se matchea al vehículo por IMEI (= Vehicle.tracker_device_id).

NO corre en DO App Platform (solo HTTP): va en un VPS/Droplet con IP fija y el
puerto TCP abierto. Ver README.md.

Env: GATEWAY_HOST (0.0.0.0) · GATEWAY_PORT (5027) · BACKEND_URL [req] ·
     API_KEY [req] · PROTOCOL (auto | teltonika | gt06 | queclink | coban)
"""
import asyncio
import os
import logging

import requests

from util import Buf
import teltonika
import gt06
import queclink
import coban

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger("gps-gateway")

HOST = os.environ.get("GATEWAY_HOST", "0.0.0.0")
PORT = int(os.environ.get("GATEWAY_PORT", "5027"))
BACKEND_URL = os.environ.get("BACKEND_URL", "").rstrip("/")
API_KEY = os.environ.get("API_KEY", "")
FORCE = os.environ.get("PROTOCOL", "auto").lower()

PROTOCOLS = [teltonika, gt06, queclink, coban]
BY_NAME = {m.NAME: m for m in PROTOCOLS}


def _forward(imei: str, fixes: list):
    """Reenvía un lote de fixes a /tracking/ingest. Bloqueante (se llama en thread)."""
    if not fixes:
        return
    positions = [{**f, "device_id": imei} for f in fixes]
    try:
        r = requests.post(
            f"{BACKEND_URL}/tracking/ingest",
            json={"positions": positions},
            headers={"X-API-Key": API_KEY},
            timeout=15,
        )
        if r.status_code >= 300:
            log.warning("ingest %s -> %s: %s", imei, r.status_code, r.text[:200])
        else:
            log.info("ingest %s: %s fix(es) -> %s", imei, len(positions), r.json())
    except Exception as e:
        log.warning("fallo ingest %s: %s", imei, e)


async def handle(reader: asyncio.StreamReader, writer: asyncio.StreamWriter):
    peer = writer.get_extra_info("peername")
    buf = Buf(reader)
    try:
        head = await asyncio.wait_for(buf.peek(16), timeout=30)
        if not head:
            return
        if FORCE != "auto" and FORCE in BY_NAME:
            mod = BY_NAME[FORCE]
        else:
            mod = next((m for m in PROTOCOLS if m.detect(head)), None)
        if not mod:
            log.info("protocolo no reconocido de %s (%r), cierro", peer, head[:12])
            return
        log.info("conexión %s → %s", peer, mod.NAME)
        await mod.handle(buf, writer, _forward, log.info)
    except (asyncio.IncompleteReadError, asyncio.TimeoutError, ConnectionResetError):
        pass
    except Exception as e:
        log.warning("error con %s: %s", peer, e)
    finally:
        try:
            writer.close()
        except Exception:
            pass


async def main():
    if not BACKEND_URL or not API_KEY:
        raise SystemExit("Faltan BACKEND_URL y/o API_KEY (ver README.md)")
    server = await asyncio.start_server(handle, HOST, PORT)
    log.info("gateway escuchando en %s:%s → %s (protocolo: %s)", HOST, PORT, BACKEND_URL, FORCE)
    async with server:
        await server.serve_forever()


if __name__ == "__main__":
    asyncio.run(main())
