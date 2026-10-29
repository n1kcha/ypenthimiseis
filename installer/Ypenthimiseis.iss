; Inno Setup script — Υπενθυμίσεις καταστημάτων
; Μεταγλώττιση (μετά το PyInstaller):  iscc installer\Ypenthimiseis.iss
; Παράγει installer\Output\Ypenthimiseis-Setup.exe

#ifndef MyAppVersion
  #define MyAppVersion "1.0.0"
#endif
#define MyAppName "Υπενθυμίσεις καταστημάτων"
#define MyAppExe "Ypenthimiseis.exe"
#define MyDataDir "Ypenthimiseis"

[Setup]
AppId={{8C3B6F1E-5D0A-4C7B-9E2F-3A1D4B6C7E90}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppVerName={#MyAppName} {#MyAppVersion}
AppPublisher=LocalBits
AppPublisherURL=https://localbits.gr/
AppSupportURL=https://github.com/n1kcha/ypenthimiseis/issues
AppUpdatesURL=https://localbits.gr/ypenthimiseis/
DefaultDirName={localappdata}\{#MyDataDir}
DisableDirPage=yes
DisableProgramGroupPage=yes
DefaultGroupName={#MyAppName}
PrivilegesRequired=lowest
OutputDir=Output
OutputBaseFilename=Ypenthimiseis-Setup
SetupIconFile=icon.ico
WizardImageFile=wizard.bmp,wizard-2x.bmp
WizardSmallImageFile=wizard-small.bmp,wizard-small-2x.bmp
UninstallDisplayIcon={app}\{#MyAppExe}
UninstallDisplayName={#MyAppName}
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
ShowLanguageDialog=no
CloseApplications=yes
RestartApplications=no
UsedUserAreasWarning=no

[Languages]
Name: "greek"; MessagesFile: "Greek.isl"

[InstallDelete]
; καθαρή αναβάθμιση των αρχείων του προγράμματος (ΟΧΙ config.json / state.json)
Type: filesandordirs; Name: "{app}\_internal"
; παλιά εκκίνηση της έκδοσης με Python (install.py / install_startup.bat)
Type: files; Name: "{userstartup}\ypenthimiseis-katastimaton.bat"

[Files]
Source: "..\dist\Ypenthimiseis\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExe}"; IconFilename: "{app}\{#MyAppExe}"
Name: "{group}\Ρυθμίσεις υπενθυμίσεων"; Filename: "{app}\{#MyAppExe}"; Parameters: "--settings"; IconFilename: "{app}\{#MyAppExe}"
Name: "{group}\Απεγκατάσταση"; Filename: "{uninstallexe}"

[Registry]
; αυτόματη εκκίνηση με τα Windows (μόνο για τον τρέχοντα χρήστη)
Root: HKCU; Subkey: "Software\Microsoft\Windows\CurrentVersion\Run"; ValueType: string; ValueName: "Ypenthimiseis"; ValueData: """{app}\{#MyAppExe}"""; Flags: uninsdeletevalue

[Run]
Filename: "{app}\{#MyAppExe}"; Description: "Εκκίνηση των υπενθυμίσεων τώρα"; Flags: nowait postinstall skipifsilent
Filename: "{app}\{#MyAppExe}"; Flags: nowait; Check: WizardSilent

[Code]
var
  StorePage: TInputQueryWizardPage;
  ExtraPage: TWizardPage;
  ExtraMemo: TNewMemo;

function DataDir: String;
begin
  Result := ExpandConstant('{localappdata}\{#MyDataDir}');
end;

function ConfigPath: String;
begin
  Result := DataDir + '\config.json';
end;

function HasConfig: Boolean;
begin
  Result := FileExists(ConfigPath);
end;

{ Κλείνει την εφαρμογή αν τρέχει (και την παλιά έκδοση με pythonw app.py). }
procedure KillApp;
var
  R: Integer;
begin
  Exec(ExpandConstant('{sys}\taskkill.exe'), '/F /T /IM {#MyAppExe}', '', SW_HIDE, ewWaitUntilTerminated, R);
  Exec('powershell.exe',
    '-NoProfile -NonInteractive -ExecutionPolicy Bypass -Command "' +
    'Get-CimInstance Win32_Process | Where-Object { $_.ProcessId -ne $PID -and $_.Name -match ''python'' -and ' +
    '$_.CommandLine -like ''*{#MyDataDir}\app.py*'' } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force }"',
    '', SW_HIDE, ewWaitUntilTerminated, R);
  Sleep(800);
end;

function IsValidStoreId(S: String): Boolean;
var
  I: Integer;
  C: Char;
begin
  Result := Length(S) > 0;
  for I := 1 to Length(S) do
  begin
    C := S[I];
    if not (((C >= 'a') and (C <= 'z')) or ((C >= '0') and (C <= '9')) or (C = '-') or (C = '_')) then
    begin
      Result := False;
      Exit;
    end;
  end;
end;

function StartsWithHttp(S: String): Boolean;
begin
  Result := Pos('http', Lowercase(Trim(S))) = 1;
end;

function JsonEsc(S: String): String;
var
  I: Integer;
  C: Char;
begin
  Result := '';
  for I := 1 to Length(S) do
  begin
    C := S[I];
    if C = '\' then
      Result := Result + '\\'
    else if C = '"' then
      Result := Result + '\"'
    else if Ord(C) < 32 then
      Result := Result + ' '
    else
      Result := Result + C;
  end;
end;

procedure InitializeWizard;
begin
  StorePage := CreateInputQueryPage(wpWelcome,
    'Στοιχεία καταστήματος',
    'Τα στοιχεία που χρειάζονται οι υπενθυμίσεις.',
    'Μπορείτε να τα αλλάξετε αργότερα από το εικονίδιο κοντά στο ρολόι → «Ρυθμίσεις».');
  StorePage.Add('Όνομα καταστήματος:', False);
  StorePage.Add('ID καταστήματος (λατινικά γράμματα ή/και αριθμοί, π.χ. peristeri ή 12):', False);
  StorePage.Add('Κεντρικός σύνδεσμος ICS (μυστική διεύθυνση iCal, ξεκινά με https://):', False);
  StorePage.Add('Δευτερόλεπτα ήχου ειδοποίησης:', False);
  StorePage.Values[3] := '10';

  ExtraPage := CreateCustomPage(StorePage.ID,
    'Επιπλέον ημερολόγια (προαιρετικό)',
    'Ένας σύνδεσμος ICS ανά γραμμή. Αφήστε κενό αν δεν υπάρχουν.');
  ExtraMemo := TNewMemo.Create(ExtraPage);
  ExtraMemo.Parent := ExtraPage.Surface;
  ExtraMemo.Left := 0;
  ExtraMemo.Top := 0;
  ExtraMemo.Width := ExtraPage.SurfaceWidth;
  ExtraMemo.Height := ScaleY(140);
  ExtraMemo.ScrollBars := ssVertical;
  ExtraMemo.WordWrap := False;
  ExtraMemo.WantReturns := True;
end;

function ShouldSkipPage(PageID: Integer): Boolean;
begin
  { σε αναβάθμιση κρατάμε το υπάρχον config.json — οι αλλαγές γίνονται από τις Ρυθμίσεις }
  Result := ((PageID = StorePage.ID) or (PageID = ExtraPage.ID)) and HasConfig;
end;

function NextButtonClick(CurPageID: Integer): Boolean;
var
  Sec, I: Integer;
begin
  Result := True;
  if CurPageID = StorePage.ID then
  begin
    StorePage.Values[0] := Trim(StorePage.Values[0]);
    StorePage.Values[1] := Lowercase(Trim(StorePage.Values[1]));
    StorePage.Values[2] := Trim(StorePage.Values[2]);
    if StorePage.Values[0] = '' then
    begin
      MsgBox('Συμπληρώστε το όνομα του καταστήματος.', mbError, MB_OK);
      Result := False;
    end
    else if not IsValidStoreId(StorePage.Values[1]) then
    begin
      MsgBox('Το ID δέχεται μόνο λατινικά γράμματα, αριθμούς, - ή _ (π.χ. peristeri ή 12).', mbError, MB_OK);
      Result := False;
    end
    else if not StartsWithHttp(StorePage.Values[2]) then
    begin
      MsgBox('Ο κεντρικός σύνδεσμος ICS πρέπει να ξεκινά με http:// ή https://', mbError, MB_OK);
      Result := False;
    end
    else
    begin
      Sec := StrToIntDef(Trim(StorePage.Values[3]), -1);
      if (Sec < 1) or (Sec > 600) then
      begin
        MsgBox('Τα δευτερόλεπτα ήχου πρέπει να είναι ακέραιος από 1 έως 600.', mbError, MB_OK);
        Result := False;
      end;
    end;
  end
  else if CurPageID = ExtraPage.ID then
  begin
    for I := 0 to ExtraMemo.Lines.Count - 1 do
      if (Trim(ExtraMemo.Lines[I]) <> '') and not StartsWithHttp(ExtraMemo.Lines[I]) then
      begin
        MsgBox('Κάθε γραμμή πρέπει να είναι σύνδεσμος που ξεκινά με http:// ή https://' + #13#10 + ExtraMemo.Lines[I], mbError, MB_OK);
        Result := False;
        Exit;
      end;
  end;
end;

procedure WriteConfig;
var
  Lines: TArrayOfString;
  Extras: String;
  I, N, Sec: Integer;
  U: String;
begin
  Extras := '';
  N := 0;
  for I := 0 to ExtraMemo.Lines.Count - 1 do
  begin
    U := Trim(ExtraMemo.Lines[I]);
    if (U <> '') and (U <> StorePage.Values[2]) then
    begin
      if N > 0 then
        Extras := Extras + ',' + #13#10;
      Extras := Extras + '    "' + JsonEsc(U) + '"';
      N := N + 1;
    end;
  end;
  Sec := StrToIntDef(Trim(StorePage.Values[3]), 10);

  SetArrayLength(Lines, 14);
  Lines[0] := '{';
  Lines[1] := '  "store_name": "' + JsonEsc(StorePage.Values[0]) + '",';
  Lines[2] := '  "store_id": "' + JsonEsc(StorePage.Values[1]) + '",';
  Lines[3] := '  "ics_url": "' + JsonEsc(StorePage.Values[2]) + '",';
  if N = 0 then
  begin
    Lines[4] := '  "ics_urls": [],';
    Lines[5] := '';
    Lines[6] := '';
  end
  else
  begin
    Lines[4] := '  "ics_urls": [';
    Lines[5] := Extras;
    Lines[6] := '  ],';
  end;
  Lines[7] := '  "poll_seconds": 30,';
  Lines[8] := '  "minutes_before": 0,';
  Lines[9] := '  "show_missed_max_minutes": 15,';
  Lines[10] := '  "sound": true,';
  Lines[11] := '  "sound_seconds": ' + IntToStr(Sec);
  Lines[12] := '}';
  Lines[13] := '';
  ForceDirectories(DataDir);
  if not SaveStringsToUTF8File(ConfigPath, Lines, False) then
    MsgBox('Δεν γράφτηκε το config.json. Ανοίξτε τις Ρυθμίσεις από το εικονίδιο της εφαρμογής.', mbError, MB_OK);
end;

function PrepareToInstall(var NeedsRestart: Boolean): String;
begin
  KillApp;
  Result := '';
end;

procedure CurStepChanged(CurStep: TSetupStep);
begin
  { γράφουμε config.json μόνο αν δεν υπάρχει ήδη και ο χρήστης συμπλήρωσε τη φόρμα;
    αλλιώς η εφαρμογή ανοίγει μόνη της τις Ρυθμίσεις στην πρώτη εκκίνηση }
  if (CurStep = ssPostInstall) and (not HasConfig) and (StorePage.Values[2] <> '') then
    WriteConfig;
end;

function InitializeUninstall: Boolean;
begin
  KillApp;
  Result := True;
end;

procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
begin
  if CurUninstallStep = usPostUninstall then
  begin
    DeleteFile(DataDir + '\chime.wav');
    DeleteFile(DataDir + '\app.log');
    DeleteFile(DataDir + '\app.old.log');
    DeleteFile(DataDir + '\config.tmp');
    DeleteFile(DataDir + '\state.tmp');
    if FileExists(ConfigPath) and (not UninstallSilent) then
      if MsgBox('Να διαγραφούν και οι ρυθμίσεις (config.json) και το ιστορικό «Το είδα»;' + #13#10 +
                'Επιλέξτε «Όχι» αν θα το ξαναεγκαταστήσετε.', mbConfirmation, MB_YESNO or MB_DEFBUTTON2) = IDYES then
      begin
        DeleteFile(ConfigPath);
        DeleteFile(DataDir + '\state.json');
      end;
    RemoveDir(DataDir);
  end;
end;
