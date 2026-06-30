# GPS Gateway — Traza / LogicWare

Recibe la conexión **directa** de equipos GPS/M2M (sin pasar por Flespi/Traccar ni
ninguna plataforma de terceros) y reenvía sus datos a LogicWare.

```
[ Equipo GPS/M2M ]  --TCP (protocolo binario)-->  [ gps-gateway ]  --HTTP POST-->  [ backend /tracking/ingest ]
   (SIM de datos)        Codec 8 / 8E              (este servicio)     X-API-Key        (DO App Platform)
```

El equipo "marca a casa" por TCP a la **IP:puerto** de este gateway. El gateway
parsea el protocolo, extrae **posición + telemetría del CAN** (combustible, RPM,
temp, etc. como *IO elements*) y lo manda a la puerta única de ingesta del backend.

- **Auto-detección de protocolo:** enchufás cualquier equipo y el gateway reconoce
  solo cuál es (por los primeros bytes). No hay que pre-configurar nada.
- **El match equipo→vehículo** es por **IMEI** = `tracker_device_id` del vehículo
  (lo cargás en *Equipos GPS* del standalone).

## Protocolos soportados
| Protocolo | Equipos típicos | Estado |
|---|---|---|
| **Teltonika** (Codec 8 / 8E) | FMB920, FMC130, FMC640… (M2M/CAN) | ✅ Según especificación |
| **GT06 / GT06N** | Concox, **Jimi IoT (VL103…)** y clones | ⚠️ Según especificación — validar con equipo real |
| **Queclink** | GV serie (GV300, GV320…) | ⚠️ Según especificación — validar con equipo real |
| **Coban / GPS103** | TK103 y clones económicos | ⚠️ Según especificación — validar con equipo real |

> Teltonika es el más sólido (spec clara y es el M2M con CAN/telemetría). Los demás
> están implementados por especificación pero **se confirman en 5 min** con un equipo
> real (en binarios como GT06 los bits de signo de lat/lng pueden variar por firmware).
> Otros (Ruptela, Suntech, Calamp) se agregan fácil — ver el final.

## Por qué va aparte (no en DO App Platform)
DO App Platform es **solo HTTP**: no abre puertos TCP arbitrarios ni mantiene
sockets persistentes. Por eso el gateway corre en un **VPS chico con IP fija**
(un Droplet de ~5–6 USD/mes) con el puerto TCP abierto. El backend sigue donde está.

## Requisitos previos
1. Un **Droplet** (Ubuntu) con IP pública fija y el puerto TCP abierto (default `5027`).
2. La **API Key** de la empresa en LogicWare (`Company.api_key`).
3. En LogicWare, el vehículo con su **IMEI** cargado en *Equipos GPS* (`tracker_device_id`).

## Correr
```bash
cd gps-gateway
pip install -r requirements.txt

export BACKEND_URL="https://api.logicware.cl"   # base del backend
export API_KEY="<api_key_de_la_empresa>"
export GATEWAY_PORT=5027                          # opcional (default 5027)
export PROTOCOL=auto                               # opcional (auto | teltonika | gt06 | queclink | coban)

python gateway.py
```

### Como servicio (systemd) en el Droplet
```ini
# /etc/systemd/system/gps-gateway.service
[Unit]
Description=GPS Gateway Traza
After=network.target

[Service]
WorkingDirectory=/opt/gps-gateway
Environment=BACKEND_URL=https://api.logicware.cl
Environment=API_KEY=__API_KEY__
Environment=GATEWAY_PORT=5027
ExecStart=/usr/bin/python3 gateway.py
Restart=always

[Install]
WantedBy=multi-user.target
```
```bash
sudo ufw allow 5027/tcp
sudo systemctl enable --now gps-gateway
```

## Deploy con Docker (1 comando — recomendado)
En el Droplet (con Docker instalado):
```bash
cp .env.example .env       # editá BACKEND_URL + API_KEY
docker compose up -d --build
sudo ufw allow 5027/tcp
```
Queda escuchando el puerto 5027/TCP y **reinicia solo**. Logs: `docker compose logs -f`.
Para actualizar: `git pull && docker compose up -d --build`.

