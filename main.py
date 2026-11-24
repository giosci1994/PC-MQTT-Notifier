import json
import threading
import queue
import time
import os
import glob
import logging
import collections
import requests
import subprocess
import tempfile
import paho.mqtt.client as mqtt
import customtkinter as ctk
from PIL import Image, ImageTk
import pystray
from pystray import MenuItem as item
import pywinstyles
import tkinter as tk
from datetime import datetime
import notification_styles as nstyles
import app_core

log = app_core.log
ICON_FILE = app_core.resource_path("icon.png")
ICON_ICO = app_core.resource_path("icon.ico")
APP_VERSION = "1.2.0"
REPO_NAME = "giosci1994/PC-MQTT-Notifier"
GITHUB_API_URL = f"https://api.github.com/repos/{REPO_NAME}/releases/latest"

class Translator:
    def __init__(self, locale_dir="locales", default_lang="en"):
        # Next to the program (or inside the exe), not in the current folder
        self.locale_dir = app_core.resource_path(locale_dir)
        self.default_lang = default_lang
        self.current_lang = default_lang
        self.strings = {}
        self.available_langs = []
        self.load_available_langs()
        self.set_language(default_lang)
        
    def load_available_langs(self):
        if not os.path.exists(self.locale_dir):
            return
        files = glob.glob(os.path.join(self.locale_dir, "*.json"))
        self.available_langs = [os.path.splitext(os.path.basename(f))[0] for f in files]
        if not self.available_langs:
            self.available_langs = [self.default_lang]
        
    def set_language(self, lang):
        if lang not in self.available_langs:
            lang = self.default_lang
        
        self.current_lang = lang
        file_path = os.path.join(self.locale_dir, f"{lang}.json")
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                self.strings = json.load(f)
        except Exception:
            self.strings = {}
            
    def get(self, key, default=None):
        return self.strings.get(key, default if default is not None else key)

_translator = Translator()
def _(key, default=None):
    return _translator.get(key, default)

def _f(key, default=None, **values):
    # Translation with {placeholders} filled in
    text = _(key, default)
    try:
        return text.format(**values)
    except Exception:
        return text

def dpi_factor(widget):
    # Windows display scaling (customtkinter makes the app DPI aware)
    try:
        return max(1.0, min(3.0, widget.winfo_fpixels('1i') / 96.0))
    except Exception:
        return 1.0

def ctk_scaling(widget):
    # The factor customtkinter applies to its widgets and to geometry() sizes
    try:
        return float(ctk.ScalingTracker.get_window_scaling(widget))
    except Exception:
        return dpi_factor(widget)

def place_box(root, width, height, position, margin=35):
    # Position on the real work area (taskbar excluded) of the primary monitor
    area = nstyles.work_area()
    if area is None:
        area = (0, 0, root.winfo_screenwidth(), root.winfo_screenheight() - 40)
    left, top, right, bottom = area
    if position in ("top-center", "bottom-center"):
        x = left + (right - left - width) / 2
    else:
        x = right - width - margin
    if str(position).startswith("bottom"):
        y = bottom - height - margin
    else:
        y = top + margin
    return int(x), int(y)

