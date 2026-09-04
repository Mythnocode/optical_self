; Inno Setup script for OpticalMLPlatform
; Build with ISCC from the Inno Setup 6 install dir (see build_installer.bat).

#define MyAppName "OpticalMLPlatform"
#define MyAppDisplayName "激光耦合仿真系统及智能优化平台"
#define MyAppVersion "1.5.6"
#define MyAppPublisher "OpticalMLWorkspace"
#define MyAppExeName "OpticalMLPlatform.exe"

[Setup]
AppId={{0E5F64F4-7E52-4C9C-A1C4-9C3D9004B2E7}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppVerName={#MyAppVersion}
AppPublisher={#MyAppPublisher}
DefaultDirName={localappdata}\Programs\{#MyAppName}
DefaultGroupName={#MyAppName}
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
OutputDir=..\dist\installer
OutputBaseFilename=OpticalMLPlatform_Setup_v{#MyAppVersion}
SetupIconFile=app.ico
UninstallDisplayIcon={app}\{#MyAppExeName}
UninstallDisplayName={#MyAppDisplayName}
Compression=lzma2/ultra64
SolidCompression=yes
WizardStyle=modern
ArchitecturesInstallIn64BitMode=x64compatible
UsePreviousAppDir=yes

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"
Name: "chinesesimplified"; MessagesFile: "compiler:Languages\ChineseSimplified.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked

[Files]
Source: "..\dist\OpticalMLPlatform\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{group}\{cm:UninstallProgram,{#MyAppDisplayName}}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "{cm:LaunchProgram,{#MyAppDisplayName}}"; Flags: nowait postinstall skipifsilent
