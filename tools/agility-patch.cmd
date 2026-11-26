@echo off
rem Auto-patch a VIctory fork for Windows 10's D3D12 (Agility SDK).
rem Usage: agility-patch.cmd <fork-root> [--d3d12-core PATH] [--dry-run] [--revert]
setlocal
set "TOOL=%~dp0victory_agility_patch.py"
python "%TOOL%" %*
if errorlevel 9009 py -3 "%TOOL%" %*
exit /b %ERRORLEVEL%