class SettingsWindow(ctk.CTkToplevel):
    ERROR_COLOR = "#e5484d"

    def __init__(self, parent, current_config, on_save, on_preview):
        super().__init__(parent)
        self.main_app = parent
        self.title(_("settings_title", "PC-MQTT-Notifier Settings"))
        # Height that fits the screen; the fields scroll, the buttons stay visible
        try:
            screen_h = self.winfo_screenheight() / ctk_scaling(self)
        except Exception:
            screen_h = 900
        self.geometry(f"470x{int(max(420, min(900, screen_h * 0.85)))}")
        self.minsize(420, 380)
        
        if os.path.exists(ICON_ICO):
            self.after(200, lambda: self.iconbitmap(ICON_ICO))
            
        self.current_config = dict(current_config)
        self.on_save_callback = on_save
        self.on_preview_callback = on_preview
        self.attributes("-topmost", True)
        self.protocol("WM_DELETE_WINDOW", self.on_close)
        
        try:
            pywinstyles.apply_style(self, "mica")
        except Exception as e:
            log.info("Stile mica non applicato: %s", e)
        
        is_dark = nstyles.resolve_dark(current_config.get("theme", "dark"))
        self.configure(fg_color="#1c1c1e" if is_dark else "#f3f3f3")
        
        self._choices = {}
        self._fields = {}
        title_font = ctk.CTkFont(family="Segoe UI Variable Display", size=24, weight="bold")
        label_font = ctk.CTkFont(family="Segoe UI Variable Text", size=14)
        self.label_font = label_font
        self.error_font = ctk.CTkFont(family="Segoe UI Variable Text", size=12)
        
        # Buttons at the bottom, always visible
        bottom = ctk.CTkFrame(self, fg_color="transparent")
        bottom.pack(side="bottom", fill="x", padx=30, pady=(8, 16))
        self.btn_test = ctk.CTkButton(bottom, text=_("btn_preview", "Show Notification Preview"), font=ctk.CTkFont(family="Segoe UI Variable Text", size=15), height=40, corner_radius=10, fg_color="transparent", border_width=1, command=self.preview)
        self.btn_test.pack(fill="x", pady=(0, 8))
        self.btn_save = ctk.CTkButton(bottom, text=_("btn_save", "Save and Apply"), font=ctk.CTkFont(family="Segoe UI Variable Text", size=15, weight="bold"), height=40, corner_radius=10, command=self.save)
        self.btn_save.pack(fill="x")
        if getattr(self.main_app, 'update_available', None):
            ver = self.main_app.update_available[0]
            self.btn_update = ctk.CTkButton(bottom, text=_f("btn_update", "Update to {ver}", ver=ver), font=ctk.CTkFont(family="Segoe UI Variable Text", size=15, weight="bold"), height=40, corner_radius=10, fg_color="#28a745", hover_color="#218838", command=lambda: self.main_app.command_queue.put("download_update"))
            self.btn_update.pack(fill="x", pady=(8, 0))
        
        # The fields, in a frame that scrolls
        form = ctk.CTkScrollableFrame(self, fg_color="transparent")
        form.pack(side="top", fill="both", expand=True, padx=8, pady=(8, 0))
        form.grid_columnconfigure(1, weight=1)
        self.form = form
        
        ctk.CTkLabel(form, text=_("section_mqtt", "MQTT Network"), font=title_font).grid(row=0, column=0, columnspan=2, pady=(15, 10), sticky="w", padx=15)
        
        self.create_entry(_("mqtt_broker", "MQTT Broker:"), 1, "mqtt_broker")
        self.create_entry(_("mqtt_port", "MQTT Port:"), 2, "mqtt_port", default="1883")
        self.create_entry(_("mqtt_username", "MQTT Username:"), 3, "mqtt_username")
        self.create_entry(_("mqtt_password", "MQTT Password:"), 4, "mqtt_password", show="*")
        self.create_entry(_("mqtt_topic", "MQTT Topic:"), 5, "mqtt_topic")
        
        self.label(_("mqtt_tls", "TLS (port 8883):"), 6)
        self.e_tls = ctk.CTkSwitch(form, text="", font=label_font)
        if current_config.get("mqtt_tls", False):
            self.e_tls.select()
        else:
            self.e_tls.deselect()
        self.e_tls.grid(row=6, column=1, padx=(0, 15), pady=8, sticky="w")
        
        ctk.CTkLabel(form, text=_("section_appearance", "Appearance and Notifications"), font=title_font).grid(row=7, column=0, columnspan=2, pady=(30, 10), sticky="w", padx=15)
        
        self.label(_("language", "Language:"), 8)
        self.e_language = ctk.CTkOptionMenu(form, values=_translator.available_langs or ["en"], font=label_font)
        self.e_language.set(current_config.get("language", "en"))
        self.e_language.grid(row=8, column=1, padx=(0, 15), pady=8, sticky="ew")
        
        self.create_entry(_("duration", "Duration (s):"), 9, "duration", default="5")
        
        self.label(_("position", "Position:"), 10)
        self.e_position = self.create_choice("position", [
            ("top-center", _("pos_top_center", "Top center")),
            ("top-right", _("pos_top_right", "Top right")),
            ("bottom-right", _("pos_bottom_right", "Bottom right")),
            ("bottom-center", _("pos_bottom_center", "Bottom center")),
        ], current_config.get("position", "top-center"))
        self.e_position.grid(row=10, column=1, padx=(0, 15), pady=8, sticky="ew")
        
        self.label(_("theme", "Theme:"), 11)
        self.e_theme = self.create_choice("theme", [
            ("dark", _("theme_dark", "Dark")),
            ("light", _("theme_light", "Light")),
            ("system", _("theme_system", "Same as Windows")),
        ], current_config.get("theme", "dark"))
        self.e_theme.grid(row=11, column=1, padx=(0, 15), pady=8, sticky="ew")
        
        self.label(_("alpha", "Transparency:"), 12)
        self.e_alpha = ctk.CTkSlider(form, from_=0.2, to=1.0, number_of_steps=80)
        self.e_alpha.set(current_config.get("alpha", 0.94))
        self.e_alpha.grid(row=12, column=1, padx=(0, 15), pady=8, sticky="ew")
        
        self.label(_("fps", "Fluidity (FPS):"), 13)
        self.e_fps = ctk.CTkSlider(form, from_=10, to=120, number_of_steps=110)
        self.e_fps.set(current_config.get("fps", 50))
        self.e_fps.grid(row=13, column=1, padx=(0, 15), pady=8, sticky="ew")
        
        self.label(_("corner_radius", "Corner Radius:"), 14)
        self.e_corner = ctk.CTkSlider(form, from_=0, to=65, number_of_steps=65)
        self.e_corner.set(current_config.get("corner_radius", 30))
        self.e_corner.grid(row=14, column=1, padx=(0, 15), pady=8, sticky="ew")
        
        # Notification style (replaces the old "fluid background" switch:
        # classic = fluid on, static = fluid off)
        self.label(_("notification_style", "Notification Style:"), 15)
        self.e_style = self.create_choice("notification_style", [
            ("glass", _("style_glass", "Windows 11 Glass")),
            ("aurora", _("style_aurora", "Soft Aurora")),
            ("classic", _("style_classic", "Classic")),
            ("static", _("style_static", "Static")),
            ("ambient", _("style_ambient", "Ambient")),
            ("poster", _("style_poster", "Poster")),
            ("vinyl", _("style_vinyl", "Vinyl")),
        ], current_config.get("notification_style", nstyles.DEFAULT_STYLE),
            command=lambda _v: self.update_variant_row())
        self.e_style.grid(row=15, column=1, padx=(0, 15), pady=8, sticky="ew")
        
        # Variant of the chosen style: palette for aurora, glow for glass
        self.variant_label = ctk.CTkLabel(form, text="", font=label_font)
        self.e_palette = self.create_choice("aurora_palette", [
            ("night", _("palette_night", "Night")),
            ("sunset", _("palette_sunset", "Sunset")),
            ("forest", _("palette_forest", "Forest")),
        ], current_config.get("aurora_palette", nstyles.DEFAULT_PALETTE))
        self.e_glow = self.create_choice("glass_glow", [
            ("full", _("glow_full", "Full")),
            ("soft", _("glow_soft", "Soft")),
        ], current_config.get("glass_glow", nstyles.DEFAULT_GLOW))
        self.update_variant_row()
        
        self.label(_("scale", "Notification Size:"), 17)
        self.e_scale = ctk.CTkSlider(form, from_=0.7, to=1.5, number_of_steps=80)
        self.e_scale.set(current_config.get("scale", 1.0))
        self.e_scale.grid(row=17, column=1, padx=(0, 15), pady=8, sticky="ew")

    def label(self, text, row):
        ctk.CTkLabel(self.form, text=text, font=self.label_font).grid(row=row, column=0, padx=(15, 10), pady=8, sticky="e")

    def create_choice(self, key, options, current, command=None):
        # Option menu that shows translated labels and stores config values
        labels = [label for _value, label in options]
        menu = ctk.CTkOptionMenu(self.form, values=labels, font=self.label_font, command=command)
        menu.set(dict(options).get(current, labels[0]))
        self._choices[key] = (menu, options)
        return menu

    def get_choice(self, key):
        menu, options = self._choices[key]
        label = menu.get()
        for value, text in options:
            if text == label:
                return value
        return options[0][0]

    def update_variant_row(self):
        style = self.get_choice("notification_style")
        for widget in (self.variant_label, self.e_palette, self.e_glow):
            widget.grid_remove()
        if style == "aurora":
            self.variant_label.configure(text=_("aurora_palette", "Aurora Colors:"))
            self.e_palette.grid(row=16, column=1, padx=(0, 15), pady=8, sticky="ew")
        elif style == "glass":
            self.variant_label.configure(text=_("glass_glow", "Glow:"))
            self.e_glow.grid(row=16, column=1, padx=(0, 15), pady=8, sticky="ew")
        else:
            return
        self.variant_label.grid(row=16, column=0, padx=(15, 10), pady=8, sticky="e")

    def style_settings(self):
        style = self.get_choice("notification_style")
        return {
            "notification_style": style,
            "aurora_palette": self.get_choice("aurora_palette"),
            "glass_glow": self.get_choice("glass_glow"),
            # kept for older versions of the app: off only for the static style
            "enable_fluid": style != "static",
        }

    def create_entry(self, label_text, row, config_key, show="", default=""):
        # Entry with a message under it, shown when the value is wrong
        self.label(label_text, row)
        cell = ctk.CTkFrame(self.form, fg_color="transparent")
        cell.grid(row=row, column=1, padx=(0, 15), pady=8, sticky="ew")
        entry = ctk.CTkEntry(cell, show=show, font=self.label_font, height=35, corner_radius=8, border_width=1)
        val = self.current_config.get(config_key, default)
        entry.insert(0, str(val))
        entry.pack(fill="x")
        error = ctk.CTkLabel(cell, text="", font=self.error_font, text_color=self.ERROR_COLOR, anchor="w", justify="left")
        self._fields[config_key] = (entry, error, entry.cget("border_color"))
        setattr(self, f"e_{config_key}", entry)

    def show_errors(self, errors):
        texts = {
            "error_required": _("error_required", "Required field."),
            "error_port": _("error_port", "Enter a whole number from 1 to 65535."),
            "error_duration": _("error_duration", "Enter the seconds, more than 0 (e.g. 5 or 5.5)."),
        }
        for key, (entry, error, border) in self._fields.items():
            if key in errors:
                error.configure(text=texts.get(errors[key], errors[key]))
                error.pack(fill="x", pady=(2, 0))
                entry.configure(border_color=self.ERROR_COLOR)
            else:
                error.pack_forget()
                entry.configure(border_color=border)

    def collect(self):
        fields = {key: entry.get() for key, (entry, _err, _b) in self._fields.items()}
        values, errors = app_core.validate_settings(fields)
        cfg = dict(self.current_config)
        cfg.update(values)
        cfg.update({
            "mqtt_tls": bool(self.e_tls.get()),
            "position": self.get_choice("position"),
            "theme": self.get_choice("theme"),
            "alpha": round(float(self.e_alpha.get()), 2),
            "fps": int(round(self.e_fps.get())),
            "corner_radius": int(round(self.e_corner.get())),
            **self.style_settings(),
            "scale": round(float(self.e_scale.get()), 2),
            "language": self.e_language.get(),
        })
        return cfg, errors
        
    def preview(self):
        try:
            preview_config, _errors = self.collect()
            preview_config["duration"] = 99999  # stays until the window closes
            self.on_preview_callback(preview_config)
        except Exception:
            log.exception("Anteprima non riuscita")

    def save(self):
        new_config, errors = self.collect()
        self.show_errors(errors)
        if errors:
            return
        self.on_save_callback(new_config)
        self.main_app.hide_notification()
        self.destroy()

    def on_close(self):
        self.main_app.hide_notification()
        self.destroy()

