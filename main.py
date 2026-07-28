import json
import threading
import queue
import time
import os
import glob
import requests
import subprocess
import tempfile
import sys
import paho.mqtt.client as mqtt
import customtkinter as ctk
from PIL import Image, ImageTk, ImageDraw
import pystray
from pystray import MenuItem as item
import pywinstyles
import hPyT
import colorsys
import tkinter as tk
import math

CONFIG_FILE = "config.json"
ICON_FILE = "icon.png"
ICON_ICO = "icon.ico"
APP_VERSION = "1.0.0"
REPO_NAME = "giosci1994/PC-MQTT-Notifier"
GITHUB_API_URL = f"https://api.github.com/repos/{REPO_NAME}/releases/latest"

class Translator:
    def __init__(self, locale_dir="locales", default_lang="en"):
        self.locale_dir = locale_dir
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

def load_config():
    try:
        with open(CONFIG_FILE, "r") as f:
            return json.load(f)
    except Exception:
        return {
            "mqtt_broker": "192.168.1.100",
            "mqtt_port": 1883,
            "mqtt_username": "",
            "mqtt_password": "",
            "mqtt_topic": "homeassistant/pc_giovanni/notify",
            "duration": 5,
            "position": "top-center",
            "theme": "dark",
            "alpha": 0.94,
            "fps": 50,
            "language": "en"
        }

def save_config(config):
    with open(CONFIG_FILE, "w") as f:
        json.dump(config, f, indent=2)

