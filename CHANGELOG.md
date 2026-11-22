# Changelog

## 1.1.0

### New
- Two new notification styles: **Windows 11 Glass** (blurred acrylic background, thin animated rainbow border, full or soft glow) and **Soft Aurora** (three slowly moving colour blobs, palettes Night, Sunset, Forest). Classic and Static are still available; new installs start with Glass.
- New layout for Glass and Aurora: icon, app name and time, a bar that shows the remaining time, slide-in entrance, smooth corners and shadow.
- Notification theme **Dark, Light or Same as Windows** (follows the Windows app theme by itself).
- Optional payload fields `icon` (a name such as `door`, `washer`, `info`, or an emoji) and `app`. A plain text payload is shown as the message.
- Optional **TLS** connection to the broker; the MQTT password is kept in the Windows Credential Manager.
- Click a notification to close it; long messages make it taller instead of being cut.

### Fixed
- A payload that is not a JSON object no longer stops notifications and the tray menu.
- The app keeps retrying when the broker is not reachable at startup, and never freezes while connecting.
- Notifications that arrive together are shown one after the other (up to 10 waiting).
- Changing size, theme or style and saving without a preview no longer breaks the next notification.
- Settings are saved safely in `%APPDATA%\PC-MQTT-Notifier\` (moved automatically from the old place); a damaged `config.json` is kept aside and the app starts with defaults.
- The settings window scrolls and fits small screens; wrong values are shown under the field.
- Position uses the work area of the primary monitor (taskbar excluded) and the Windows display scaling.
- Updates are installed only if the SHA256 matches `SHA256SUMS.txt`, the installer is chosen by its exact name, and the app restarts after a silent update.
- Retained messages are not shown again at startup; messages sent while the PC was off are not delivered later.
- Missing translations, the version number in update messages, the fade-out with low transparency, duplicate settings windows, a leftover tray icon after updating.
- Log file `notifier.log` and connection status in the tray icon tooltip.

### Build
- Version taken from the git tag; pinned dependencies and GitHub Actions; checks (syntax, lint, translations) before the build; code signing step ready, off until a certificate is added.
