### TabGuard AI — Local Prototype

On-device, zero-API background utility that watches your active window title, runs it through a local "Semantic Buffer Interceptor" (keyword/regex hazard classifier), and instantly drops a clean placeholder overlay over the screen if a hazard (private chat, finance doc, sensitive folder, etc.) comes into focus — so it never leaks live during a screen-share. 

### Architecture

tabguard_ai/
├── hazard_classifier.py   # Semantic Buffer Interceptor (keyword/regex scoring, 0-100 severity)
├── window_monitor.py      # Background thread polling the active window title (~30 Hz)
├── overlay.py             # Borderless, semi-transparent, always-on-top intercept canvas
├── main.py                # Control dashboard (Tkinter) + system tray (pystray) + wiring
└── requirements.txt

Everything runs 100% locally. No network calls, no API keys, no telemetry. 

### 1. Install dependencies

Use a virtual environment (recommended): 

bash

python -m venv venv
# Windows
venv\Scripts\activate
# macOS/Linux
source venv/bin/activate

pip install -r requirements.txt

Use code with caution.

### 2. Run it

bash

python main.py

Use code with caution.

This opens the **Control Dashboard**. A tray icon (green shield) also appears in your system tray/menu bar — closing the dashboard window minimizes to tray rather than quitting, so monitoring keeps running. 

### 3. Core Features & Intercept Modes

TabGuard features **two** dynamic intercept modes built specifically to prevent data leaks during live presentations or screen-sharing workflows: 

* **Fullscreen Mode:** Triggers instantly when the focused, active window itself matches a hazard constraint (e.g., you accidentally Alt-Tab directly into WhatsApp Desktop or a sensitive corporate spreadsheet). The entire display is covered with a secure placeholder canvas within 33ms.
* **Region Mode (Notification Sniping):** Triggers when a small background notification toast (such as an incoming WhatsApp Web popup banner or a Slack alert) arrives on screen. Since toasts do not take OS-keyboard focus, TabGuard runs an independent enumeration scan, calculates the exact pixel bounding box coordinates of the active popup window, and places a localized dark privacy shield ONLY over that specific region. The rest of your active screen remains fully live and completely uninterrupted.

### Future Roadmap

* **Distilled Local Embeddings:** Replace the current keyword engine with a lightweight localized sentence-transformer running offline via onnxruntime to achieve true meaning-based semantic hazard detection (e.g., catching terms like "CTC" or "take-home" automatically without literal keyword hits).
* **Native OS Screen-Share Hooks:** Hook directly into browser getDisplayMedia instances or system recording indicators so the background utility dynamically triggers only during an active live call session.
* **Selective In-Frame Redaction:** Move from full boundary masking to inside-the-window blurring, automatically pixelating specific string values (like financial digits) while keeping the surrounding document completely legible to the audience.
