import math
import socket
import threading
import time
import queue
import traceback
import tkinter as tk
from tkinter import ttk, messagebox

from pyrtcm import RTCMReader, VALCKSUM

APP_TITLE = "RTCM3 TCP Debugger"
WATCHDOG_NO_DATA_SEC = 3.0
WATCHDOG_STALE_MSG_SEC = 10.0
WATCHDOG_MSM_MISSING_SEC = 5.0
BASE_POSITION_TYPES = {"1005", "1006"}
MSM_TYPES = {
    "1074", "1075", "1076", "1077",
    "1084", "1085", "1086", "1087",
    "1094", "1095", "1096", "1097",
    "1114", "1115", "1116", "1117",
    "1124", "1125", "1126", "1127",
}


def ecef_to_geodetic(x: float, y: float, z: float):
    """Convert ECEF XYZ (meters) to WGS84 geodetic lat/lon/height."""
    a = 6378137.0
    f = 1 / 298.257223563
    e2 = f * (2 - f)
    b = a * (1 - f)
    ep2 = (a * a - b * b) / (b * b)

    p = math.hypot(x, y)
    if p == 0:
        lat = math.copysign(math.pi / 2, z)
        lon = 0.0
        h = abs(z) - b
        return math.degrees(lat), math.degrees(lon), h

    th = math.atan2(a * z, b * p)
    lon = math.atan2(y, x)
    lat = math.atan2(
        z + ep2 * b * math.sin(th) ** 3,
        p - e2 * a * math.cos(th) ** 3,
    )
    n = a / math.sqrt(1 - e2 * math.sin(lat) ** 2)
    h = p / math.cos(lat) - n

    for _ in range(5):
        n = a / math.sqrt(1 - e2 * math.sin(lat) ** 2)
        h = p / math.cos(lat) - n
        lat = math.atan2(z, p * (1 - e2 * n / (n + h)))

    return math.degrees(lat), math.degrees(lon), h


