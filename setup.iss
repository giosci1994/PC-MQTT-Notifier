[Setup]
AppName=PC-MQTT-Notifier
AppVersion=2.0
DefaultDirName={autopf}\PC-MQTT-Notifier
DefaultGroupName=PC-MQTT-Notifier
OutputBaseFilename=PC-MQTT-Notifier-Setup
Compression=lzma2
SolidCompression=yes
ArchitecturesInstallIn64BitMode=x64
PrivilegesRequired=lowest
SetupIconFile=icon.ico
UninstallDisplayIcon={app}\PC-MQTT-Notifier.exe

[Files]
Source: "dist\PC-MQTT-Notifier.exe"; DestDir: "{app}"; Flags: ignoreversion
Source: "icon.png"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{group}\PC-MQTT-Notifier"; Filename: "{app}\PC-MQTT-Notifier.exe"
Name: "{autostartup}\PC-MQTT-Notifier"; Filename: "{app}\PC-MQTT-Notifier.exe"; Tasks: autostart

[Tasks]
Name: "autostart"; Description: "Avvia automaticamente con Windows / Run automatically on Windows startup"; GroupDescription: "Avvio / Startup:"

[Run]
Filename: "{app}\PC-MQTT-Notifier.exe"; Description: "Avvia / Launch PC-MQTT-Notifier"; Flags: nowait postinstall skipifsilent
