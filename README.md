# C-ITS Inspector

[![Python Version](https://img.shields.io/badge/Python-3.11%20%7C%203.12%20%7C%203.13-blue.svg)](https://www.python.org/)
[![GUI](https://img.shields.io/badge/GUI-PyQt6-blue)](https://www.qt.io/)
[![Platform](https://img.shields.io/badge/Platform-Windows-lightgrey)](#)
[![Standards](https://img.shields.io/badge/Standards-ETSI%20%7C%20C--Roads-orange)](#)
[![License](https://img.shields.io/badge/License-Proprietary-red)](LICENSE)

**English** | [Deutsches README](README_DE.md)

A professional desktop application designed for in-depth analysis, validation, and map rendering of V2X/C-ITS messages (ITS-G5 / LTE-V2X) from PCAP files and MAP-XML topographies.

---

## 🎯 C-ITS Test Service & Deep Message Dissection

**C-ITS Inspector** is engineered for technical engineering teams, field testers, and systems integrators in the C-ITS ecosystem. It provides deep ASN.1 decoding and verification of complex road safety and traffic management use cases in the field.

### Supported C-ITS Message Types
*   **CAM** (Cooperative Awareness Message) – Vehicle state, telemetry, and spatial trajectories.
*   **DENM** (Decentralized Environmental Notification Message) – Hazard alerts, roadworks, and warning zones.
*   **MAPEM** (Map Data) – Intersection geometry, lanes (Ingress/Egress), stop lines, and signal group allocations.
*   **SPATEM** (Signal Phase and Timing) – Real-time signal state, timing predictions, and active phases.
*   **SREM / SSEM** (Signal Request / Status Message) – Prioritization requests (e.g., public transit, emergency vehicles) and RSU acknowledgements.
*   **NMEA / GNSS** – Reference GPS feeds to evaluate positioning drift and RSU-OBU distance calculations.

---

## 🛠 Core Features & Use Cases

### 1. C-Roads Conformance Validation (Handbook v3.2.0)
Verify MAPEM and SPATEM messages directly on import:
*   Validation of `IntersectionGeometry` IDs and topography revisions.
*   Consistency checks on lane geometry connections (Ingress-to-Egress).
*   Signal group binding checks between MAPEM lanes and active SPATEM states.

### 2. Request-Prioritization & Conflict Analysis (SREM/SSEM)
*   **Request Correlation**: Trace SREM priority requests and cross-reference them with the corresponding status replies (SSEM) returned by the RSU.
*   **Prioritization Panel**: Automatic extraction of timing anomalies, late grants, and request conflicts.
*   **Soft-Merge Trace**: Correlate TXA and RXA capture flows, resolving multi-source events with confidence values.

### 3. Arrival Forecast (ETA) & Clock Skew
*   Graph-based vehicle-to-stopline ETA analysis over time.
*   Clock-skew verification between vehicle internal clocks and infrastructure signals.
*   Chronological event tables for troubleshooting SREM/SSEM interactions.

### 4. Vector Map Topography & Trajectory Easing
*   Render intersection plans dynamically (Inbound, Outbound, stoplines, and phase connections) as vector lines.
*   Switchable basemaps (OSM, Satellite, Light, Dark) with local caching.
*   **Non-linear Interpolation (Easing)**: Eased coordinates between subsequent GNSS messages, providing realistic, fluid vehicle movement during playback without jumps.

---

## 🚀 System Architecture & High Performance

The application is built on PyQt6 and an optimized QWebEngine / Leaflet stack designed for large captures:
*   **Lazy Tab Rendering**: Maps and raw tables update only when their tab is visible. This saves significant CPU cycles and prevents WebEngine IPC bottlenecks at high speeds (up to 10x).
*   **Memory Guard**: A background thread continuously monitors the application's RAM usage. It automatically switches map details to "Saver" or "Diagnostic" mode if memory exceeds thresholds.
*   **Local Assets**: Leaflet JS/CSS libraries and images are bundled locally for offline use.

---

## 💻 Getting Started

### Prerequisites
*   Windows 10 or Windows 11
*   Python >= 3.11 with dependencies (see `pyproject.toml`)
*   *Optional*: Wireshark / TShark installed on the system (greatly accelerates PCAP parsing).

### Installation & Launch
The free download of the Demo version is available at the following link: [C-ITS-Inspector.exe](https://drive.google.com/file/d/1p54nI-e_UJO4Gr8u9W-sWpO_6mTC0klo/view?usp=sharing)

1.  Clone the repository or unpack the release bundle.
2.  Install dependencies:
    ```powershell
    pip install .[dev]
    ```
3.  Launch the application:
    ```powershell
    python c_its_inspector_launcher.py
    ```

---

## 🔒 License and Commercial Terms

This software is **proprietary** and protected by copyright.

> [!IMPORTANT]
> **Summary of Usage Terms:**
> *   **Copyright**: Copyright (c) 2026 Kevin Seipel. All rights reserved.
> *   **Kevin Seipel**: Unrestricted personal usage permitted.
> *   **Third Parties (non-commercial / academic)**: Usage permitted unless explicitly revoked by the copyright owner at any time without reason.
> *   **Research Institutes**: Can contact sales to receive a free license for 0.5 years (6 months). Extensions of this license are clearly NOT excluded.
> *   **Commercial Usage**: Requires a valid commercial license. Unlicensed commercial usage is strictly prohibited. Commercial licenses are valid for a period of 1 year.

### Acquiring a License
For commercial inquiries, custom agreements, or volume licensing options, please contact:

📧 **Email**: **[vertrieb@seipel.uk](mailto:vertrieb@seipel.uk)**