## Probar SIN hardware (emulador)
`emulator.py` simula un equipo Teltonika que se mueve, para validar toda la cadena
(gateway → ingesta → mapa) hoy, sin equipo real:
1. En Traza: generá la **API Key** (Conexión GPS) y creá un vehículo en **Equipos GPS**
   con el IMEI `356307042441013` (o el que pongas en `IMEI=`).
2. Corré el gateway apuntando al backend real:
   ```bash
   BACKEND_URL=https://api.logicware.cl API_KEY=<api_key> python gateway.py
   ```
3. En otra terminal: `python emulator.py`
4. Abrí Traza → el vehículo aparece y se **mueve** en el mapa.

Sirve para confirmar que el sistema está listo antes de tener el equipo físico.

## Capturar / validar un equipo real (debug)
Para confirmar y afinar el parser con un equipo en mano (ej. **Jimi IoT VL103 → GT06**):
```bash
GATEWAY_DEBUG=1 BACKEND_URL=https://api.logicware.cl API_KEY=<key> python gateway.py
```
Loguea el **hex crudo** de cada paquete + lo que decodifica. Conectá el equipo,
capturá unos minutos y pasá el log → con eso se ajustan al milímetro el layout y
los **signos de lat/lng** (Chile = Sur/Oeste).

### Jimi IoT / Concox (VL103): SMS de configuración
- **APN:** `APN,<apn>#` (o `APN,<apn>,<user>,<pass>#`)
- **Servidor:** `SERVER,1,<ip_o_dominio>,<puerto>,0#`  (el `0` final = **TCP**)
- IMEI del equipo de la foto: `869066064832661` → cargalo en *Equipos GPS*.

> Los comandos exactos dependen del firmware (algunos usan `IP,`/`ADMINIP,` o piden
> password `123456`). Si el manual del VL103 difiere, pasámelo y lo ajusto.

## Configurar el equipo (Teltonika)
Por **Teltonika Configurator** (USB) o por **SMS**, hay que setear:
- **APN** de la SIM M2M (nombre, y user/pass si aplica).
- **Servidor**: la **IP pública del Droplet** + el **puerto** (`5027`) + modo **TCP**.
- **Protocolo de datos: Codec 8 Extended** (recomendado, trae los IO del CAN).

> Los comandos SMS exactos (números de parámetro) dependen del **modelo** (FMB920,
> FMC130, FMC640…). Pasame el modelo y te dejo el SMS exacto. Lo genérico:
> APN → servidor (IP/puerto/TCP) → Codec 8E.

## Telemetría (IO elements)
El gateway reenvía los IO crudos en `attributes` (`{ "<io_id>": valor }`). El
mapeo de cada IO ID a campo (combustible %, RPM, temp, AdBlue, TPMS, voltaje…)
**depende de la configuración del equipo** y se resuelve en el backend. IO comunes
de Teltonika: `239`=ignición, `240`=movimiento, `66`=voltaje externo, `67`=batería
interna; los del **CAN** (combustible/RPM/temp) según el adaptador/modelo.

**Pendiente backend:** leer esos IO de `attributes` en `/tracking/ingest` y
guardarlos como telemetría real → ahí el panel de *Indicadores* deja de ser
simulado. (Se hace cuando definamos el modelo y veamos qué IO IDs manda.)

## Agregar otro protocolo (Ruptela, Suntech, Calamp…)
Cada protocolo es un módulo con esta interfaz:
```python
NAME = "miproto"
def detect(head: bytes) -> bool: ...          # ¿los primeros bytes son de este protocolo?
async def handle(buf, writer, forward, log):  # login + framing + parseo + ACK
    # buf.exactly(n) / buf.until(delim) para leer; writer.write(...) para responder.
    # await asyncio.to_thread(forward, imei, fixes) para mandar al backend.
    ...
```
Cada `fix` es `{ts, lat, lng, speed, heading, ignition, attributes}`.
1. Crear `miproto.py` con `NAME`, `detect`, `handle`.
2. Sumarlo en `gateway.py` → `PROTOCOLS = [teltonika, gt06, queclink, coban, miproto]`.
3. Listo: la auto-detección lo toma. (O forzarlo con `PROTOCOL=miproto`.)
