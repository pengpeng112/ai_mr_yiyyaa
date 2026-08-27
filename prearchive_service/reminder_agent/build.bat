@echo off
rem ============================================================================
rem build.bat - Prearchive Reminder Agent (028 P2 skeleton, 4.1 external helper)
rem Output: ReminderAgent.exe (WinForms tray app, fail-open skeleton)
rem Runtime: place agent_config.json (copy from agent_config.example.json,
rem          replace placeholders) next to ReminderAgent.exe
rem ============================================================================
setlocal
set CSC=C:\Windows\Microsoft.NET\Framework64\v4.0.30319\csc.exe
if not exist "%CSC%" (
  echo [ERROR] csc.exe not found: %CSC%
  exit /b 1
)
"%CSC%" /nologo /target:winexe /out:ReminderAgent.exe /optimize+ /codepage:65001 ^
  /r:System.dll /r:System.Core.dll /r:System.Drawing.dll ^
  /r:System.Windows.Forms.dll /r:System.Web.Extensions.dll ^
  ReminderAgent.cs
if errorlevel 1 (
  echo [ERROR] compile failed
  exit /b 1
)
echo [OK] ReminderAgent.exe built.
endlocal
