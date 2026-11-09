#ifndef PayloadDir
  #error PayloadDir must point to the verified delivery folder.
#endif
#ifndef DeliveryDir
  #error DeliveryDir must point to the installer output folder.
#endif

[Setup]
AppId={{C271F19B-1A78-49AD-B90B-8B3175D5F8E2}
AppName=PDF 高清压缩
AppVersion=2.4.1
AppVerName=PDF 高清压缩 2.4.1
DefaultDirName={localappdata}\Programs\PDFCompressor
DefaultGroupName=PDF 高清压缩
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0
WizardStyle=modern light
WizardSizePercent=100
DisableWelcomePage=yes
DisableDirPage=no
DisableProgramGroupPage=yes
DisableReadyPage=no
DisableFinishedPage=yes
DisableStartupPrompt=yes
AllowNoIcons=no
AllowCancelDuringInstall=yes
UsePreviousAppDir=yes
UsePreviousGroup=yes
CloseApplications=no
RestartApplications=no
AppMutex=Local\PDFCompressor.Main
Uninstallable=yes
UninstallDisplayName=PDF 高清压缩
UninstallDisplayIcon={app}\PDFCompressor.exe
SetupIconFile={#PayloadDir}\折叠图标.ico
OutputDir={#DeliveryDir}
OutputBaseFilename=PDF高清压缩_一键安装_v2.4.1_Setup
Compression=lzma2
SolidCompression=yes
SetupLogging=yes
VersionInfoVersion=2.4.1.0
VersionInfoDescription=PDF 高清压缩安装程序
VersionInfoProductName=PDF 高清压缩
VersionInfoProductVersion=2.4.1
UninstallLogMode=append

[Languages]
Name: "zhcn"; MessagesFile: "compiler:Languages\ChineseSimplified.isl"

[Messages]
ButtonInstall=一键安装(&I)
ReadyLabel1=点击“一键安装”，安装 PDF 高清压缩。
ReadyLabel2a=请核对安装位置。安装后创建桌面快捷方式并启动软件。
SetupAppRunningError=PDF 高清压缩仍在运行。请先完成或停止任务，并正常退出软件，再继续安装。
UninstallAppRunningError=PDF 高清压缩仍在运行。请先完成或停止任务，并正常退出软件，再继续卸载。
ReadyMemoDir=安装位置：
FinishedHeadingLabel=安装完成
FinishedLabelNoIcons=PDF 高清压缩已安装完成。

[Files]
Source: "{#PayloadDir}\PDFCompressor\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "{#PayloadDir}\折叠图标.ico"; DestDir: "{app}"; DestName: "app.ico"; Flags: ignoreversion
Source: "安装与卸载说明.txt"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\LICENSE"; DestDir: "{app}"; DestName: "LICENSE.txt"; Flags: ignoreversion
Source: "..\THIRD_PARTY_NOTICES.md"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\licenses\*"; DestDir: "{app}\licenses"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{autodesktop}\PDF高清压缩"; Filename: "{app}\PDFCompressor.exe"; WorkingDir: "{app}"; IconFilename: "{app}\app.ico"; AppUserModelID: "LocalTools.PDFCompressor.UnifiedUI.2.1"
Name: "{group}\PDF 高清压缩"; Filename: "{app}\PDFCompressor.exe"; WorkingDir: "{app}"; IconFilename: "{app}\app.ico"; AppUserModelID: "LocalTools.PDFCompressor.UnifiedUI.2.1"
Name: "{group}\卸载 PDF 高清压缩"; Filename: "{uninstallexe}"

[Run]
Filename: "{app}\PDFCompressor.exe"; WorkingDir: "{app}"; Flags: nowait skipifsilent

[Code]
var
  ExistingDir: String;
  ExistingVersion: String;

function IsNewer(A, B: String): Boolean;
var
  I, P, X, Y: Integer;
  SA, SB: String;
begin
  Result := False;
  for I := 1 to 4 do begin
    P := Pos('.', A); if P = 0 then P := Length(A) + 1;
    SA := Copy(A, 1, P - 1); Delete(A, 1, P);
    P := Pos('.', B); if P = 0 then P := Length(B) + 1;
    SB := Copy(B, 1, P - 1); Delete(B, 1, P);
    X := StrToIntDef(SA, 0); Y := StrToIntDef(SB, 0);
    if X > Y then begin Result := True; Exit; end;
    if X < Y then Exit;
  end;
end;

function InitializeSetup(): Boolean;
var
  Key: String;
begin
  Key := 'Software\Microsoft\Windows\CurrentVersion\Uninstall\{C271F19B-1A78-49AD-B90B-8B3175D5F8E2}_is1';
  RegQueryStringValue(HKCU64, Key, 'InstallLocation', ExistingDir);
  RegQueryStringValue(HKCU64, Key, 'DisplayVersion', ExistingVersion);
  Result := True;
  if IsNewer(ExistingVersion, '2.4.1') then
    Result := SuppressibleMsgBox('检测到已安装版本 ' + ExistingVersion + '。继续将回退到 2.4.1。是否确认回退？', mbConfirmation, MB_YESNO, IDNO) = IDYES;
end;

function DirectoryAllowed(): Boolean;
begin
  Result := (ExistingDir = '') or (CompareText(RemoveBackslashUnlessRoot(ExistingDir), RemoveBackslashUnlessRoot(ExpandConstant('{app}'))) = 0);
end;

function NextButtonClick(CurPageID: Integer): Boolean;
begin
  Result := True;
  if (CurPageID = wpSelectDir) and not DirectoryAllowed() then begin
    MsgBox('升级会沿用原安装位置：' + ExistingDir + #13#10 + '如需更换位置，请先正常卸载旧版，再重新安装。卸载不会删除您的 PDF、设置和处理记录。', mbInformation, MB_OK);
    Result := False;
  end;
end;

function PrepareToInstall(var NeedsRestart: Boolean): String;
begin
  Result := '';
  if not DirectoryAllowed() then begin
    Result := '升级必须沿用原安装目录。请先卸载旧版后再更换安装位置。';
    Exit;
  end;
  if CheckForMutexes('Local\PDFCompressor.Busy') then
    Result := '正在压缩文件，请先完成或安全停止任务，再正常退出软件。安装不会强制停止当前任务。';
end;

