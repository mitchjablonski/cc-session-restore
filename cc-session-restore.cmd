@echo off
rem Text-mode version of cc-session-restore (the window is cc-session-restore.ps1).
wsl.exe --cd "%~dp0." -- python3 ./cc-session-restore --wait %*