class StyledPopup:
    """One notification in any style (glass, aurora, classic, static, ambient,
    poster, vinyl), drawn with Pillow by notification_styles.CardRenderer.

    On Windows the window has per-pixel alpha (UpdateLayeredWindow): smooth
    corners, shadow and glow. The glass style uses only this layered window
    (no separate acrylic backdrop window, because on Windows 11 DWM ignores
    SetWindowRgn with ACCENT_ENABLE_ACRYLICBLURBEHIND).
    If something fails (or not on Windows) it falls back to the old way:
    -transparentcolor and -alpha, card only, edges blended on its colour.
    """
    ENTER = 0.45  # seconds: slide down + fade in
    FADE_IN = 0.3
    EXIT = 0.22
    OFFSCREEN = -32000
    KEY = "#000001"

    def __init__(self, root, config, title, message, icon, app_name, dark, on_click=None):
        self.root = root
        self.on_click = on_click
        self.config = config
        self.dark = dark
        self.closed = False
        self.exiting = False
        self.task = None
        self.win = None
        self.canvas = None
        self.photo = None
        self.layered = None
        self.backdrop = None
        self.backdrop_pending = False
        self.text = (title, message, icon, app_name, datetime.now().strftime("%H:%M"))

        scale = float(config.get("scale", 1.0))
        try:
            # Windows DPI scaling (customtkinter makes the app DPI aware)
            scale *= max(1.0, min(3.0, root.winfo_fpixels('1i') / 96.0))
        except Exception:
            pass
        self.scale = scale
        self.alpha = max(0.2, min(1.0, float(config.get("alpha", 0.94))))
        try:
            fps = float(config.get("fps", 50))
        except Exception:
            fps = 50
        self.delay = int(1000 / fps) if fps > 0 else 20
        self.duration = max(0.5, float(config.get("duration", 5)))

        opened = False
        if os.name == 'nt':
            try:
                self.renderer = self.make_renderer(margin=True)
                self.place()
                # No acrylic backdrop window for "glass": DWM ignores SetWindowRgn
                # with ACCENT_ENABLE_ACRYLICBLURBEHIND on Windows 11, showing a
                # gray rectangle behind rounded cards.
                self.open_layered()
                opened = True
            except Exception as e:
                log.warning("Finestra a strati non disponibile, uso il fallback: %s", e)
                self.close_windows()
        if not opened:
            self.renderer = self.make_renderer(margin=False)
            self.place()
            self.open_fallback()

        self.t0 = time.monotonic()
        self.tick()

    def make_renderer(self, margin):
        title, message, icon, app_name, now = self.text
        cfg = self.config
        return nstyles.CardRenderer(
            cfg.get("notification_style", nstyles.DEFAULT_STYLE), self.dark, title, message,
            app_name=app_name, time_text=now, icon=icon, scale=self.scale,
            corner_radius=cfg.get("corner_radius", 30),
            palette=cfg.get("aurora_palette", nstyles.DEFAULT_PALETTE),
            glow=cfg.get("glass_glow", nstyles.DEFAULT_GLOW), margin=margin)

    def place(self):
        # Same positions as the other styles, on the work area, computed on the card
        r = self.renderer
        self.card_x, self.card_y = place_box(self.root, r.cw, r.ch, self.config.get("position", "top-center"))

    def new_window(self, bg):
        win = tk.Toplevel(self.root)
        win.overrideredirect(True)
        win.attributes("-topmost", True)
        win.configure(bg=bg)
        if self.on_click is not None:
            # a click closes the notification before its time
            win.bind("<Button-1>", lambda _e: self.on_click())
        return win

    def open_layered(self):
        r = self.renderer
        w, h = r.size
        win = self.new_window("black")
        self.win = win
        win.geometry(f"{w}x{h}+{self.OFFSCREEN}+{self.OFFSCREEN}")
        win.update_idletasks()
        self.layered = nstyles.LayeredWindow(nstyles.root_hwnd(win.winfo_id()), (w, h))
        x, y = self.window_pos(-r.s * 18)
        if not self.layered.present(r.frame(0, 1), x, y, 0):
            raise OSError("UpdateLayeredWindow failed")

    def open_fallback(self):
        r = self.renderer
        w, h = r.size
        win = self.new_window(self.KEY)
        self.win = win
        win.attributes("-alpha", 0.0)
        if os.name == 'nt':
            win.wm_attributes("-transparentcolor", self.KEY)
        self.canvas = tk.Canvas(win, width=w, height=h, bg=self.KEY, highlightthickness=0)
        self.canvas.pack(fill="both", expand=True)
        self.photo = ImageTk.PhotoImage(nstyles.flatten_on_key(r.frame(0, 1), r.matte))
        self.canvas.create_image(0, 0, anchor="nw", image=self.photo)
        x, y = self.window_pos(-r.s * 18)
        win.geometry(f"{w}x{h}+{x}+{y}")

    def window_pos(self, dy):
        m = self.renderer.m
        return self.card_x - m, int(round(self.card_y - m + dy))

    def tick(self):
        self.task = None
        if self.closed:
            return
        now = time.monotonic()
        elapsed = now - self.t0
        s = self.renderer.s
        if self.exiting:
            k = 1.0 - (now - self.exit_t0) / self.EXIT
            if k <= 0:
                self.destroy()
                return
            alpha, dy = self.alpha * k, -6 * s * (1 - k)
        else:
            e = elapsed / self.ENTER
            alpha = self.alpha * min(1.0, elapsed / self.FADE_IN)
            # the static style only fades in, the others also slide down
            dy = 0 if self.renderer.style == "static" else -18 * s * (1 - nstyles.ease_out_back(e))
        try:
            img = self.renderer.frame(elapsed, 1.0 - elapsed / self.duration)
            x, y = self.window_pos(dy)
            if self.layered is not None:
                self.layered.present(img, x, y, alpha)
            else:
                self.photo.paste(nstyles.flatten_on_key(img, self.renderer.matte))
                self.win.geometry(f"+{x}+{y}")
                self.win.attributes("-alpha", alpha)
        except Exception as e:
            log.warning("Errore animazione notifica: %s", e)
            self.destroy()
            return
        self.task = self.root.after(self.delay, self.tick)

    def start_exit(self):
        if self.closed or self.exiting:
            return
        self.exiting = True
        self.exit_t0 = time.monotonic()

    def close_windows(self):
        if self.layered is not None:
            self.layered.close()
            self.layered = None
        if self.win is not None:
            try:
                self.win.destroy()
            except Exception:
                pass
        self.win = None
        self.canvas = None

    def destroy(self):
        # Stops the animation and frees everything: no CPU used after closing
        self.closed = True
        if self.task is not None:
            try:
                self.root.after_cancel(self.task)
            except Exception:
                pass
            self.task = None
        self.close_windows()

