; NeoSSHWinManager Windows installer (Inno Setup 6)
;
; Builds a Setup.exe from the already-built dist\ executables (run
; build_dual.ps1 first). The app version is read directly from the built
; GUI exe's version resource, so it can never drift from file_version_info.txt.
;
; Compile with: ISCC.exe installer\NeoSSHWinManager.iss
; (or run installer\build_installer.ps1, which does both steps)

#define MyAppName "NeoSSHWinManager"
#define MyAppExeName "NeoSSHWinManager.exe"
#define MyAppCliExeName "NeoSSHWinManager-cli.exe"
#define MyAppPublisher "Gregor Krebs"
#define MyAppURL "https://github.com/gregorkrebs/NeoSSHWinManager"
#define MyAppId "{B4E6F1A2-7C3D-4E5A-9F8B-1D2C3E4F5A6B}"

#define RawVersion GetVersionNumbersString(SourcePath + "..\dist\" + MyAppExeName)
#define MyAppVersion Copy(RawVersion, 1, RPos(".", RawVersion) - 1)

[Setup]
AppId={{#MyAppId}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppVerName={#MyAppName} {#MyAppVersion}
AppPublisher={#MyAppPublisher}
AppPublisherURL={#MyAppURL}
AppSupportURL={#MyAppURL}/issues
AppUpdatesURL={#MyAppURL}/releases
DefaultDirName={autopf}\{#MyAppName}
DefaultGroupName={#MyAppName}
DisableProgramGroupPage=yes
LicenseFile=..\LICENSE
OutputDir=..\dist_installer
OutputBaseFilename=NeoSSHWinManager-Setup-{#MyAppVersion}
SetupIconFile=..\assets\app_icon.ico
UninstallDisplayIcon={app}\{#MyAppExeName}
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
ChangesAssociations=no

[Languages]
Name: "en"; MessagesFile: "compiler:Default.isl"
Name: "de"; MessagesFile: "compiler:Languages\German.isl"
Name: "es"; MessagesFile: "compiler:Languages\Spanish.isl"
Name: "ru"; MessagesFile: "compiler:Languages\Russian.isl"
Name: "nl"; MessagesFile: "compiler:Languages\Dutch.isl"

[CustomMessages]
en.AutoStartTask=Start %1 automatically when Windows starts
de.AutoStartTask=%1 automatisch mit Windows starten
es.AutoStartTask=Iniciar %1 automáticamente al arrancar Windows
ru.AutoStartTask=Запускать %1 автоматически при загрузке Windows
nl.AutoStartTask=%1 automatisch starten bij het opstarten van Windows

en.AppPrefsPageCaption=Application Preferences
de.AppPrefsPageCaption=Anwendungseinstellungen
es.AppPrefsPageCaption=Preferencias de la aplicación
ru.AppPrefsPageCaption=Настройки приложения
nl.AppPrefsPageCaption=Toepassingsvoorkeuren

en.AppPrefsPageDescription=Choose the language and appearance %1 should start with. You can change these anytime later in the app's Settings.
de.AppPrefsPageDescription=Wähle die Sprache und das Erscheinungsbild, mit dem %1 starten soll. Diese Auswahl kann jederzeit in den Einstellungen der App geändert werden.
es.AppPrefsPageDescription=Elige el idioma y la apariencia con la que debe iniciarse %1. Puedes cambiarlos más tarde en los ajustes de la aplicación.
ru.AppPrefsPageDescription=Выберите язык и оформление, с которыми должно запускаться приложение %1. Позже это можно изменить в настройках приложения.
nl.AppPrefsPageDescription=Kies de taal en het uiterlijk waarmee %1 moet starten. Dit kan later altijd worden gewijzigd in de instellingen van de app.

en.AppLanguageLabel=Application language:
de.AppLanguageLabel=Anwendungssprache:
es.AppLanguageLabel=Idioma de la aplicación:
ru.AppLanguageLabel=Язык приложения:
nl.AppLanguageLabel=Applicatietaal:

en.ThemeLabel=Appearance:
de.ThemeLabel=Erscheinungsbild:
es.ThemeLabel=Apariencia:
ru.ThemeLabel=Внешний вид:
nl.ThemeLabel=Uiterlijk:

en.ThemeDark=Dark
de.ThemeDark=Dunkel
es.ThemeDark=Oscuro
ru.ThemeDark=Тёмная
nl.ThemeDark=Donker

en.ThemeLight=Light
de.ThemeLight=Hell
es.ThemeLight=Claro
ru.ThemeLight=Светлая
nl.ThemeLight=Licht

en.ComponentGui=GUI application (required)
de.ComponentGui=Grafische Anwendung (erforderlich)
es.ComponentGui=Aplicación gráfica (obligatoria)
ru.ComponentGui=Графическое приложение (обязательно)
nl.ComponentGui=Grafische toepassing (vereist)

en.ComponentCli=Command-line tool (NeoSSHWinManager-cli.exe)
de.ComponentCli=Kommandozeilen-Tool (NeoSSHWinManager-cli.exe)
es.ComponentCli=Herramienta de línea de comandos (NeoSSHWinManager-cli.exe)
ru.ComponentCli=Инструмент командной строки (NeoSSHWinManager-cli.exe)
nl.ComponentCli=Opdrachtregeltool (NeoSSHWinManager-cli.exe)

en.MyFullInstallation=Full installation
de.MyFullInstallation=Vollständige Installation
es.MyFullInstallation=Instalación completa
ru.MyFullInstallation=Полная установка
nl.MyFullInstallation=Volledige installatie

en.MyCompactInstallation=Compact installation (GUI only)
de.MyCompactInstallation=Kompakte Installation (nur GUI)
es.MyCompactInstallation=Instalación compacta (solo GUI)
ru.MyCompactInstallation=Компактная установка (только GUI)
nl.MyCompactInstallation=Compacte installatie (alleen GUI)

en.MyCustomInstallation=Custom installation
de.MyCustomInstallation=Benutzerdefinierte Installation
es.MyCustomInstallation=Instalación personalizada
ru.MyCustomInstallation=Выборочная установка
nl.MyCustomInstallation=Aangepaste installatie

[Types]
Name: "full"; Description: "{cm:MyFullInstallation}"
Name: "compact"; Description: "{cm:MyCompactInstallation}"
Name: "custom"; Description: "{cm:MyCustomInstallation}"; Flags: iscustom

[Components]
Name: "gui"; Description: "{cm:ComponentGui}"; Types: full compact custom; Flags: fixed
Name: "cli"; Description: "{cm:ComponentCli}"; Types: full custom

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"
Name: "autostart"; Description: "{cm:AutoStartTask,{#MyAppName}}"; GroupDescription: "{cm:AdditionalIcons}"

[Files]
Source: "..\dist\{#MyAppExeName}"; DestDir: "{app}"; Flags: ignoreversion; Components: gui
Source: "..\dist\{#MyAppCliExeName}"; DestDir: "{app}"; Flags: ignoreversion; Components: cli
Source: "..\README.md"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\CHANGELOG.md"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{autoprograms}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{autoprograms}\{#MyAppName} CLI"; Filename: "{app}\{#MyAppCliExeName}"; Components: cli
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Registry]
Root: HKCU; Subkey: "Software\Microsoft\Windows\CurrentVersion\Run"; ValueType: string; ValueName: "{#MyAppName}"; ValueData: """{app}\{#MyAppExeName}"""; Flags: uninsdeletevalue; Tasks: autostart

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "{cm:LaunchProgram,{#MyAppName}}"; Flags: nowait postinstall skipifsilent

[Code]
var
  AppPrefsPage: TWizardPage;
  LangCombo: TNewComboBox;
  ThemeCombo: TNewComboBox;

procedure InitializeWizard;
var
  LangLabel, ThemeLabel: TNewStaticText;
begin
  AppPrefsPage := CreateCustomPage(wpSelectTasks, CustomMessage('AppPrefsPageCaption'),
    CustomMessage('AppPrefsPageDescription'));

  LangLabel := TNewStaticText.Create(AppPrefsPage);
  LangLabel.Parent := AppPrefsPage.Surface;
  LangLabel.Caption := CustomMessage('AppLanguageLabel');
  LangLabel.Top := ScaleY(8);
  LangLabel.AutoSize := True;

  LangCombo := TNewComboBox.Create(AppPrefsPage);
  LangCombo.Parent := AppPrefsPage.Surface;
  LangCombo.Style := csDropDownList;
  LangCombo.Top := LangLabel.Top + LangLabel.Height + ScaleY(4);
  LangCombo.Width := AppPrefsPage.SurfaceWidth;
  LangCombo.Items.Add('English');
  LangCombo.Items.Add('Deutsch');
  LangCombo.Items.Add('Español');
  LangCombo.Items.Add('Русский');
  LangCombo.Items.Add('Nederlands');
  LangCombo.Items.Add('العربية');
  LangCombo.ItemIndex := 0;

  ThemeLabel := TNewStaticText.Create(AppPrefsPage);
  ThemeLabel.Parent := AppPrefsPage.Surface;
  ThemeLabel.Caption := CustomMessage('ThemeLabel');
  ThemeLabel.Top := LangCombo.Top + LangCombo.Height + ScaleY(16);
  ThemeLabel.AutoSize := True;

  ThemeCombo := TNewComboBox.Create(AppPrefsPage);
  ThemeCombo.Parent := AppPrefsPage.Surface;
  ThemeCombo.Style := csDropDownList;
  ThemeCombo.Top := ThemeLabel.Top + ThemeLabel.Height + ScaleY(4);
  ThemeCombo.Width := AppPrefsPage.SurfaceWidth;
  ThemeCombo.Items.Add(CustomMessage('ThemeDark'));
  ThemeCombo.Items.Add(CustomMessage('ThemeLight'));
  ThemeCombo.ItemIndex := 0;
end;

function LangCodeFromIndex(Idx: Integer): String;
begin
  case Idx of
    1: Result := 'de';
    2: Result := 'es';
    3: Result := 'ru';
    4: Result := 'nl';
    5: Result := 'ar';
  else
    Result := 'en';
  end;
end;

procedure CurStepChanged(CurStep: TSetupStep);
var
  PrefsDir, PrefsFile, ThemeCode, StartWithWindowsJson, JsonContent: String;
begin
  if CurStep = ssPostInstall then
  begin
    PrefsDir := ExpandConstant('{userappdata}\SSHWinManager');
    ForceDirectories(PrefsDir);
    PrefsFile := PrefsDir + '\install_prefs.json';

    if ThemeCombo.ItemIndex = 1 then
      ThemeCode := 'light'
    else
      ThemeCode := 'dark';

    if WizardIsTaskSelected('autostart') then
      StartWithWindowsJson := 'true'
    else
      StartWithWindowsJson := 'false';

    JsonContent := '{' + #13#10 +
      '  "language": "' + LangCodeFromIndex(LangCombo.ItemIndex) + '",' + #13#10 +
      '  "theme": "' + ThemeCode + '",' + #13#10 +
      '  "start_with_windows": ' + StartWithWindowsJson + #13#10 +
      '}';

    SaveStringToFile(PrefsFile, JsonContent, False);
  end;
end;
