# 🔔 PC-MQTT-Notifier

**Bypass Windows Toast. Own your notifications with a lightweight, highly customizable, fluid overlay connected to MQTT.**

### 🌐 [giosci1994.github.io/PC-MQTT-Notifier](https://giosci1994.github.io/PC-MQTT-Notifier/)

Listen to any **MQTT topic** (from Home Assistant, Node-RED, or custom scripts) and display sleek, non-invasive desktop notifications with animated fluid backgrounds on Windows.

<p align="center">
  <a href="https://github.com/giosci1994/PC-MQTT-Notifier/actions/workflows/build.yml"><img src="https://github.com/giosci1994/PC-MQTT-Notifier/actions/workflows/build.yml/badge.svg" alt="Build Status" /></a>
  <a href="https://github.com/giosci1994/PC-MQTT-Notifier/releases/latest"><img src="https://img.shields.io/github/v/release/giosci1994/PC-MQTT-Notifier?color=00b585" alt="Release" /></a>
  <img src="https://img.shields.io/github/downloads/giosci1994/PC-MQTT-Notifier/total?color=34d399" alt="Downloads" />
  <img src="https://img.shields.io/badge/platform-Windows-0078d4" alt="Windows" />
  <a href="LICENSE"><img src="https://img.shields.io/github/license/giosci1994/PC-MQTT-Notifier" alt="License" /></a>
  <a href="https://buymeacoffee.com/giosci1994u"><img src="https://img.shields.io/badge/Buy%20Me%20a%20Coffee-FFDD00?logo=buymeacoffee&logoColor=black" alt="Buy Me a Coffee" /></a>
</p>

<p align="center">
  <img src="docs/social-preview.png" width="800" alt="PC-MQTT-Notifier Social Preview & Mockup" />
</p>

---

## ✨ Features

- 🌊 **Fluid Background**: Gorgeous animated mesh gradients powered by fast Lissajous curve calculations. Uses 0% CPU in static background mode.
- 🎨 **Highly Customizable**: Change UI scale, opacity/transparency, corner radius, animation FPS, display duration, and screen position (top-center, bottom-right, top-right, bottom-center).
- 🌍 **Native i18n (Bilingual)**: Full built-in English and Italian translations. Easily add new languages by dropping a JSON file into the `locales/` folder.
- ⚙️ **System Tray Native**: Runs quietly in your system tray with single-click settings and instant test previews.
- 🔄 **GitHub Auto-Updater**: Built-in update checker that automatically notifies you and installs the latest `.exe` release in one click.
- 🔌 **Home Assistant & MQTT Ready**: Receives simple JSON payloads from Home Assistant, Node-RED, or any custom MQTT broker.

---

## 📸 Screenshots

<p align="center">
  <img src="docs/settings.png" width="320" alt="Settings Dashboard" />
  &nbsp;&nbsp;
  <img src="docs/dark_pop-up_fluid.png" width="400" alt="Dark Theme Notification Popup" />
</p>

<p align="center">
  <img src="docs/light_pop-up_static.png" width="400" alt="Light Theme Notification Popup" />
</p>

---

## 🚀 Installation

### Option 1: Installer (Recommended)
1. Download `PC-MQTT-Notifier-Setup-1.0.0.exe` from the **[Releases](../../releases)** page.
2. Run the installer. It will automatically place the application in your Start Menu and support **1-click auto-updates**.

### Option 2: Portable Executable
1. Download `PC-MQTT-Notifier.exe` from the Releases page.
2. Run it anywhere on your system without installation.

### Verify the download
From the next release, every release also has `SHA256SUMS.txt` and `VERIFY.ps1`. Put them in the
same folder as the downloaded `.exe` and run, in PowerShell:

```powershell
powershell -ExecutionPolicy Bypass -File .\VERIFY.ps1
# or by hand, then compare with SHA256SUMS.txt:
Get-FileHash .\PC-MQTT-Notifier-Setup-1.0.0.exe -Algorithm SHA256
```

---

## ⚙️ MQTT Payload & Setup

The application subscribes to your specified MQTT topic (default: `homeassistant/pc_giovanni/notify`).

### 📩 JSON Payload Format
Send a JSON payload with a `title` and `message` key:

```json
{
  "title": "Front Door Opened",
  "message": "The main entrance door sensor was triggered at 16:20."
}
```

### 🏠 Home Assistant Automation Example

Add this action to any Home Assistant automation YAML:

```yaml
action: mqtt.publish
data:
  topic: homeassistant/pc_giovanni/notify
  payload: >-
    {
      "title": "Solar Power Peak",
      "message": "Solar panel production exceeded 4.5 kW!"
    }
```

---

## 🛠️ Development & Building from Source

### Prerequisites
- Python 3.10+ installed on Windows.

### 1. Clone & Run
```bash
git clone https://github.com/giosci1994/PC-MQTT-Notifier.git
cd PC-MQTT-Notifier

# Install dependencies
pip install -r requirements.txt

# Run main application
python main.py
```

### 2. Build Executable with PyInstaller
```bash
pyinstaller --noconsole --onefile --icon=icon.ico --name="PC-MQTT-Notifier" main.py
```

### 3. Build Windows Installer with InnoSetup
Compile the `setup.iss` script using **Inno Setup 6**:
```bash
iscc setup.iss
```
This generates `Output/PC-MQTT-Notifier-Setup-1.0.0.exe`.

---

## 🧩 Project Structure

```
PC-MQTT-Notifier/
├── main.py                  # Core application (CTk GUI, MQTT client, pystray, auto-updater)
├── requirements.txt         # Python dependencies
├── config.json              # Saved configuration settings
├── icon.png / icon.ico      # Application icons
├── setup.iss                # InnoSetup installer configuration
├── scripts/VERIFY.ps1       # Checks downloads against SHA256SUMS.txt (shipped with each release)
├── locales/                 # i18n translation files
│   ├── en.json              # English locale
│   └── it.json              # Italian locale
├── docs/                    # GitHub Pages website & assets
│   ├── index.html           # Arborae-standard landing page
│   ├── css/style.css        # Stylesheet & design system
│   ├── js/main.js           # Scroll reveal & toggle scripts
│   ├── social-preview.html  # Source of the social preview (Firefox headless screenshot)
│   └── social-preview.png   # 1280x640 social preview image
└── .github/
    └── workflows/
        └── build.yml        # CI/CD automated build workflow
```

---

## 🔐 Privacy & Security

- **100% Local Connection**: Connects directly to your local or private MQTT broker. No telemetry or tracking.
- **Auto-Updates**: Update checks strictly poll public GitHub Releases via the official GitHub REST API.

---

## ☕ Support

If PC-MQTT-Notifier is useful to you, you can buy me a coffee.

<a href="https://buymeacoffee.com/giosci1994u"><img src="https://cdn.buymeacoffee.com/buttons/v2/default-yellow.png" height="45" alt="Buy Me a Coffee" /></a>

## 📄 License

Distributed under the **GPLv3 License**. See [`LICENSE`](LICENSE) for more information.

Developed with ❤️ by **[giosci1994](https://github.com/giosci1994)** / **Arborae**.
