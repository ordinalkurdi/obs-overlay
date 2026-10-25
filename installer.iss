; Inno Setup script - builds ObsOverlay-Setup-<version>.exe from the PyInstaller output in dist\ObsOverlay
#ifndef MyAppVersion
  #define MyAppVersion "0.1.0"
#endif

[Setup]
AppId={{A7A4EDBB-5CD6-4645-9D3C-E99A5433F56C}
AppName=OBS Overlay
AppVersion={#MyAppVersion}
AppPublisher=OBS Overlay contributors
DefaultDirName={autopf}\OBS Overlay
DefaultGroupName=OBS Overlay
DisableProgramGroupPage=yes
OutputDir=installer_output
OutputBaseFilename=ObsOverlay-Setup-{#MyAppVersion}
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
UninstallDisplayIcon={app}\ObsOverlay.exe
CloseApplications=yes

[Tasks]
Name: "desktopicon"; Description: "Create a desktop shortcut"; Flags: unchecked
Name: "startup"; Description: "Start OBS Overlay when Windows starts (tray only)"; Flags: unchecked

[Files]
Source: "dist\ObsOverlay\*"; DestDir: "{app}"; Flags: recursesubdirs createallsubdirs ignoreversion

[Icons]
Name: "{autoprograms}\OBS Overlay"; Filename: "{app}\ObsOverlay.exe"
Name: "{autodesktop}\OBS Overlay"; Filename: "{app}\ObsOverlay.exe"; Tasks: desktopicon
Name: "{userstartup}\OBS Overlay"; Filename: "{app}\ObsOverlay.exe"; Tasks: startup

[Run]
Filename: "{app}\ObsOverlay.exe"; Description: "Launch OBS Overlay"; Flags: nowait postinstall skipifsilent
