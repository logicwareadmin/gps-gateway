"""
Queclink (GV serie) — protocolo ASCII, común en M2M/flota. Mensajes
'+RESP:GT...' / '+BUFF:GT...' separados por coma y terminados en '$'.

El layout exacto varía por modelo/firmware, así que la posición (lng, lat,
hora UTC) se ubica por PATRÓN: float, float, y 14 dígitos de fecha consecutivos.
VALIDAR con un equipo real.
"""
import asyncio
from datetime import datetime, timezone

NAME = "queclink"


def detect(head: bytes) -> bool:
    return head[:6] in (b"+RESP:", b"+BUFF:") or head[:5] == b"+ACK:"


def _is_float(s: str) -> bool:
    try:
        float(s)
        return True
    except (ValueError, TypeError):
        return False


def _decode(parts):
    n = len(parts)
    for i in range(3, n - 2):
        a, b, c = parts[i], parts[i + 1], parts[i + 2]
        if _is_float(a) and _is_float(b) and len(c) == 14 and c.isdigit():
            lng, lat = float(a), float(b)
            if -180 <= lng <= 180 and -90 <= lat <= 90 and (lng or lat):
                try:
                    ts = datetime.strptime(c, "%Y%m%d%H%M%S").replace(tzinfo=timezone.utc).isoformat()
                except ValueError:
                    ts = datetime.now(timezone.utc).isoformat()
                speed = float(parts[i - 3]) if i >= 3 and _is_float(parts[i - 3]) else 0
                heading = float(parts[i - 2]) if i >= 2 and _is_float(parts[i - 2]) else 0
                return {"ts": ts, "lat": round(lat, 7), "lng": round(lng, 7),
                        "speed": round(speed), "heading": round(heading),
                        "satellites": None, "ignition": None, "attributes": {}}
    return None


async def handle(buf, writer, forward, log):
    imei = None
    while True:
        raw = await buf.until(b"$")
        line = raw.decode("ascii", "ignore").strip().strip("\r\n")
        if not line:
            continue
        parts = line.split(",")
        if len(parts) < 4:
            continue
        if len(parts) > 2 and parts[2].isdigit() and len(parts[2]) >= 14:
            imei = parts[2]
            if imei not in (None,) and not _seen_imei(imei):
                log(f"queclink IMEI={imei}")
        if parts[0].startswith("+ACK"):
            continue
        fix = _decode(parts)
        if fix and imei:
            await asyncio.to_thread(forward, imei, [fix])


_seen = set()


def _seen_imei(imei: str) -> bool:
    if imei in _seen:
        return True
    _seen.add(imei)
    return False