class SettingsWindow(ctk.CTkToplevel):
    def __init__(self, parent, current_config, on_save, on_preview):
        super().__init__(parent)
        self.main_app = parent
        self.title(_("settings_title", "PC-MQTT-Notifier Settings"))
        self.geometry("450x970")
        
        if os.path.exists(ICON_ICO):
            self.after(200, lambda: self.iconbitmap(ICON_ICO))
            
        self.current_config = current_config.copy()
        self.on_save_callback = on_save
        self.on_preview_callback = on_preview
        self.attributes("-topmost", True)
        self.protocol("WM_DELETE_WINDOW", self.on_close)
        
        pywinstyles.apply_style(self, "mica")
        
        is_dark = current_config.get("theme", "dark") == "dark"
        self.configure(fg_color="#1c1c1e" if is_dark else "#f3f3f3")
        
        self.grid_columnconfigure(1, weight=1)
        
        title_font = ctk.CTkFont(family="Segoe UI Variable Display", size=24, weight="bold")
        label_font = ctk.CTkFont(family="Segoe UI Variable Text", size=14)
        
        ctk.CTkLabel(self, text="Rete MQTT", font=title_font).grid(row=0, column=0, columnspan=2, pady=(25, 10), sticky="w", padx=25)
        
        self.create_entry(_("mqtt_broker", "Broker IP:"), 1, "mqtt_broker", label_font)
        self.create_entry(_("mqtt_port", "Porta:"), 2, "mqtt_port", label_font, default="1883")
        self.create_entry(_("mqtt_username", "Username:"), 3, "mqtt_username", label_font)
        self.create_entry(_("mqtt_password", "Password:"), 4, "mqtt_password", label_font, show="*")
        self.create_entry(_("mqtt_topic", "Topic:"), 5, "mqtt_topic", label_font)
        
        ctk.CTkLabel(self, text="Aspetto e Notifiche", font=title_font).grid(row=6, column=0, columnspan=2, pady=(30, 10), sticky="w", padx=25)
        
        ctk.CTkLabel(self, text=_("language", "Lingua:"), font=label_font).grid(row=7, column=0, padx=(25, 10), pady=8, sticky="e")
        self.e_language = ctk.CTkOptionMenu(self, values=_translator.available_langs, font=label_font)
        self.e_language.set(current_config.get("language", "en"))
        self.e_language.grid(row=7, column=1, padx=(0, 25), pady=8, sticky="ew")
        
        self.create_entry(_("duration", "Durata (sec):"), 8, "duration", label_font, default="5")
        
        ctk.CTkLabel(self, text=_("position", "Posizione:"), font=label_font).grid(row=9, column=0, padx=(25, 10), pady=8, sticky="e")
        self.e_position = ctk.CTkOptionMenu(self, values=["top-center", "bottom-right", "top-right", "bottom-center"], font=label_font)
        self.e_position.set(current_config.get("position", "top-center"))
        self.e_position.grid(row=9, column=1, padx=(0, 25), pady=8, sticky="ew")
        
        ctk.CTkLabel(self, text=_("theme", "Tema:"), font=label_font).grid(row=10, column=0, padx=(25, 10), pady=8, sticky="e")
        self.e_theme = ctk.CTkOptionMenu(self, values=["dark", "light"], font=label_font)
        self.e_theme.set(current_config.get("theme", "dark"))
        self.e_theme.grid(row=10, column=1, padx=(0, 25), pady=8, sticky="ew")
        
        ctk.CTkLabel(self, text=_("alpha", "Trasparenza:"), font=label_font).grid(row=11, column=0, padx=(25, 10), pady=8, sticky="e")
        self.e_alpha = ctk.CTkSlider(self, from_=0.2, to=1.0, number_of_steps=80)
        self.e_alpha.set(current_config.get("alpha", 0.94))
        self.e_alpha.grid(row=11, column=1, padx=(0, 25), pady=8, sticky="ew")
        
        ctk.CTkLabel(self, text=_("fps", "Fluidità (FPS):"), font=label_font).grid(row=12, column=0, padx=(25, 10), pady=8, sticky="e")
        self.e_fps = ctk.CTkSlider(self, from_=10, to=120, number_of_steps=110)
        self.e_fps.set(current_config.get("fps", 50))
        self.e_fps.grid(row=12, column=1, padx=(0, 25), pady=8, sticky="ew")
        
        ctk.CTkLabel(self, text=_("corner_radius", "Arrotondamento Angoli:"), font=label_font).grid(row=13, column=0, padx=(25, 10), pady=8, sticky="e")
        self.e_corner = ctk.CTkSlider(self, from_=0, to=65, number_of_steps=65)
        self.e_corner.set(current_config.get("corner_radius", 30))
        self.e_corner.grid(row=13, column=1, padx=(0, 25), pady=8, sticky="ew")
        
        ctk.CTkLabel(self, text=_("enable_fluid", "Sfondo Fluido:"), font=label_font).grid(row=14, column=0, padx=(25, 10), pady=8, sticky="e")
        self.e_fluid = ctk.CTkSwitch(self, text="", font=label_font)
        if current_config.get("enable_fluid", True):
            self.e_fluid.select()
        else:
            self.e_fluid.deselect()
        self.e_fluid.grid(row=14, column=1, padx=(0, 25), pady=8, sticky="w")
        
        ctk.CTkLabel(self, text=_("scale", "Grandezza Notifica:"), font=label_font).grid(row=15, column=0, padx=(25, 10), pady=8, sticky="e")
        self.e_scale = ctk.CTkSlider(self, from_=0.7, to=1.5, number_of_steps=80)
        self.e_scale.set(current_config.get("scale", 1.0))
        self.e_scale.grid(row=15, column=1, padx=(0, 25), pady=8, sticky="ew")
        
        self.btn_test = ctk.CTkButton(self, text=_("btn_preview", "Mostra Anteprima Notifica"), font=ctk.CTkFont(family="Segoe UI Variable Text", size=15), height=40, corner_radius=10, fg_color="transparent", border_width=1, command=self.preview)
        self.btn_test.grid(row=16, column=0, columnspan=2, pady=(25, 0), padx=40, sticky="ew")
        
        self.btn_save = ctk.CTkButton(self, text=_("btn_save", "Salva e Applica"), font=ctk.CTkFont(family="Segoe UI Variable Text", size=15, weight="bold"), height=40, corner_radius=10, command=self.save)
        self.btn_save.grid(row=17, column=0, columnspan=2, pady=(15, 20), padx=40, sticky="ew")
        
        if getattr(self.main_app, 'update_available', None):
            ver, url = self.main_app.update_available
            self.btn_update = ctk.CTkButton(self, text=_("btn_update", f"Aggiorna a {ver}"), font=ctk.CTkFont(family="Segoe UI Variable Text", size=15, weight="bold"), height=40, corner_radius=10, fg_color="#28a745", hover_color="#218838", command=lambda: self.main_app.command_queue.put(f"download_update:{url}"))
            self.btn_update.grid(row=18, column=0, columnspan=2, pady=(0, 20), padx=40, sticky="ew")

    def create_entry(self, label_text, row, config_key, font, show="", default=""):
        ctk.CTkLabel(self, text=label_text, font=font).grid(row=row, column=0, padx=(25, 10), pady=8, sticky="e")
        entry = ctk.CTkEntry(self, show=show, font=font, height=35, corner_radius=8, border_width=1)
        val = self.current_config.get(config_key, default)
        entry.insert(0, str(val))
        entry.grid(row=row, column=1, padx=(0, 25), pady=8, sticky="ew")
        setattr(self, f"e_{config_key}", entry)
        
    def preview(self):
        try:
            preview_config = {
                "mqtt_broker": self.e_mqtt_broker.get(),
                "mqtt_port": int(self.e_mqtt_port.get()),
                "mqtt_username": self.e_mqtt_username.get(),
                "mqtt_password": self.e_mqtt_password.get(),
                "mqtt_topic": self.e_mqtt_topic.get(),
                "duration": 99999, # Molto lungo per fare da preview persistente
                "position": self.e_position.get(),
                "theme": self.e_theme.get(),
                "alpha": float(self.e_alpha.get()),
                "fps": int(self.e_fps.get()),
                "corner_radius": int(self.e_corner.get()),
                "enable_fluid": bool(self.e_fluid.get()),
                "scale": float(self.e_scale.get()),
                "language": self.e_language.get()
            }
            self.on_preview_callback(preview_config)
        except Exception:
            pass

    def save(self):
        new_config = {
            "mqtt_broker": self.e_mqtt_broker.get(),
            "mqtt_port": int(self.e_mqtt_port.get()),
            "mqtt_username": self.e_mqtt_username.get(),
            "mqtt_password": self.e_mqtt_password.get(),
            "mqtt_topic": self.e_mqtt_topic.get(),
            "duration": int(self.e_duration.get()),
            "position": self.e_position.get(),
            "theme": self.e_theme.get(),
            "alpha": float(self.e_alpha.get()),
            "fps": int(self.e_fps.get()),
            "corner_radius": int(self.e_corner.get()),
            "enable_fluid": bool(self.e_fluid.get()),
            "scale": float(self.e_scale.get()),
            "language": self.e_language.get()
        }
        self.on_save_callback(new_config)
        self.main_app.hide_notification()
        self.destroy()

    def on_close(self):
        self.on_preview_callback(self.current_config)
        self.main_app.hide_notification()
        self.destroy()

