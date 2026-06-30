"""
Emulador de equipo GPS — prueba TODA la cadena sin hardware.

Simula un equipo Teltonika (Codec 8) que se conecta al gateway, hace login con
un IMEI y manda posiciones que se MUEVEN (un círculo). Sirve para verificar, hoy
mismo y sin equipo real, que: gateway → /tracking/ingest → match por IMEI →
vehículo moviéndose en el mapa de Traza.

Pasos:
  1. En Traza: generá la API Key (Conexión GPS) y creá un vehículo en Equipos GPS
     con el IMEI de abajo (por defecto 356307042441013).
  2. Corré el gateway apuntando al backend:
        BACKEND_URL=https://api.logicware.cl  API_KEY=<la_api_key>  python gateway.py
  3. Corré este emulador (otra terminal):
        python emulator.py
  4. Abrí Traza → el vehículo aparece y se mueve en el mapa.

Env: GATEWAY_HOST (127.0.0.1) · GATEWAY_PORT (5027) · IMEI · INTERVAL (5) ·
     LAT/LNG (punto de partida, default Santiago centro)
"""
import math
import os
import socket
import struct
import time

HOST = os.environ.get("GATEWAY_HOST", "127.0.0.1")
PORT = int(os.environ.get("GATEWAY_PORT", "5027"))
IMEI = os.environ.get("IMEI", "356307042441013")
INTERVAL = float(os.environ.get("INTERVAL", "5"))
LAT0 = float(os.environ.get("LAT", "-33.4489"))
LNG0 = float(os.environ.get("LNG", "-70.6693"))


def crc16_ibm(data: bytes) -> int:
    crc = 0
    for b in data:
        crc ^= b
        for _ in range(8):
            crc = (crc >> 1) ^ 0xA001 if (crc & 1) else (crc >> 1)
    return crc & 0xFFFF


def avl_packet(lat: float, lng: float, speed: int, angle: int, ignition: bool) -> bytes:
    ts = int(time.time() * 1000)
    rec = struct.pack(">Q", ts) + b"\x01"            # timestamp + priority
    rec += struct.pack(">i", int(lng * 1e7))
    rec += struct.pack(">i", int(lat * 1e7))
    rec += struct.pack(">h", 500)                     # altitude
    rec += struct.pack(">H", angle % 360)             # angle
    rec += b"\x09"                                     # satellites
    rec += struct.pack(">H", speed)                   # speed
    # IO: event 0, total 2; N1 = [239 ignición, 66 voltaje]; N2/N4/N8 = 0
    rec += b"\x00\x02\x02" + bytes([239, 1 if ignition else 0]) + bytes([66, 13]) + b"\x00\x00\x00"
    data = b"\x08\x01" + rec + b"\x01"                # codec + num + record + num
    return b"\x00\x00\x00\x00" + struct.pack(">I", len(data)) + data + struct.pack(">I", crc16_ibm(data))


def main():
    print(f"conectando a {HOST}:{PORT} como IMEI={IMEI}…")
    s = socket.create_connection((HOST, PORT), timeout=10)
    imei_b = IMEI.encode()
    s.sendall(struct.pack(">H", len(imei_b)) + imei_b)   # login
    resp = s.recv(1)
    if resp != b"\x01":
        print(f"login rechazado (resp={resp!r})"); return
    print("login OK, enviando posiciones (Ctrl+C para parar)…")
    lat, lng, angle = LAT0, LNG0, 0
    try:
        while True:
            s.sendall(avl_packet(lat, lng, 40, angle, True))
            ack = int.from_bytes(s.recv(4), "big")
            print(f"  lat={lat:.5f} lng={lng:.5f} ang={angle:3d}  -> ack={ack}")
            angle = (angle + 20) % 360
            lat += 0.0009 * math.cos(math.radians(angle))
            lng += 0.0009 * math.sin(math.radians(angle))
            time.sleep(INTERVAL)
    except KeyboardInterrupt:
        print("\nfin.")
    finally:
        s.close()


if __name__ == "__main__":
    main()
