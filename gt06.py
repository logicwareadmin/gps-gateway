"""
GT06 / GT06N — protocolo de Concox / Jimi IoT (y muchos clones chinos). Es el
más extendido por volumen. Binario, con login (IMEI en BCD), heartbeat y
paquetes de ubicación; el server debe responder ACK (login/heartbeat) con CRC-ITU.

OJO: implementado según la especificación GT06. Los BITS DE SIGNO de lat/lng y
algunos sub-protocolos varían según firmware → VALIDAR con un equipo real
(en Chile lat es Sur / lng es Oeste, ambos negativos).
"""
import asyncio
import os
import struct
from datetime import datetime, timezone

NAME = "gt06"
DEBUG = os.environ.get("GATEWAY_DEBUG") in ("1", "true", "True")


def detect(head: bytes) -> bool:
    return head[:2] in (b"\x78\x78", b"\x79\x79")


def crc_itu(data: bytes) -> int:
    crc = 0xFFFF
    for b in data:
        crc ^= b
        for _ in range(8):
            crc = (crc >> 1) ^ 0x8408 if (crc & 1) else (crc >> 1)
    return (~crc) & 0xFFFF


def _ack(proto: int, serial: bytes) -> bytes:
    body = bytes([0x05, proto]) + serial          # len + protocol + serial
    return b"\x78\x78" + body + struct.pack(">H", crc_itu(body)) + b"\x0d\x0a"


def _decode_location(c: bytes):
    if len(c) < 18:
        return None
    try:
        ts = datetime(2000 + c[0], c[1], c[2], c[3], c[4], c[5], tzinfo=timezone.utc).isoformat()
    except ValueError:
        ts = datetime.now(timezone.utc).isoformat()
    sat = c[6] & 0x0F
    lat = struct.unpack(">I", c[7:11])[0] / 30000.0 / 60.0
    lng = struct.unpack(">I", c[11:15])[0] / 30000.0 / 60.0
    speed = c[15]
    cs = struct.unpack(">H", c[16:18])[0]
    course = cs & 0x03FF
    if not (cs & 0x0400):   # bit10: 1=Norte, 0=Sur  (Chile = Sur → negativo)
        lat = -lat
    if cs & 0x0800:         # bit11: 1=Oeste (Chile = Oeste → negativo)
        lng = -lng
    return {"ts": ts, "lat": round(lat, 7), "lng": round(lng, 7),
            "speed": speed, "heading": course, "satellites": sat,
            "ignition": None, "attributes": {}}


async def handle(buf, writer, forward, log):
    imei = None
    while True:
        start = await buf.exactly(2)
        if start == b"\x78\x78":
            ln = (await buf.exactly(1))[0]
        elif start == b"\x79\x79":
            ln = struct.unpack(">H", await buf.exactly(2))[0]
        else:
            if DEBUG:
                log(f"gt06 desync start={start.hex()} (esperaba 7878/7979)")
            break
        body = await buf.exactly(ln)      # protocol + content + serial(2) + crc(2)
        await buf.exactly(2)              # stop 0x0d0a
        if len(body) < 5:
            continue
        proto = body[0]
        content = body[1:-4]
        serial = body[-4:-2]
        if DEBUG:
            log(f"gt06 RX proto=0x{proto:02x} body={body.hex()}")

        if proto == 0x01:  # login
            imei = content[:8].hex()
            imei = imei[1:] if imei.startswith("0") else imei
            log(f"gt06 IMEI={imei}")
            writer.write(_ack(0x01, serial)); await writer.drain()
        elif proto in (0x13, 0x23):  # heartbeat / status
            writer.write(_ack(proto, serial)); await writer.drain()
        elif proto in (0x12, 0x22, 0x16, 0x26, 0xA0):  # ubicación
            fix = _decode_location(content)
            if DEBUG:
                log(f"gt06 decode -> {fix}")
            if fix and imei:
                await asyncio.to_thread(forward, imei, [fix])
            if proto in (0x16, 0x26):  # alarma: requiere ACK
                writer.write(_ack(proto, serial)); await writer.drain()
        elif proto == 0x8A:  # pedido de sincronización de hora
            writer.write(_ack(proto, serial)); await writer.drain()
        # otros protocolos: se ignoran