class MainApplication(ctk.CTk):
    QUEUE_LIMIT = 10

    def __init__(self):
        super().__init__()
        self.withdraw()
        self.settings = app_core.load_config()
        _translator.set_language(self.settings.get("language", "en"))
        self.apply_theme()
        
        self.msg_queue = queue.Queue()
        self.command_queue = queue.Queue()
        # Notifications wait their turn: the next one shows when the previous one is gone
        self.pending = collections.deque(maxlen=self.QUEUE_LIMIT)
        self.showing = False
        self.next_show_at = 0.0
        self.quitting = False
        
        self.hide_task = None
        self.styled_popup = None
        self.settings_window = None
        self.tray_icon = None
        self.status_text = ""
        self.ncfg = self.settings  # settings of the notification on screen
        self.notify_dark = nstyles.resolve_dark(self.settings.get("theme", "dark"))
        self.mqtt_client = None
        self.mqtt_topic = None
        self.update_available = None
        
        self.setup_mqtt()
        self.check_queues()
        self.check_for_updates(manual=False)
        
    def apply_theme(self):
        theme = self.settings.get("theme", "dark")
        ctk.set_appearance_mode(theme)
        ctk.set_default_color_theme("blue")

    # --- MQTT --------------------------------------------------------------
    def set_status(self, text, level=logging.INFO):
        # Connection state: in the log and in the tray icon tooltip
        self.status_text = text
        log.log(level, "MQTT: %s", text)
        icon = self.tray_icon
        if icon is not None:
            try:
                icon.title = f"PC MQTT Notifier - {text}"[:120]
            except Exception:
                pass

    def setup_mqtt(self):
        old = self.mqtt_client
        self.mqtt_client = None
        if old is not None:
            def _stop():
                try:
                    old.disconnect()
                    old.loop_stop()
                except Exception as e:
                    log.warning("Chiusura del vecchio collegamento MQTT: %s", e)
            # in the background, so a broker that does not answer never blocks the windows
            threading.Thread(target=_stop, daemon=True).start()
        
        cfg = self.settings
        broker = str(cfg.get("mqtt_broker", "")).strip()
        self.mqtt_topic = cfg.get("mqtt_topic")
        if not broker:
            self.set_status(_("status_not_configured", "Not configured: open the settings"), logging.WARNING)
            return
        try:
            # Clean session: messages sent while the PC was off are not wanted
            client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, clean_session=True)
            if cfg.get("mqtt_username"):
                client.username_pw_set(cfg["mqtt_username"], cfg.get("mqtt_password") or None)
            if cfg.get("mqtt_tls"):
                client.tls_set()
            client.reconnect_delay_set(min_delay=1, max_delay=60)
            client.on_connect = self.on_mqtt_connect
            client.on_disconnect = self.on_mqtt_disconnect
            client.on_connect_fail = self.on_mqtt_connect_fail
            client.on_message = self.on_mqtt_message
            # Connects in the background and keeps retrying until the broker answers
            client.connect_async(broker, int(cfg.get("mqtt_port", 1883)), 60)
            client.loop_start()
            self.mqtt_client = client
            self.set_status(_f("status_connecting", "Connecting to {broker}...", broker=broker))
        except Exception as e:
            self.set_status(_f("status_error", "MQTT error: {error}", error=e), logging.ERROR)
            
    def on_mqtt_connect(self, client, userdata, flags, reason_code, properties):
        if client is not self.mqtt_client:
            return
        failed = getattr(reason_code, "is_failure", None)
        if failed is None:
            failed = reason_code != 0
        if failed:
            self.set_status(_f("status_refused", "Refused by the broker: {reason}", reason=reason_code), logging.WARNING)
            return
        client.subscribe(self.mqtt_topic, qos=1)
        self.set_status(_f("status_connected", "Connected to {broker}", broker=self.settings.get("mqtt_broker")))

    def on_mqtt_disconnect(self, client, userdata, flags, reason_code, properties):
        if client is self.mqtt_client:
            self.set_status(_f("status_disconnected", "Not connected ({reason}), retrying", reason=reason_code), logging.WARNING)

    def on_mqtt_connect_fail(self, client, userdata):
        if client is self.mqtt_client:
            self.set_status(_("status_unreachable", "Broker not reachable, retrying"), logging.WARNING)
            
    def on_mqtt_message(self, client, userdata, msg):
        try:
            if msg.retain:
                # kept by the broker from before: not a new notification
                log.info("Messaggio conservato (retained) ignorato su %s", msg.topic)
                return
            if self.mqtt_topic and not mqtt.topic_matches_sub(self.mqtt_topic, msg.topic):
                return
            payload = app_core.parse_payload(msg.payload)
            if payload is None:
                log.info("Payload ignorato su %s", msg.topic)
                return
            self.msg_queue.put(payload)
        except Exception as e:
            log.warning("Errore payload: %s", e)

    # --- Notifications ----------------------------------------------------
    def notification_style(self, cfg=None):
        cfg = cfg if cfg is not None else self.ncfg
        style = cfg.get("notification_style")
        if style not in nstyles.STYLES:
            style = "static" if cfg.get("enable_fluid", True) is False else nstyles.DEFAULT_STYLE
        return style

    def show_notification(self, title, message, icon=None, app_name=None, cfg=None, preview=False):
        # cfg: settings to draw with (the preview passes its own, without changing the app's)
        cfg = cfg if cfg is not None else self.settings
        self.ncfg = cfg
        # Theme checked at every notification, so "system" follows Windows
        self.notify_dark = nstyles.resolve_dark(cfg.get("theme", "dark"))
        self.showing = not preview
        self.close_styled_popup()
        if self.hide_task:
            self.after_cancel(self.hide_task)
            self.hide_task = None
        try:
            self.show_styled_notification(title, message, icon, app_name)
        except Exception:
            log.exception("Notifica non mostrata")
            self.showing = False
            return
        duration_ms = int(float(cfg.get("duration", 5)) * 1000)
        self.hide_task = self.after(duration_ms, self.hide_notification)

    def show_styled_notification(self, title, message, icon, app_name):
        # Every style is one window drawn with Pillow (notification_styles)
        self.styled_popup = StyledPopup(self, self.ncfg, title, message, icon,
                                        app_name or "Home Assistant", self.notify_dark,
                                        on_click=self.hide_notification)

    def close_styled_popup(self):
        if self.styled_popup is not None:
            self.styled_popup.destroy()
            self.styled_popup = None

    def hide_notification(self):
        if self.hide_task:
            self.after_cancel(self.hide_task)
            self.hide_task = None
        if self.showing:
            self.next_show_at = time.monotonic() + 0.3
        self.showing = False
        if self.styled_popup is not None:
            self.styled_popup.start_exit()
            self.styled_popup = None

    # --- Main loop of the queues -------------------------------------------
    def check_queues(self):
        try:
            while True:
                try:
                    cmd = self.command_queue.get_nowait()
                except queue.Empty:
                    break
                self.run_command(cmd)
            while True:
                try:
                    msg = self.msg_queue.get_nowait()
                except queue.Empty:
                    break
                if isinstance(msg, dict):
                    self.pending.append(msg)
            if self.pending and not self.showing and not self.quitting and time.monotonic() >= self.next_show_at:
                msg = self.pending.popleft()
                title = msg.get("title") or _("default_notification_title", "Notification")
                self.show_notification(str(title), str(msg.get("message", "")), icon=msg.get("icon"), app_name=msg.get("app"))
        except Exception:
            log.exception("Errore nel giro delle code")
        finally:
            # always scheduled again: one error must not stop notifications and the tray menu
            if not self.quitting:
                self.after(100, self.check_queues)

    def run_command(self, cmd):
        if cmd == "open_settings":
            win = self.settings_window
            if win is not None and win.winfo_exists():
                win.deiconify()
                win.lift()
                win.focus_force()
            else:
                self.settings_window = SettingsWindow(self, self.settings, self.on_settings_saved, self.on_settings_preview)
        elif cmd == "check_updates":
            self.check_for_updates(manual=True)
        elif cmd == "download_update":
            self.download_and_install_update()
        elif cmd == "quit":
            self.quitting = True
            log.info("Uscita")
            if self.mqtt_client:
                try:
                    self.mqtt_client.disconnect()
                    self.mqtt_client.loop_stop()
                except Exception:
                    pass
            if self.tray_icon is not None:
                try:
                    self.tray_icon.stop()
                except Exception:
                    pass
            self.close_styled_popup()
            self.quit()

    # --- Updates -------------------------------------------------------------
    def app_message(self, title, message):
        self.msg_queue.put({"app": app_core.APP_NAME, "title": title, "message": message})

    def check_for_updates(self, manual=False):
        def _check():
            try:
                response = requests.get(GITHUB_API_URL, timeout=10)
                response.raise_for_status()
                data = response.json()
                latest_version = str(data.get("tag_name", "")).lstrip("vV")
                if app_core.is_newer(latest_version, APP_VERSION):
                    exe_url, sums_url = app_core.pick_installer(data.get("assets", []))
                    if exe_url:
                        self.update_available = (latest_version, exe_url, sums_url)
                        self.app_message(_("update_title", "Update Available"),
                                         _f("update_message", "Version {ver} is available. Go to settings to update.", ver=latest_version))
                        return
                if manual:
                    self.app_message(_("update_title", "Update Available"), _("update_up_to_date", "You are on the latest version."))
            except Exception as e:
                log.warning("Controllo aggiornamenti non riuscito: %s", e)
                if manual:
                    self.app_message(_("update_error", "Update Error"), str(e))
        threading.Thread(target=_check, daemon=True).start()

    def download_and_install_update(self):
        info = self.update_available
        if not info:
            return
        ver, exe_url, sums_url = info
        def _download():
            exe_path = None
            try:
                self.app_message(_("update_title", "Update Available"), _("update_downloading", "Downloading update, please wait..."))
                # The installer runs only if its SHA256 matches SHA256SUMS.txt of the release
                if not sums_url:
                    raise RuntimeError(_("update_no_checksum", "The release has no SHA256SUMS.txt: update not installed."))
                sums = requests.get(sums_url, timeout=15)
                sums.raise_for_status()
                expected = app_core.parse_sha256sums(sums.text).get(app_core.INSTALLER_NAME)
                if not expected:
                    raise RuntimeError(_("update_no_checksum", "The release has no SHA256SUMS.txt: update not installed."))
                fd, exe_path = tempfile.mkstemp(prefix="PC-MQTT-Notifier-Update-", suffix=".exe")
                os.close(fd)
                with requests.get(exe_url, stream=True, timeout=30) as response:
                    response.raise_for_status()
                    with open(exe_path, "wb") as f:
                        for chunk in response.iter_content(65536):
                            f.write(chunk)
                if app_core.sha256_file(exe_path) != expected:
                    raise RuntimeError(_("update_verify_failed", "The downloaded file does not match its SHA256: update not installed."))
                log.info("Aggiornamento %s verificato, avvio dell'installer", ver)
                self.app_message(_("update_title", "Update Available"), _("update_installing", "Installing update, the app will restart shortly."))
                time.sleep(2)
                popen_kwargs = {"env": app_core.clean_subprocess_env()}
                if os.name == "nt":
                    popen_kwargs["creationflags"] = (
                        getattr(subprocess, "DETACHED_PROCESS", 0)
                        | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
                    )
                subprocess.Popen([exe_path, "/SILENT", "/CLOSEAPPLICATIONS"], **popen_kwargs)
                self.command_queue.put("quit")
            except Exception as e:
                log.error("Aggiornamento non riuscito: %s", e)
                if exe_path and os.path.exists(exe_path):
                    try:
                        os.remove(exe_path)
                    except Exception:
                        pass
                self.app_message(_("update_error", "Update Error"), str(e))
        threading.Thread(target=_download, daemon=True).start()

    # --- Settings ----------------------------------------------------------
    def on_settings_preview(self, preview_config):
        # The preview draws with its own settings and does not replace the app's
        cfg = app_core.sanitize_config(preview_config)
        self.show_notification(_("preview_title", "Notification Preview"), _("preview_message", "This is a real-time preview."), cfg=cfg, preview=True)
        
    def on_settings_saved(self, new_config):
        self.settings = app_core.sanitize_config(new_config)
        self.ncfg = self.settings
        try:
            app_core.save_config(self.settings)
        except Exception as e:
            log.error("Salvataggio delle impostazioni non riuscito: %s", e)
            self.app_message(_("settings_save_error", "Settings not saved"), str(e))
        _translator.set_language(self.settings.get("language", "en"))
        self.apply_theme()
        # colours and sizes are rebuilt now, not at the next preview
        self.notify_dark = nstyles.resolve_dark(self.settings.get("theme", "dark"))
        self.setup_mqtt()

