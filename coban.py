"""
Coban / GPS103 (TK103 y clones) — protocolo ASCII simple, muy usado en equipos
económicos. Mensajes terminados en ';'.

  Login:      ##,imei:<imei>,A;            -> responder "LOAD"
  Heartbeat:  <imei>;                       -> responder "ON"
  Ubicación:  imei:<imei>,tracker,<fecha>,<tel>,F,<hhmmss.sss>,<A/V>,
              <ddmm.mmmm>,<N/S>,<dddmm.mmmm>,<E/W>,<vel_nudos>,<rumbo>;

VALIDAR con un equipo real (hay variantes de formato según firmware).
"""
import asyncio
from datetime import datetime, timezone

NAME = "coban"


def detect(head: bytes) -> bool:
    h = head[:8].lower()
    return h.startswith(b"##") or h.startswith(b"imei:")


def _imei(token: str):
    i = token.lower().find("imei:")
    if i < 0:
        return None
    rest = token[i + 5:]
    digits = ""
    for ch in rest:
        if ch.isdigit():
            digits += ch
        else:
            break
    return digits or None


def _dm(val: str, deg_digits: int):
    """ddmm.mmmm / dddmm.mmmm -> grados decimales."""
    try:
        d = int(val[:deg_digits])
        m = float(val[deg_digits:])
        return d + m / 60.0
    except (ValueError, IndexError):
        return None


def _decode(token: str):
    parts = token.split(",")
    if len(parts) < 12:
        return None, _imei(token)
    imei = _imei(parts[0])
    try:
        valid = parts[6].upper() == "A"
        lat = _dm(parts[7], 2)
        if lat is not None and parts[8].upper() == "S":
            lat = -lat
        lng = _dm(parts[9], 3)
        if lng is not None and parts[10].upper() == "W":
            lng = -lng
        speed = float(parts[11]) * 1.852 if parts[11] else 0  # nudos -> km/h
        course = float(parts[12]) if len(parts) > 12 and parts[12] else 0
    except (ValueError, IndexError):
        return None, imei
    if lat is None or lng is None or not valid:
        return None, imei
    return {
        "ts": datetime.now(timezone.utc).isoformat(),
        "lat": round(lat, 7), "lng": round(lng, 7),
        "speed": round(speed), "heading": round(course), "satellites": None,
        "ignition": None, "attributes": {},
    }, imei


async def handle(buf, writer, forward, log):
    imei = None
    while True:
        raw = await buf.until(b";")
        token = raw.decode("ascii", "ignore").strip().strip("\r\n").lstrip(",").strip()
        if not token:
            continue
        low = token.lower()
        if token.startswith("##"):
            imei = _imei(token) or imei
            log(f"coban IMEI={imei}")
            writer.write(b"LOAD"); await writer.drain()
        elif low.startswith("imei:"):
            fix, im = _decode(token)
            if im:
                imei = im
            if fix and imei:
                await asyncio.to_thread(forward, imei, [fix])
        elif token.isdigit():
            imei = token
            writer.write(b"ON"); await writer.drain()
