"""
Teltonika — Codec 8 / 8E (FMB/FMC…). El M2M de referencia en Chile/LatAm:
SIM de datos + GPS + lectura del CAN/OBD (los IO elements = telemetría).

Login: [2 bytes largo][IMEI ASCII] -> server responde 0x01 (aceptar).
Datos: paquetes AVL -> server responde uint32 = registros aceptados (ACK).
VALIDADO contra la especificación Codec 8/8E.
"""
import asyncio
import struct
from datetime import datetime, timezone

NAME = "teltonika"


def detect(head: bytes) -> bool:
    # Login Teltonika: 2 bytes de largo (IMEI 15-17) + dígitos ASCII.
    if len(head) < 4:
        return False
    ln = (head[0] << 8) | head[1]
    if ln not in (15, 16, 17):
        return False
    body = head[2:2 + ln]
    return body == b"" or body.isdigit() or head[2:4].isdigit()


def parse_imei(data: bytes):
    if len(data) < 2:
        return None
    ln = struct.unpack(">H", data[:2])[0]
    if ln <= 0 or len(data) < 2 + ln:
        return None
    try:
        return data[2:2 + ln].decode("ascii", "ignore").strip()
    except Exception:
        return None


def _read_io(buf: bytes, off: int, codec8e: bool):
    io = {}

    def rid(o):
        return (struct.unpack(">H", buf[o:o + 2])[0], o + 2) if codec8e else (buf[o], o + 1)

    def rcount(o):
        return (struct.unpack(">H", buf[o:o + 2])[0], o + 2) if codec8e else (buf[o], o + 1)

    event_id, off = rid(off)
    _total, off = rcount(off)
    for size, fmt in ((1, ">B"), (2, ">H"), (4, ">I"), (8, ">Q")):
        n, off = rcount(off)
        for _ in range(n):
            iid, off = rid(off)
            io[iid] = struct.unpack(fmt, buf[off:off + size])[0]
            off += size
    if codec8e:
        nx, off = rcount(off)
        for _ in range(nx):
            iid, off = rid(off)
            vlen = struct.unpack(">H", buf[off:off + 2])[0]
            off += 2
            io[iid] = buf[off:off + vlen].hex()
            off += vlen
    return io, event_id, off


def parse_avl(packet: bytes):
    if len(packet) < 10 or packet[:4] != b"\x00\x00\x00\x00":
        return None
    codec = packet[8]
    if codec not in (0x08, 0x8E):
        return None
    codec8e = codec == 0x8E
    num = packet[9]
    off = 10
    fixes = []
    try:
        for _ in range(num):
            ts_ms = struct.unpack(">Q", packet[off:off + 8])[0]; off += 8
            off += 1  # priority
            lon = struct.unpack(">i", packet[off:off + 4])[0] / 1e7; off += 4
            lat = struct.unpack(">i", packet[off:off + 4])[0] / 1e7; off += 4
            alt = struct.unpack(">h", packet[off:off + 2])[0]; off += 2
            angle = struct.unpack(">H", packet[off:off + 2])[0]; off += 2
            sats = packet[off]; off += 1
            speed = struct.unpack(">H", packet[off:off + 2])[0]; off += 2
            io, _ev, off = _read_io(packet, off, codec8e)
            fixes.append({
                "ts": datetime.fromtimestamp(ts_ms / 1000, tz=timezone.utc).isoformat(),
                "lat": round(lat, 7), "lng": round(lon, 7),
                "altitude": alt, "heading": angle, "satellites": sats, "speed": speed,
                "ignition": bool(io.get(239)) if 239 in io else None,
                "attributes": {str(k): v for k, v in io.items()},
            })
    except (struct.error, IndexError):
        return None
    return num, fixes


async def handle(buf, writer, forward, log):
    raw = await buf.exactly(2)
    ln = (raw[0] << 8) | raw[1]
    imei = (await buf.exactly(ln)).decode("ascii", "ignore").strip()
    if not imei.isdigit():
        writer.write(b"\x00"); await writer.drain(); return
    log(f"teltonika IMEI={imei}")
    writer.write(b"\x01"); await writer.drain()  # aceptar login
    while True:
        hdr = await buf.exactly(8)  # preámbulo(4) + data_len(4)
        if hdr[:4] != b"\x00\x00\x00\x00":
            break
        dlen = struct.unpack(">I", hdr[4:8])[0]
        if dlen <= 0 or dlen > 1_000_000:
            break
        packet = hdr + await buf.exactly(dlen + 4)  # + CRC
        res = parse_avl(packet)
        if res:
            num, fixes = res
            await asyncio.to_thread(forward, imei, fixes)
            writer.write(struct.pack(">I", num)); await writer.drain()
        else:
            writer.write(struct.pack(">I", 0)); await writer.drain()
