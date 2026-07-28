import json
import threading
import queue
import paho.mqtt.client as mqtt
import customtkinter as ctk

# Caricamento configurazione
try:
    with open("config.json", "r") as f:
        config = json.load(f)
except FileNotFoundError:
    print("Errore: file config.json non trovato.")
    exit(1)

ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("blue")

class NotificationApp(ctk.CTk):
    def __init__(self):
        super().__init__()
        
        self.msg_queue = queue.Queue()
        
        # Dimensioni della notifica
        self.width = 380
        self.height = 95
        
        # Impostazioni per finestra trasparente senza bordi
        self.overrideredirect(True)
        self.wm_attributes("-transparentcolor", "#000001") # Colore reso trasparente da Windows
        self.configure(fg_color="#000001")
        self.attributes("-topmost", True)
        self.attributes("-alpha", 0.0) # Inizialmente invisibile
        
        # Container arrotondato
        self.frame = ctk.CTkFrame(self, fg_color="#1c1c1e", corner_radius=15, border_width=1, border_color="#3a3a3c")
        self.frame.pack(fill="both", expand=True, padx=2, pady=2)
        
        # Titolo
        self.title_label = ctk.CTkLabel(self.frame, text="", font=ctk.CTkFont(size=16, weight="bold"), text_color="#ffffff")
        self.title_label.pack(pady=(12, 2), padx=18, anchor="w")
        
        # Messaggio
        self.message_label = ctk.CTkLabel(self.frame, text="", font=ctk.CTkFont(size=14), text_color="#a1a1a6", justify="left", wraplength=340)
        self.message_label.pack(pady=(0, 10), padx=18, anchor="w")
        
        self.center_window()
        self.hide_task = None
        self.check_queue()

    def center_window(self):
        screen_width = self.winfo_screenwidth()
        x = (screen_width / 2) - (self.width / 2)
        y = 20 # Distanza dal bordo superiore
        self.geometry(f'{self.width}x{self.height}+{int(x)}+{int(y)}')

    def show_notification(self, title, message):
        self.title_label.configure(text=title)
        self.message_label.configure(text=message)
        self.attributes("-alpha", 0.95)
        
        if self.hide_task:
            self.after_cancel(self.hide_task)
        self.hide_task = self.after(6000, self.hide_notification)

    def hide_notification(self):
        self.attributes("-alpha", 0.0)
        self.hide_task = None

    def check_queue(self):
        try:
            msg = self.msg_queue.get_nowait()
            if msg:
                self.show_notification(msg.get("title", "Notifica"), msg.get("message", ""))
        except queue.Empty:
            pass
        self.after(100, self.check_queue)

app = NotificationApp()

def on_connect(client, userdata, flags, reason_code, properties):
    if reason_code == 0:
        print(f"Connesso al broker MQTT: {config['mqtt_broker']}")
        client.subscribe(config['mqtt_topic'])
    else:
        print(f"Connessione fallita. Codice: {reason_code}")

def on_message(client, userdata, msg):
    try:
        payload = json.loads(msg.payload.decode())
        app.msg_queue.put(payload)
    except Exception as e:
        print(f"Errore decodifica payload: {e}")

mqtt_client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
if config.get("mqtt_username") and config.get("mqtt_password"):
    mqtt_client.username_pw_set(config["mqtt_username"], config["mqtt_password"])

mqtt_client.on_connect = on_connect
mqtt_client.on_message = on_message

try:
    mqtt_client.connect(config["mqtt_broker"], config["mqtt_port"], 60)
    mqtt_client.loop_start()
except Exception as e:
    print(f"Errore connessione MQTT: {e}")

app.mainloop()