class MainApplication(ctk.CTk):
    def __init__(self):
        super().__init__()
        self.withdraw()
        self.config = load_config()
        _translator.set_language(self.config.get("language", "en"))
        self.apply_theme()
        
        self.msg_queue = queue.Queue()
        self.command_queue = queue.Queue()
        
        self.notify_window = None
        self.hide_task = None
        self.rainbow_task = None
        self.rainbow_base = None
        self.rainbow_offset = 0
        self.mqtt_client = None
        
        self.generate_rainbow_base()
        self.setup_mqtt()
        self.check_queues()
        self.update_available = None
        self.check_for_updates(manual=False)
        
    def apply_theme(self):
        theme = self.config.get("theme", "dark")
        ctk.set_appearance_mode(theme)
        ctk.set_default_color_theme("blue")
        
    def setup_mqtt(self):
        if self.mqtt_client:
            self.mqtt_client.loop_stop()
            self.mqtt_client.disconnect()
            
        self.mqtt_client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
        if self.config.get("mqtt_username") and self.config.get("mqtt_password"):
            self.mqtt_client.username_pw_set(self.config["mqtt_username"], self.config["mqtt_password"])

        self.mqtt_client.on_connect = self.on_mqtt_connect
        self.mqtt_client.on_message = self.on_mqtt_message

        try:
            self.mqtt_client.connect(self.config["mqtt_broker"], self.config["mqtt_port"], 60)
            self.mqtt_client.loop_start()
        except Exception as e:
            print(f"Errore connessione MQTT: {e}")
            
    def on_mqtt_connect(self, client, userdata, flags, reason_code, properties):
        if reason_code == 0:
            print(f"Connesso al broker MQTT: {self.config['mqtt_broker']}")
            client.subscribe(self.config['mqtt_topic'])
            
    def on_mqtt_message(self, client, userdata, msg):
        try:
            payload = json.loads(msg.payload.decode())
            self.msg_queue.put(payload)
        except Exception as e:
            print(f"Errore payload: {e}")

    def generate_rainbow_base(self):
        # Generiamo una mappa di "Rumore 2D" organica a bassa risoluzione (super veloce)
        w, h = 150, 150
        base = Image.new("RGB", (w, h))
        pixels = base.load()
        
        is_dark = self.config.get("theme", "dark") == "dark"
        
        if self.config.get("enable_fluid", True):
            for x in range(w):
                for y in range(h):
                    # Onde matematiche incrociate per creare un fluido
                    nx = x / 25.0
                    ny = y / 25.0
                    v = math.sin(nx + ny) + math.sin(nx * 0.6 - ny * 1.2) + math.cos(nx * 0.9 + ny * 0.7)
                    val = (v + 3) / 6.0 # Normalizzato ~ 0-1
                    
                    # Mappiamo il fluido in un gradiente di colori
                    hue = (val * 1.5) % 1.0
                    
                    if is_dark:
                        # Colori profondi tipo aurora boreale
                        r, g, b = colorsys.hsv_to_rgb(hue, 0.65, 0.35)
                    else:
                        # Colori pastello fluidi, stile mesh gradient
                        r, g, b = colorsys.hsv_to_rgb(hue, 0.45, 0.98)
                        
                    pixels[x, y] = (int(r*255), int(g*255), int(b*255))
                    
            # Ingrandiamo l'immagine con filtro Bicubic per creare una sfumatura "Mesh Gradient" perfetta e fluidissima
            self.rainbow_base = base.resize((1200, 600), Image.Resampling.BICUBIC)
        else:
            color = (25, 25, 25) if is_dark else (240, 240, 240)
            self.rainbow_base = Image.new("RGB", (1200, 600), color)
                
        # Maschera a pillola per ritagliare gli angoli
        scale = float(self.config.get("scale", 1.0))
        width = int(420 * scale)
        height = int(135 * scale)
        radius = int(self.config.get("corner_radius", 30) * scale)
        self.pill_mask = Image.new("L", (width, height), 0)
        draw = ImageDraw.Draw(self.pill_mask)
        draw.rounded_rectangle((0, 0, width, height), radius=radius, fill=255)

    def create_notification_window(self):
        if hasattr(self, 'fade_task') and self.fade_task:
            self.after_cancel(self.fade_task)
            self.fade_task = None
            
        if self.notify_window is not None:
            self.notify_window.destroy()
            
        self.notify_window = ctk.CTkToplevel(self)
        self.notify_window.overrideredirect(True)
        self.notify_window.attributes("-topmost", True)
        self.notify_window.attributes("-alpha", 0.0)
        
        scale = float(self.config.get("scale", 1.0))
        
        if self.config.get("enable_fluid", True):
            self.notify_window.configure(fg_color="#000001")
            if os.name == 'nt':
                self.notify_window.wm_attributes("-transparentcolor", "#000001")
            
            self.width = int(420 * scale)
            self.height = int(135 * scale)
            
            # Usiamo tk.Canvas per permettere di avere testi trasparenti direttamente sull'immagine!
            self.canvas = tk.Canvas(self.notify_window, width=self.width, height=self.height, bg="#000001", highlightthickness=0)
            self.canvas.pack(fill="both", expand=True)
            
            # Immagine di base per il canvas
            self.tk_img = ImageTk.PhotoImage(Image.new("RGB", (self.width, self.height), (0, 0, 1)))
            self.img_id = self.canvas.create_image(0, 0, anchor="nw", image=self.tk_img)
            
            is_dark = self.config.get("theme", "dark") == "dark"
            text_color = "#ffffff" if is_dark else "#000000"
            subtext_color = "#e5e5ea" if is_dark else "#333333"
            
            title_font = ("Segoe UI Variable Display", int(18 * scale), "bold")
            msg_font = ("Segoe UI Variable Text", int(15 * scale))
            
            # Testi scritti direttamente sull'immagine (niente background box grigi!)
            self.title_id = self.canvas.create_text(int(30 * scale), int(32 * scale), text="", font=title_font, fill=text_color, anchor="w")
            self.msg_id = self.canvas.create_text(int(30 * scale), int(62 * scale), text="", font=msg_font, fill=subtext_color, anchor="nw", width=int(360 * scale))
        else:
            # Vecchio stile con box nativo CTk (backup)
            if os.name == 'nt':
                self.notify_window.wm_attributes("-transparentcolor", "#000001")
                self.notify_window.configure(fg_color="#000001")
                
            bg_color = "#1c1c1e" if self.config.get("theme", "dark") == "dark" else "#f2f2f7"
            text_color = "#ffffff" if self.config.get("theme", "dark") == "dark" else "#000000"
            subtext_color = "#a1a1a6" if self.config.get("theme", "dark") == "dark" else "#3c3c43"
            border_color = "#3a3a3c" if self.config.get("theme", "dark") == "dark" else "#c6c6c8"
            
            self.width = int(380 * scale)
            self.height = int(95 * scale)
            
            radius = int(self.config.get("corner_radius", 30))
            if radius > 45: radius = 45 # Limite CTkFrame
            
            self.frame = ctk.CTkFrame(self.notify_window, fg_color=bg_color, corner_radius=radius, border_width=1, border_color=border_color)
            self.frame.pack(fill="both", expand=True, padx=2, pady=2)
            
            self.title_label = ctk.CTkLabel(self.frame, text="", font=ctk.CTkFont(size=int(16 * scale), weight="bold"), text_color=text_color)
            self.title_label.pack(pady=(int(12 * scale), 2), padx=int(18 * scale), anchor="w")
            
            self.message_label = ctk.CTkLabel(self.frame, text="", font=ctk.CTkFont(size=int(14 * scale)), text_color=subtext_color, justify="left", wraplength=int(340 * scale))
            self.message_label.pack(pady=(0, int(10 * scale)), padx=int(18 * scale), anchor="w")
        
        screen_width = self.winfo_screenwidth()
        screen_height = self.winfo_screenheight()
        
        margin = 35
        pos = self.config.get("position", "top-center")
        
        if pos == "top-center":
            x = (screen_width / 2) - (self.width / 2)
            y = margin
        elif pos == "bottom-right":
            x = screen_width - self.width - margin
            y = screen_height - self.height - margin - 40
        elif pos == "top-right":
            x = screen_width - self.width - margin
            y = margin
        else: # bottom-center
            x = (screen_width / 2) - (self.width / 2)
            y = screen_height - self.height - margin - 40
            
        self.notify_window.geometry(f'{self.width}x{self.height}+{int(x)}+{int(y)}')

    def animate_rainbow(self):
        if self.notify_window and self.notify_window.winfo_exists():
            scale = float(self.config.get("scale", 1.0))
            width = int(420 * scale)
            height = int(135 * scale)
            
            # Calcoliamo una traiettoria fluida usando curve di Lissajous (il tempo guida il movimento)
            t = time.time() * 0.4 
            
            # Centro dell'immagine gigante e raggio di movimento
            cx, cy = 600 - (width / 2), 300 - (height / 2)
            rx, ry = (1200 - width) / 2 - 10, (600 - height) / 2 - 10
            
            # Movimento fluido e organico nelle direzioni X e Y
            offset_x = int(cx + math.sin(t) * rx)
            offset_y = int(cy + math.cos(t * 0.8) * ry)
            
            # Ritagliamo l'inquadratura corrente dal grande sfondo fluido
            cropped = self.rainbow_base.crop((offset_x, offset_y, offset_x + width, offset_y + height))
            
            # Applichiamo la maschera per gli angoli arrotondati
            final_img = Image.new("RGB", (width, height), (0, 0, 1))
            final_img.paste(cropped, (0, 0), self.pill_mask)
            
            # Aggiorniamo il canvas
            self.tk_img = ImageTk.PhotoImage(final_img)
            self.canvas.itemconfig(self.img_id, image=self.tk_img)
            
            # Aggiornamento in base agli FPS
            fps = self.config.get("fps", 50)
            delay = int(1000 / fps) if fps > 0 else 20
            self.rainbow_task = self.after(delay, self.animate_rainbow)

    def show_notification(self, title, message):
        self.create_notification_window()
        
        if self.config.get("enable_fluid", True):
            self.canvas.itemconfig(self.title_id, text=title)
            self.canvas.itemconfig(self.msg_id, text=message)
            self.rainbow_offset = 0
            self.animate_rainbow()
        else:
            self.title_label.configure(text=title)
            self.message_label.configure(text=message)
        
        # Animazione Fade-in con effetto vetro (alpha)
        target_alpha = self.config.get("alpha", 0.94)
        def fade_in(alpha=0.0):
            if not self.notify_window or not self.notify_window.winfo_exists():
                return
            if alpha < target_alpha:
                alpha += 0.15
                if alpha > target_alpha:
                    alpha = target_alpha
                self.notify_window.attributes("-alpha", alpha)
                self.fade_task = self.after(20, lambda: fade_in(alpha))
            else:
                self.notify_window.attributes("-alpha", target_alpha)
                
        fade_in()
        
        if self.hide_task:
            self.after_cancel(self.hide_task)
            
        duration_ms = self.config.get("duration", 5) * 1000
        self.hide_task = self.after(duration_ms, self.hide_notification)

    def hide_notification(self):
        if self.rainbow_task:
            self.after_cancel(self.rainbow_task)
            self.rainbow_task = None
            
        if self.notify_window:
            def fade_out(alpha=0.92):
                if not self.notify_window or not self.notify_window.winfo_exists():
                    return
                if alpha > 0.0:
                    alpha -= 0.15
                    self.notify_window.attributes("-alpha", alpha)
                    self.fade_task = self.after(20, lambda: fade_out(alpha))
                else:
                    self.notify_window.destroy()
                    self.notify_window = None
            fade_out()
        self.hide_task = None

    def check_queues(self):
        try:
            cmd = self.command_queue.get_nowait()
            if cmd == "open_settings":
                SettingsWindow(self, self.config, self.on_settings_saved, self.on_settings_preview)
            elif cmd == "check_updates":
                self.check_for_updates(manual=True)
            elif cmd.startswith("download_update:"):
                url = cmd.split(":", 1)[1]
                self.download_and_install_update(url)
            elif cmd == "quit":
                if self.mqtt_client:
                    self.mqtt_client.loop_stop()
                self.quit()
        except queue.Empty:
            pass

        try:
            msg = self.msg_queue.get_nowait()
            if msg:
                self.show_notification(msg.get("title", _("default_notification_title", "Notifica")), msg.get("message", ""))
        except queue.Empty:
            pass
            
        self.after(100, self.check_queues)

    def check_for_updates(self, manual=False):
        def _check():
            try:
                response = requests.get(GITHUB_API_URL, timeout=5)
                if response.status_code == 200:
                    data = response.json()
                    latest_version = data.get("tag_name", "").lstrip('v')
                    if not latest_version: return
                    
                    current = tuple(map(int, APP_VERSION.split(".")))
                    latest = tuple(map(int, latest_version.split(".")))
                    
                    if latest > current:
                        download_url = None
                        for asset in data.get("assets", []):
                            if asset.get("name", "").endswith(".exe"):
                                download_url = asset.get("browser_download_url")
                                break
                        
                        if download_url:
                            self.update_available = (latest_version, download_url)
                            self.msg_queue.put({
                                "title": _("update_title", "Aggiornamento Disponibile!"),
                                "message": _("update_message", f"Versione {latest_version} disponibile. Vai nelle impostazioni per aggiornare.")
                            })
                    else:
                        if manual:
                            self.msg_queue.put({
                                "title": _("update_title", "Aggiornamento"),
                                "message": _("update_up_to_date", "Sei all'ultima versione disponibile.")
                            })
            except Exception as e:
                print("Update check failed:", e)
        threading.Thread(target=_check, daemon=True).start()

    def download_and_install_update(self, url):
        def _download():
            try:
                self.msg_queue.put({
                    "title": _("update_title", "Aggiornamento"),
                    "message": _("update_downloading", "Download in corso, attendere...")
                })
                response = requests.get(url, stream=True, timeout=10)
                if response.status_code == 200:
                    exe_path = os.path.join(tempfile.gettempdir(), "PC-MQTT-Notifier-Update.exe")
                    with open(exe_path, "wb") as f:
                        for chunk in response.iter_content(1024):
                            f.write(chunk)
                    
                    self.msg_queue.put({
                        "title": _("update_title", "Aggiornamento"),
                        "message": _("update_installing", "Installazione in corso, l'app si riavvierà.")
                    })
                    time.sleep(2)
                    
                    subprocess.Popen([exe_path, "/SILENT"])
                    self.command_queue.put("quit")
            except Exception as e:
                self.msg_queue.put({
                    "title": _("update_error", "Errore Aggiornamento"),
                    "message": str(e)
                })
        threading.Thread(target=_download, daemon=True).start()

    def on_settings_preview(self, preview_config):
        # Genera una notifica di preview
        self.config = preview_config
        _translator.set_language(preview_config.get("language", "en"))
        self.generate_rainbow_base() # Ricalcola la maschera degli angoli e i colori
            
        self.show_notification(_("preview_title", "Anteprima Notifica"), _("preview_message", "Questa è un'anteprima in tempo reale."))
        
    def on_settings_saved(self, new_config):
        self.config = new_config
        save_config(self.config)
        _translator.set_language(self.config.get("language", "en"))
        self.apply_theme()
        self.setup_mqtt()

def setup_tray(command_queue):
    try:
        image = Image.open(ICON_FILE)
    except:
        image = Image.new('RGB', (64, 64), color = 'black')
        
    def on_settings(icon, item):
        command_queue.put("open_settings")
        
    def on_update(icon, item):
        command_queue.put("check_updates")
        
    def on_quit(icon, item):
        icon.stop()
        command_queue.put("quit")

    menu = pystray.Menu(
        item(lambda item: _("tray_settings", "Impostazioni"), on_settings),
        item(lambda item: _("tray_update", "Verifica Aggiornamenti"), on_update),
        item(lambda item: _("tray_quit", "Esci"), on_quit)
    )
    
    icon = pystray.Icon("PC-MQTT-Notifier", image, "PC MQTT Notifier", menu=menu)
    icon.run()

if __name__ == "__main__":
    app = MainApplication()
    tray_thread = threading.Thread(target=setup_tray, args=(app.command_queue,), daemon=True)
    tray_thread.start()
    try:
        app.mainloop()
    except KeyboardInterrupt:
        print("\nApplicazione terminata dall'utente.")
