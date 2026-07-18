#!/usr/bin/env python3
"""
Persistent Tuya UDP discovery listener.
Listens on ports 6666/6667 for Tuya device broadcasts and logs
each newly discovered device to both stdout and a log file.

Runs indefinitely (or until killed) to catch devices as they're
activated throughout the day.

Deployed on the Pi 5 inside the HA container so it can use
SO_REUSEPORT alongside HA's own localtuya discovery.
"""
import socket
import json
import time
import select
import os
from hashlib import md5
from datetime import datetime

UDP_KEY = md5(b"yGAdlopoPVldABfn").digest()
LOG_FILE = "/config/tuya_discovery_log.txt"

def decrypt_udp(message):
    try:
        from cryptography.hazmat.backends import default_backend
        from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
        cipher = Cipher(algorithms.AES(UDP_KEY), modes.ECB(), default_backend())
        decryptor = cipher.decryptor()
        decrypted = decryptor.update(message) + decryptor.finalize()
        pad_len = decrypted[-1]
        if 0 < pad_len <= 16:
            decrypted = decrypted[:-pad_len]
        return decrypted.decode('utf-8', errors='replace')
    except Exception:
        return None

def log(msg):
    ts = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    line = f"[{ts}] {msg}"
    print(line, flush=True)
    try:
        with open(LOG_FILE, 'a') as f:
            f.write(line + '\n')
    except Exception:
        pass

# Known device names from HA config (gwId → friendly name)
KNOWN_DEVICES = {
    "131052773c61058a9f6b": "Laundry Room Light",
    "131052773c61058b5101": "Guest Room Light",
    "131052773c61058b58d1": "Powder Room Light",
    "131052773c61058b5cac": "Bathroom Light",
    "131052773c61058b5cb5": "Master Bedroom Fan Light",
    "131052773c61058b7d1b": "Basement Stair Light",
    "131052773c61058b9a1d": "Kitchen Fan",
    "131052773c61058ba305": "Patio Door Light",
    "131052773c61058b5f6b": "Laundry Room Light",
    "13105277c4dd57315edd": "Izaan's Bedroom light",
    "13105277c4dd573160d3": "Mina's Light",
    "50535623c44f33c2b17d": "Basement Lights",
    "15004183cc50e351f530": "Stair light (LED)",
    "3258883224a160340ee9": "Kitchen Light",
    "45142045c82b96c1f60f": "Foyer Light",
    "eb63d6fd2a642f6bf4r3iy": "Airbnb Infrared Heater",
    "eb799ab5470604253bnhi7": "Massage Room Heater",
    "eb68c40bc6f3c68e69ygrv": "Holiday Lights",
    "eb814f71bb6ded1077903w": "Outdoor Decoration SmartPlug",
    "eb9349f92e7f4acaaaccvg": "Cat Feeder",
    "eb9883b5def5e30cd1zakb": "Wasserstein Smart Floodlight 2",
    "ebb260bd73b0104270ypy1": "Family Room Blinds",
    "ebc2a243ded11aa5b3xbf8": "Dining Room Blinds",
    "ebcc9e5463ba321aa9b3ph": "Living Room Blinds",
    "ebc2cdd6b08d7469ealqcv": "Mina's Lamp",
    "ebc9634b3be58b35e2pdmn": "Salt Lamps",
    "ebf5071fb7d8c3303eha2l": "Living Room Floor Lamp",
    "eb3b9e64d0208b5c04gt4z": "Side Rain barrel",
    "eb228bea36b97bb1bcag3w": "Powder Room Mirror",
    "eb18e63205403c111dwphl": "Mina's Blinds",
    "eb1780072f130dadaci0cm": "Larissa's Garage Door",
    "888020473c6105e86199": "Master Bathroom",
    "888020473c6105e8b1ab": "Family Room",
    "888020473c6105e95c64": "Island Light",
    "66483875c4dd571483e4": "Back Hallway Light Main",
    "66483875c4dd5714a875": "Back Hallway Light",
    "67100068483fda16c660": "Office Heater",
    "6715478070039fce0412": "Garage Light Switch",
}

