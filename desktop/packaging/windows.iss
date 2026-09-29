; Compile after PyInstaller with Inno Setup 6 (ISCC.exe).
#ifndef AppVersion
  #define AppVersion "0.2.0"
#endif
#ifndef SourceRoot
  #define SourceRoot ".."
#endif
[Setup]
AppId={{AB2399D4-61B6-4F5A-8531-256817D9D1B0}
AppName=MKV Profile Converter
AppVersion={#AppVersion}
AppPublisher=MKV Profile Converter contributors
DefaultDirName={localappdata}\Programs\MKV Profile Converter
DefaultGroupName=MKV Profile Converter
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
LicenseFile={#SourceRoot}\LICENSE
OutputDir={#SourceRoot}\dist
OutputBaseFilename=MKV-Profile-Converter-Windows-x86_64-Setup
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
UninstallDisplayIcon={app}\MKVProfileConverter.exe
CloseApplications=yes
RestartApplications=no
[Tasks]
Name: "desktopicon"; Description: "Create a desktop shortcut"; GroupDescription: "Additional shortcuts:"; Flags: unchecked
[Files]
Source: "{#SourceRoot}\dist\MKVProfileConverter\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
[Icons]
Name: "{group}\MKV Profile Converter"; Filename: "{app}\MKVProfileConverter.exe"
Name: "{autodesktop}\MKV Profile Converter"; Filename: "{app}\MKVProfileConverter.exe"; Tasks: desktopicon
[Run]
Filename: "{app}\MKVProfileConverter.exe"; Description: "Launch MKV Profile Converter"; Flags: nowait postinstall skipifsilent
