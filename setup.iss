; The CI passes the version from the git tag: iscc /DMyAppVersion=1.2.3 setup.iss
#ifndef MyAppVersion
  #define MyAppVersion "1.1.1"
#endif

[Setup]
AppName=PC-MQTT-Notifier
AppVersion={#MyAppVersion}
DefaultDirName={autopf}\PC-MQTT-Notifier
DefaultGroupName=PC-MQTT-Notifier
OutputBaseFilename=PC-MQTT-Notifier-Setup
Compression=lzma2
SolidCompression=yes
ArchitecturesInstallIn64BitMode=x64
PrivilegesRequired=lowest
SetupIconFile=icon.ico
UninstallDisplayIcon={app}\PC-MQTT-Notifier.exe
; Close the running app before replacing it (also for the silent auto-update)
CloseApplications=force

[Files]
Source: "dist\PC-MQTT-Notifier\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\PC-MQTT-Notifier"; Filename: "{app}\PC-MQTT-Notifier.exe"; WorkingDir: "{app}"
Name: "{autostartup}\PC-MQTT-Notifier"; Filename: "{app}\PC-MQTT-Notifier.exe"; WorkingDir: "{app}"; Tasks: autostart

[Tasks]
Name: "autostart"; Description: "Avvia automaticamente con Windows / Run automatically on Windows startup"; GroupDescription: "Avvio / Startup:"

[Run]
Filename: "{app}\PC-MQTT-Notifier.exe"; Description: "Avvia / Launch PC-MQTT-Notifier"; Flags: nowait postinstall skipifsilent
; Silent install (the in-app update): start the app again by itself
Filename: "{app}\PC-MQTT-Notifier.exe"; Flags: nowait; Check: WizardSilent