def setup_tray(app):
    try:
        image = Image.open(ICON_FILE)
    except Exception:
        image = Image.new('RGB', (64, 64), color = 'black')
        
    def on_settings(icon, item):
        app.command_queue.put("open_settings")
        
    def on_update(icon, item):
        app.command_queue.put("check_updates")
        
    def on_quit(icon, item):
        # the main thread closes everything, the icon too
        app.command_queue.put("quit")

    menu = pystray.Menu(
        item(lambda item: _("tray_settings", "Settings"), on_settings),
        item(lambda item: _("tray_update", "Check for Updates"), on_update),
        item(lambda item: _("tray_quit", "Quit"), on_quit)
    )
    
    title = f"PC MQTT Notifier - {app.status_text}"[:120] if app.status_text else "PC MQTT Notifier"
    icon = pystray.Icon("PC-MQTT-Notifier", image, title, menu=menu)
    app.tray_icon = icon
    icon.run()

if __name__ == "__main__":
    app_core.setup_logging()
    log.info("Avvio PC-MQTT-Notifier %s", APP_VERSION)
    app = MainApplication()
    tray_thread = threading.Thread(target=setup_tray, args=(app,), daemon=True)
    tray_thread.start()
    try:
        app.mainloop()
    except KeyboardInterrupt:
        log.info("Applicazione terminata dall'utente.")