class RTCMStreamParser:
    """Very small RTCM3 framer: finds 0xD3, reads the RTCM 10-bit payload length, yields whole frames."""

    def __init__(self):
        self.buffer = bytearray()
        self.skipped_noise_bytes = 0

    def feed(self, data: bytes):
        self.buffer.extend(data)
        frames = []
        while True:
            if len(self.buffer) < 3:
                break

            if self.buffer[0] != 0xD3:
                idx = self.buffer.find(b"\xD3")
                if idx == -1:
                    self.skipped_noise_bytes += len(self.buffer)
                    self.buffer.clear()
                    break
                self.skipped_noise_bytes += idx
                del self.buffer[:idx]
                if len(self.buffer) < 3:
                    break

            payload_len = ((self.buffer[1] & 0x03) << 8) | self.buffer[2]
            frame_len = 3 + payload_len + 3

            if len(self.buffer) < frame_len:
                break

            frame = bytes(self.buffer[:frame_len])
            del self.buffer[:frame_len]
            frames.append(frame)

        return frames


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title(APP_TITLE)
        self.geometry("1180x760")
        self.minsize(1040, 660)

        self.event_queue = queue.Queue()
        self.stop_event = threading.Event()
        self.worker = None
        self.sock = None

        self.total_frames = 0
        self.invalid_frames = 0
        self.non_rtcm_bytes = 0
        self.total_received_bytes = 0
        self.last_valid_ts = None
        self.last_valid_epoch = None
        self.last_rx_epoch = None
        self.last_error = "-"
        self.stats = {}
        self.last_base_info = None
        self.last_msm_info = None

        self._build_ui()
        self.after(100, self._process_queue)
        self.after(500, self._refresh_watchdog)
        self.protocol("WM_DELETE_WINDOW", self.on_close)

    def _build_ui(self):
        top = ttk.Frame(self, padding=10)
        top.pack(fill="x")

        ttk.Label(top, text="IP:").grid(row=0, column=0, sticky="w")
        self.ip_var = tk.StringVar(value="127.0.0.1")
        ttk.Entry(top, textvariable=self.ip_var, width=18).grid(row=0, column=1, padx=(4, 12))

        ttk.Label(top, text="Port:").grid(row=0, column=2, sticky="w")
        self.port_var = tk.StringVar(value="5000")
        ttk.Entry(top, textvariable=self.port_var, width=10).grid(row=0, column=3, padx=(4, 12))

        self.connect_btn = ttk.Button(top, text="Connect", command=self.toggle_connection)
        self.connect_btn.grid(row=0, column=4, padx=(0, 8))

        self.clear_btn = ttk.Button(top, text="Clear stats", command=self.clear_stats)
        self.clear_btn.grid(row=0, column=5)

        self.status_var = tk.StringVar(value="Disconnected")
        ttk.Label(top, textvariable=self.status_var).grid(row=0, column=6, sticky="w", padx=(16, 0))
        top.columnconfigure(6, weight=1)

        summary = ttk.LabelFrame(self, text="Stream status", padding=10)
        summary.pack(fill="x", padx=10, pady=(0, 10))

        self.summary_var = tk.StringVar(value=self._summary_text())
        ttk.Label(summary, textvariable=self.summary_var, justify="left").pack(anchor="w")

        health = ttk.LabelFrame(self, text="Health checks", padding=10)
        health.pack(fill="x", padx=10, pady=(0, 10))

        self.health_var = tk.StringVar(value=self._health_text())
        ttk.Label(health, textvariable=self.health_var, justify="left").pack(anchor="w")

        main = ttk.PanedWindow(self, orient="horizontal")
        main.pack(fill="both", expand=True, padx=10, pady=(0, 10))

        left = ttk.Frame(main)
        right = ttk.Frame(main)
        main.add(left, weight=3)
        main.add(right, weight=2)

        columns = ("msgtype", "count", "last_seen", "detail")
        self.tree = ttk.Treeview(left, columns=columns, show="headings", height=20)
        self.tree.heading("msgtype", text="RTCM type")
        self.tree.heading("count", text="Count")
        self.tree.heading("last_seen", text="Last valid")
        self.tree.heading("detail", text="Last decoded detail")
        self.tree.column("msgtype", width=110, anchor="w")
        self.tree.column("count", width=80, anchor="e")
        self.tree.column("last_seen", width=160, anchor="w")
        self.tree.column("detail", width=560, anchor="w")
        self.tree.pack(side="left", fill="both", expand=True)

        yscroll = ttk.Scrollbar(left, orient="vertical", command=self.tree.yview)
        yscroll.pack(side="right", fill="y")
        self.tree.configure(yscrollcommand=yscroll.set)

        detail_box = ttk.LabelFrame(right, text="Selected message detail", padding=10)
        detail_box.pack(fill="both", expand=True)

        self.detail_text = tk.Text(detail_box, wrap="word", height=16)
        self.detail_text.pack(fill="both", expand=True)
        self.detail_text.configure(state="disabled")

        log_box = ttk.LabelFrame(right, text="Event log", padding=10)
        log_box.pack(fill="both", expand=True, pady=(10, 0))

        self.log_text = tk.Text(log_box, wrap="word", height=12)
        self.log_text.pack(fill="both", expand=True)
        self.log_text.configure(state="disabled")

        self.tree.bind("<<TreeviewSelect>>", self.on_tree_select)

    def _validity_percent(self):
        considered = self.total_frames + self.invalid_frames
        if considered == 0:
            return 0.0
        return 100.0 * self.total_frames / considered

    def _connected(self):
        return self.worker is not None and self.worker.is_alive() and not self.stop_event.is_set()

    def _stream_watchdog_status(self):
        if not self._connected():
            return "DISCONNECTED"
        if self.last_rx_epoch is None:
            return "WAITING FOR DATA"
        age = time.time() - self.last_rx_epoch
        if age > WATCHDOG_NO_DATA_SEC:
            return f"STREAM DEAD ({age:.1f}s without TCP data)"
        return f"STREAM OK ({age:.1f}s since last TCP data)"

    def _msm_status(self):
        if self.last_msm_info is None:
            return "MISSING"
        age = time.time() - self.last_msm_info["epoch"]
        if age > WATCHDOG_MSM_MISSING_SEC:
            return f"STALE ({age:.1f}s since last MSM)"
        return f"OK ({self.last_msm_info['identity']} {age:.1f}s ago)"

    def _base_status(self):
        if self.last_base_info is None:
            return "MISSING"
        age = time.time() - self.last_base_info["epoch"]
        if age > WATCHDOG_STALE_MSG_SEC:
            return f"STALE ({age:.1f}s since last {self.last_base_info['identity']})"
        return f"OK ({self.last_base_info['identity']} {age:.1f}s ago)"

    def _health_text(self):
        base_line = "Base position: MISSING"
        if self.last_base_info:
            base_line = (
                f"Base position: {self._base_status()}\n"
                f"  Station ID: {self.last_base_info.get('station_id', '-')}\n"
                f"  Lat/Lon/H: {self.last_base_info['lat']:.9f}, {self.last_base_info['lon']:.9f}, {self.last_base_info['h']:.3f} m"
            )

        msm_line = "MSM corrections: MISSING"
        if self.last_msm_info:
            msm_line = (
                f"MSM corrections: {self._msm_status()}\n"
                f"  Station ID: {self.last_msm_info.get('station_id', '-')} | "
                f"Sat: {self.last_msm_info.get('nsat', '-')} | Sig: {self.last_msm_info.get('nsig', '-')} | Cells: {self.last_msm_info.get('ncell', '-')}"
            )

        return (
            f"Watchdog: {self._stream_watchdog_status()}\n"
            f"RTCM validity: {self._validity_percent():.2f}%\n"
            f"{base_line}\n"
            f"{msm_line}"
        )

    def _summary_text(self):
        last_valid = self.last_valid_ts or "-"
        last_valid_age = "-"
        if self.last_valid_epoch is not None:
            last_valid_age = f"{time.time() - self.last_valid_epoch:.1f}s ago"
        return (
            f"Total valid RTCM frames: {self.total_frames}\n"
            f"Invalid frames (CRC/parse): {self.invalid_frames}\n"
            f"RTCM validity: {self._validity_percent():.2f}%\n"
            f"Non-RTCM bytes skipped: {self.non_rtcm_bytes}\n"
            f"Total TCP bytes received: {self.total_received_bytes}\n"
            f"Last valid frame: {last_valid} ({last_valid_age})\n"
            f"Last error: {self.last_error}"
        )

    def _refresh_health_labels(self):
        self.summary_var.set(self._summary_text())
        self.health_var.set(self._health_text())

    def set_log(self, text: str):
        self.log_text.configure(state="normal")
        self.log_text.insert("end", text + "\n")
        self.log_text.see("end")
        self.log_text.configure(state="disabled")

    def set_detail(self, text: str):
        self.detail_text.configure(state="normal")
        self.detail_text.delete("1.0", "end")
        self.detail_text.insert("1.0", text)
        self.detail_text.configure(state="disabled")

    def on_tree_select(self, _event=None):
        selection = self.tree.selection()
        if not selection:
            return
        key = selection[0]
        info = self.stats.get(key)
        if not info:
            return
        text = (
            f"Message type: {key}\n"
            f"Count: {info['count']}\n"
            f"Last valid: {info['last_seen']}\n\n"
            f"Last decoded detail:\n{info['last_detail']}"
        )
        self.set_detail(text)

    def clear_stats(self):
        self.total_frames = 0
        self.invalid_frames = 0
        self.non_rtcm_bytes = 0
        self.total_received_bytes = 0
        self.last_valid_ts = None
        self.last_valid_epoch = None
        self.last_rx_epoch = None
        self.last_error = "-"
        self.last_base_info = None
        self.last_msm_info = None
        self.stats.clear()
        for item in self.tree.get_children():
            self.tree.delete(item)
        self._refresh_health_labels()
        self.set_detail("")
        self.set_log("Stats cleared.")

    def toggle_connection(self):
        if self.worker and self.worker.is_alive():
            self.disconnect()
        else:
            self.connect()

    def connect(self):
        host = self.ip_var.get().strip()
        port_str = self.port_var.get().strip()
        try:
            port = int(port_str)
        except ValueError:
            messagebox.showerror(APP_TITLE, "Port must be an integer.")
            return

        self.stop_event.clear()
        self.worker = threading.Thread(target=self._worker_main, args=(host, port), daemon=True)
        self.worker.start()
        self.connect_btn.configure(text="Disconnect")
        self.status_var.set(f"Connecting to {host}:{port}...")
        self.set_log(f"Connecting to {host}:{port}")

    def disconnect(self):
        self.stop_event.set()
        if self.sock:
            try:
                self.sock.shutdown(socket.SHUT_RDWR)
            except Exception:
                pass
            try:
                self.sock.close()
            except Exception:
                pass
            self.sock = None
        self.connect_btn.configure(text="Connect")
        self.status_var.set("Disconnected")
        self._refresh_health_labels()
        self.set_log("Disconnected.")

    def on_close(self):
        self.disconnect()
        self.destroy()

    def _queue(self, kind, payload=None):
        self.event_queue.put((kind, payload))

    def _worker_main(self, host: str, port: int):
        parser = RTCMStreamParser()
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self.sock = sock
            sock.settimeout(2.0)
            sock.connect((host, port))
            sock.settimeout(1.0)
            self._queue("status", f"Connected to {host}:{port}")
            self._queue("log", f"Connected to {host}:{port}")

            while not self.stop_event.is_set():
                try:
                    chunk = sock.recv(4096)
                    if not chunk:
                        self._queue("log", "Remote side closed the connection.")
                        self._queue("status", "Disconnected (remote closed)")
                        break
                except socket.timeout:
                    continue

                self._queue("rx", len(chunk))
                before_noise = parser.skipped_noise_bytes
                frames = parser.feed(chunk)
                skipped = parser.skipped_noise_bytes - before_noise
                if skipped:
                    self._queue("noise", skipped)
                    self._queue("log", f"Skipped {skipped} non-RTCM byte(s) while searching for 0xD3 preamble.")

                for frame in frames:
                    try:
                        msg = RTCMReader.parse(frame, validate=VALCKSUM)
                        self._queue("message", self._extract_message_info(msg, frame))
                    except Exception as err:
                        self._queue("invalid", f"Invalid RTCM frame: {err}")

        except Exception as err:
            self._queue("status", f"Connection error: {err}")
            self._queue("log", f"Connection error: {err}")
        finally:
            try:
                if self.sock:
                    self.sock.close()
            except Exception:
                pass
            self.sock = None
            self._queue("disconnected")

    def _extract_message_info(self, msg, frame: bytes):
        identity = str(getattr(msg, "identity", "UNKNOWN"))
        now_epoch = time.time()
        now = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(now_epoch))

        detail, parsed = self.describe_message(msg, len(frame))
        raw_repr = repr(msg)
        return {
            "identity": identity,
            "timestamp": now,
            "epoch": now_epoch,
            "detail": detail,
            "parsed": parsed,
            "raw_repr": raw_repr,
        }

    def describe_message(self, msg, frame_len: int):
        ident = str(getattr(msg, "identity", "UNKNOWN"))
        base = [f"Frame length: {frame_len} bytes"]
        parsed = {}

        try:
            if ident == "1005":
                x = getattr(msg, "DF025", None)
                y = getattr(msg, "DF026", None)
                z = getattr(msg, "DF027", None)
                station = getattr(msg, "DF003", None)
                if None not in (x, y, z):
                    lat, lon, h = ecef_to_geodetic(float(x), float(y), float(z))
                    parsed.update({
                        "station_id": station,
                        "ecef_x": float(x),
                        "ecef_y": float(y),
                        "ecef_z": float(z),
                        "lat": lat,
                        "lon": lon,
                        "h": h,
                    })
                    base.extend([
                        f"Reference station ID: {station}",
                        f"ECEF X: {float(x):.4f} m",
                        f"ECEF Y: {float(y):.4f} m",
                        f"ECEF Z: {float(z):.4f} m",
                        f"Latitude: {lat:.9f}°",
                        f"Longitude: {lon:.9f}°",
                        f"Ellipsoidal height (approx.): {h:.3f} m",
                    ])
            elif ident == "1006":
                x = getattr(msg, "DF025", None)
                y = getattr(msg, "DF026", None)
                z = getattr(msg, "DF027", None)
                ant_h = getattr(msg, "DF028", None)
                station = getattr(msg, "DF003", None)
                if None not in (x, y, z):
                    lat, lon, h = ecef_to_geodetic(float(x), float(y), float(z))
                    parsed.update({
                        "station_id": station,
                        "ecef_x": float(x),
                        "ecef_y": float(y),
                        "ecef_z": float(z),
                        "lat": lat,
                        "lon": lon,
                        "h": h,
                        "antenna_height": ant_h,
                    })
                    base.extend([
                        f"Reference station ID: {station}",
                        f"Antenna height field: {ant_h}",
                        f"ECEF X: {float(x):.4f} m",
                        f"ECEF Y: {float(y):.4f} m",
                        f"ECEF Z: {float(z):.4f} m",
                        f"Latitude: {lat:.9f}°",
                        f"Longitude: {lon:.9f}°",
                        f"Ellipsoidal height (approx.): {h:.3f} m",
                    ])
            elif ident in MSM_TYPES:
                station = getattr(msg, "DF003", None)
                tow = getattr(msg, "DF248", None)
                nsat = getattr(msg, "NSat", None)
                nsig = getattr(msg, "NSig", None)
                ncell = getattr(msg, "NCell", None)
                parsed.update({
                    "station_id": station,
                    "tow": tow,
                    "nsat": nsat,
                    "nsig": nsig,
                    "ncell": ncell,
                })
                base.extend([
                    f"MSM station ID: {station}",
                    f"Epoch/TOW field: {tow}",
                    f"Satellites: {nsat}",
                    f"Signals: {nsig}",
                    f"Cells: {ncell}",
                ])
            elif ident == "1033":
                station = getattr(msg, "DF003", None)
                parsed.update({"station_id": station})
                base.extend([
                    f"Reference station ID: {station}",
                    "Receiver/antenna descriptor message present.",
                ])
            else:
                station = getattr(msg, "DF003", None)
                if station is not None:
                    parsed.update({"station_id": station})
                    base.append(f"Reference station ID: {station}")
        except Exception as err:
            base.append(f"Detail decode note: {err}")

        base.append("")
        base.append(repr(msg))
        return "\n".join(base), parsed

    def _process_queue(self):
        try:
            while True:
                kind, payload = self.event_queue.get_nowait()
                if kind == "status":
                    self.status_var.set(payload)
                elif kind == "log":
                    self.set_log(payload)
                elif kind == "rx":
                    self.total_received_bytes += int(payload)
                    self.last_rx_epoch = time.time()
                    self._refresh_health_labels()
                elif kind == "noise":
                    self.non_rtcm_bytes += int(payload)
                    self._refresh_health_labels()
                elif kind == "invalid":
                    self.invalid_frames += 1
                    self.last_error = payload
                    self._refresh_health_labels()
                    self.set_log(payload)
                elif kind == "message":
                    self.total_frames += 1
                    self.last_valid_ts = payload["timestamp"]
                    self.last_valid_epoch = payload["epoch"]
                    self.last_error = "-"
                    ident = payload["identity"]
                    info = self.stats.setdefault(
                        ident,
                        {"count": 0, "last_seen": "-", "last_detail": "", "raw_repr": ""},
                    )
                    info["count"] += 1
                    info["last_seen"] = payload["timestamp"]
                    info["last_detail"] = payload["detail"]
                    info["raw_repr"] = payload["raw_repr"]
                    self._upsert_tree_row(ident, info)

                    if ident in BASE_POSITION_TYPES and {"lat", "lon", "h"}.issubset(payload["parsed"]):
                        self.last_base_info = {
                            "identity": ident,
                            "epoch": payload["epoch"],
                            **payload["parsed"],
                        }
                    if ident in MSM_TYPES:
                        self.last_msm_info = {
                            "identity": ident,
                            "epoch": payload["epoch"],
                            **payload["parsed"],
                        }
                    self._refresh_health_labels()
                elif kind == "disconnected":
                    self.connect_btn.configure(text="Connect")
                    self._refresh_health_labels()
                self.event_queue.task_done()
        except queue.Empty:
            pass
        self.after(100, self._process_queue)

    def _refresh_watchdog(self):
        self._refresh_health_labels()
        self.after(500, self._refresh_watchdog)

    def _upsert_tree_row(self, ident: str, info: dict):
        summary_detail = info["last_detail"].splitlines()[0] if info["last_detail"] else ""
        values = (ident, info["count"], info["last_seen"], summary_detail)
        if self.tree.exists(ident):
            self.tree.item(ident, values=values)
        else:
            self.tree.insert("", "end", iid=ident, values=values)


if __name__ == "__main__":
    try:
        app = App()
        app.mainloop()
    except Exception:
        traceback.print_exc()
        raise
