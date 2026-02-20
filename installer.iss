#define MyAppName "Serviskynet Control Empresarial"
#define MyAppVersion "1.0.0"
#define MyAppPublisher "SERVISKYNET TELECOMUNICACIONES S.A.S."
#define MyAppExeName "ServiskynetControl.exe"

[Setup]
AppId={{7A773ED8-0EA3-4958-87AF-18D34DE0BC45}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
DefaultDirName={localappdata}\Programs\ServiskynetControl
DefaultGroupName=Serviskynet Control
OutputDir=dist\installer
OutputBaseFilename=Instalador_ServiskynetControl
Compression=lzma
SolidCompression=yes
WizardStyle=modern
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
DisableProgramGroupPage=yes
UninstallDisplayIcon={app}\{#MyAppExeName}

[Languages]
Name: "spanish"; MessagesFile: "compiler:Languages\Spanish.isl"

[Tasks]
Name: "desktopicon"; Description: "Crear acceso directo en el escritorio"; GroupDescription: "Accesos directos:"; Flags: unchecked

[Files]
Source: "dist\ServiskynetControl\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "iniciar_serviskynet.bat"; DestDir: "{app}"; Flags: ignoreversion
Source: "detener_serviskynet.bat"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{autoprograms}\Abrir Serviskynet Control"; Filename: "{app}\iniciar_serviskynet.bat"; WorkingDir: "{app}"
Name: "{autoprograms}\Detener Serviskynet Control"; Filename: "{app}\detener_serviskynet.bat"; WorkingDir: "{app}"
Name: "{autodesktop}\Serviskynet Control"; Filename: "{app}\iniciar_serviskynet.bat"; WorkingDir: "{app}"; Tasks: desktopicon

[Run]
Filename: "{app}\iniciar_serviskynet.bat"; Description: "Abrir Serviskynet Control ahora"; Flags: nowait postinstall skipifsilent
