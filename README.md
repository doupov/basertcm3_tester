# Base RTCM3 Tester

Simple Python GUI tool for debugging RTCM3 streams over TCP.

Repository: https://github.com/doupov/basertcm3_tester

---

## 🚀 Overview

This application connects to a TCP RTCM3 stream (e.g. from RTKLIB, NTRIP client, or GNSS base station) and provides real-time diagnostics:

- Detects and counts RTCM message types
- Validates RTCM3 frames (CRC check via `pyrtcm`)
- Shows stream health and data quality
- Decodes base station position (1005/1006)
- Detects MSM correction messages
- Provides watchdog for stream activity

Designed as a lightweight debugging tool for GNSS / RTK workflows.

---

## 🧩 Features

### 📡 Connection
- TCP client (IP + Port)
- Connect / Disconnect button

### 📊 Message Statistics
- Message count per RTCM type
- Last received timestamp
- Total bytes received

### ✅ RTCM Validation
- Valid frames
- Invalid frames (CRC errors)
- Validity percentage

### 🛰 Base Station (1005 / 1006)
- Station ID
- ECEF coordinates (X, Y, Z)
- Converted to:
  - Latitude
  - Longitude
  - Ellipsoidal height

### 📡 MSM Detection
- Detects MSM4–MSM7 messages (1074–1127)
- Shows:
  - Last MSM type
  - Station ID
  - Number of satellites
  - Signals
  - Cells

### ⏱ Watchdog
- `STREAM OK`
- `WAITING FOR DATA`
- `STREAM DEAD`

---

## 📦 Requirements

- Python 3.10+
- `pyrtcm`
- `pynmeagps`
- `tkinter` (GUI)

Install dependencies:
```bash
pip install -r requirements_rtcm_debugger.txt
```

---

## 🍏 macOS Note

If you are using Homebrew Python and get:

```bash
ModuleNotFoundError: No module named '_tkinter'
```

Install Tk support:

```bash
brew install python-tk
```

---

## ▶️ Run

```bash
python3 rtcm_debugger.py
```

Then:
1. Enter IP and Port of your RTCM3 stream
2. Click **Connect**

---

## 🔍 Typical Use Cases

- Debugging RTKLIB `str2str` streams
- Verifying RTCM output from GNSS base stations (e.g. UM980 / UM982)
- Checking NTRIP streams before sending to services (Onocoy, etc.)
- Diagnosing corrupted or mixed TCP streams

---

## ⚠️ Notes

- CRC validation is handled by `pyrtcm`
- Logical correctness of data (e.g. wrong coordinates) is not guaranteed
- Some streams may contain non-RTCM data (handled as "garbage bytes")

---

## 🛠 Future Improvements

- Traffic-light health indicator (OK / WARN / FAIL)
- Message rate graphs
- Export to `.rtcm3` file
- NTRIP client support
- Web-based UI version

---

## 📜 License

Apache 2

---

## ✍️ Author

Martin Fox  
https://github.com/doupov

---

## ⭐ If you find this useful

Give it a star ⭐ and help others working with GNSS / RTK!