# Configured IPs (so we can flag when a device has moved)
CONFIGURED_IPS = {
    "131052773c61058a9f6b": "192.168.0.69",
    "131052773c61058b5101": "192.168.0.41",
    "131052773c61058b58d1": "192.168.0.22",
    "131052773c61058b5cac": "192.168.0.73",
    "131052773c61058b5cb5": "192.168.0.70",
    "131052773c61058b7d1b": "192.168.0.88",
    "131052773c61058b9a1d": "192.168.0.57",
    "131052773c61058ba305": "192.168.0.65",
    "131052773c61058b5f6b": "192.168.0.69",
    "13105277c4dd57315edd": "192.168.0.51",
    "13105277c4dd573160d3": "192.168.0.63",
    "50535623c44f33c2b17d": "192.168.0.25",
    "15004183cc50e351f530": "192.168.0.29",
    "3258883224a160340ee9": "192.168.0.66",
    "45142045c82b96c1f60f": "192.168.0.94",
    "eb63d6fd2a642f6bf4r3iy": "192.168.0.49",
    "eb799ab5470604253bnhi7": "192.168.0.37",
    "eb68c40bc6f3c68e69ygrv": "192.168.0.109",
    "eb814f71bb6ded1077903w": "192.168.0.117",
    "eb9349f92e7f4acaaaccvg": "192.168.0.111",
    "eb9883b5def5e30cd1zakb": "192.168.0.105",
    "ebb260bd73b0104270ypy1": "192.168.0.27",
    "ebc2a243ded11aa5b3xbf8": "192.168.0.27",
    "ebcc9e5463ba321aa9b3ph": "192.168.0.27",
    "ebc2cdd6b08d7469ealqcv": "192.168.0.93",
    "ebc9634b3be58b35e2pdmn": "192.168.0.98",
    "ebf5071fb7d8c3303eha2l": "192.168.0.52",
    "eb3b9e64d0208b5c04gt4z": "192.168.0.53",
    "eb228bea36b97bb1bcag3w": "192.168.0.48",
    "eb18e63205403c111dwphl": "192.168.0.27",
    "eb1780072f130dadaci0cm": "192.168.0.21",
    "888020473c6105e86199": "192.168.0.34",
    "888020473c6105e8b1ab": "192.168.0.76",
    "888020473c6105e95c64": "192.168.0.85",
    "66483875c4dd571483e4": "192.168.0.95",
    "66483875c4dd5714a875": "192.168.0.127",
    "67100068483fda16c660": "192.168.0.83",
    "6715478070039fce0412": "192.168.0.175",
}

# Set up sockets
sock6666 = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
sock6666.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
try:
    sock6666.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEPORT, 1)
except AttributeError:
    pass
sock6666.bind(('0.0.0.0', 6666))
sock6666.settimeout(1)

sock6667 = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
sock6667.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
try:
    sock6667.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEPORT, 1)
except AttributeError:
    pass
sock6667.bind(('0.0.0.0', 6667))
sock6667.settimeout(1)

log("=" * 70)
log("Tuya UDP Discovery Listener started")
log(f"Listening on UDP 6666 + 6667 (indefinite)")
log(f"Logging to {LOG_FILE}")
log(f"Known devices in config: {len(KNOWN_DEVICES)}")
log(f"Devices at wrong IPs (need discovery): {sum(1 for gid, ip in CONFIGURED_IPS.items() if gid in KNOWN_DEVICES)}")
log("=" * 70)

devices_seen = {}
start = time.time()
last_report = start
last_summary = start

while True:
    try:
        readable, _, _ = select.select([sock6666, sock6667], [], [], 1.0)
        for sock in readable:
            try:
                data, addr = sock.recvfrom(4096)
                ip = addr[0]
                if len(data) <= 28:
                    continue

                payload = data[20:-8]

                # Try encrypted first
                decrypted = decrypt_udp(payload)
                dev = None
                if decrypted:
                    try:
                        dev = json.loads(decrypted)
                    except json.JSONDecodeError:
                        pass

                # Try plain
                if not dev:
                    try:
                        text = payload.decode('utf-8', errors='replace').rstrip('\x00')
                        dev = json.loads(text)
                    except (json.JSONDecodeError, UnicodeDecodeError):
                        continue

                if not dev:
                    continue

                gw_id = dev.get('gwId', dev.get('id', '?'))
                product = dev.get('productKey', '?')
                version = dev.get('version', '?')

                if gw_id not in devices_seen:
                    name = KNOWN_DEVICES.get(gw_id, 'UNKNOWN DEVICE')
                    configured_ip = CONFIGURED_IPS.get(gw_id, '?')

                    if gw_id in KNOWN_DEVICES:
                        if ip != configured_ip:
                            status = f"🔄 IP CHANGED (was {configured_ip})"
                        else:
                            status = "✅ IP unchanged"
                    else:
                        status = "🆕 NEW DEVICE (not in HA config)"

                    log(f"DISCOVERED: {name} | gwId={gw_id} | IP={ip} | {status} | Product={product} | v{version}")

                    devices_seen[gw_id] = {
                        'ip': ip,
                        'name': name,
                        'product': product,
                        'version': version,
                        'configured_ip': configured_ip,
                        'first_seen': datetime.now().isoformat(),
                    }

                    # Write JSON snapshot
                    try:
                        with open('/config/tuya_discovery_devices.json', 'w') as f:
                            json.dump(devices_seen, f, indent=2)
                    except Exception:
                        pass

            except socket.timeout:
                pass
            except Exception as e:
                log(f"ERROR processing packet: {e}")

        # Hourly summary
        now = time.time()
        if now - last_summary > 3600:
            log(f"--- Hourly summary: {len(devices_seen)} unique devices discovered so far ---")
            for gw_id, info in sorted(devices_seen.items(), key=lambda x: x[1]['name']):
                name = info['name']
                ip = info['ip']
                configured = info.get('configured_ip', '?')
                if ip != configured and gw_id in CONFIGURED_IPS:
                    log(f"  🔄 {name}: now at {ip} (was {configured})")
                elif gw_id not in KNOWN_DEVICES:
                    log(f"  🆕 {name} ({gw_id}): at {ip}")
                else:
                    log(f"  ✅ {name}: at {ip}")
            last_summary = now

    except KeyboardInterrupt:
        log("Listener stopped by user (Ctrl+C)")
        break
    except Exception as e:
        log(f"FATAL: {e}")
        time.sleep(5)

sock6666.close()
sock6667.close()
