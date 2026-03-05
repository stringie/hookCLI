@echo off
REM ===================================================================
REM Build hookCLI.exe using PyInstaller
REM
REM This creates:
REM   dist/hookCLI/
REM       hookCLI.exe
REM       lunahook/
REM           LunaHost64.dll
REM           LunaHook64.dll
REM           LunaHook32.dll
REM           shareddllproxy64.exe
REM           shareddllproxy32.exe
REM ===================================================================

echo [1/4] Installing PyInstaller...
pip install pyinstaller

echo [2/4] Building hookCLI.exe...
pyinstaller --noconfirm --onefile --console --name hookCLI hook_cli.py

echo [3/4] Copying LunaHook DLLs into dist folder...
mkdir "dist\lunahook" 2>nul

copy "..\files\lunahook\LunaHost64.dll"  "dist\lunahook\" /Y
copy "..\files\lunahook\LunaHook64.dll"  "dist\lunahook\" /Y
copy "..\files\lunahook\LunaHook32.dll"  "dist\lunahook\" /Y
copy "..\files\shareddllproxy64.exe"     "dist\lunahook\" /Y
copy "..\files\shareddllproxy32.exe"     "dist\lunahook\" /Y

echo [4/4] Done!
echo.
echo ===================================================================
echo   OUTPUT: dist\hookCLI.exe + dist\lunahook\
echo.
echo   Usage:
echo     dist\hookCLI.exe --attach ^<PID^>
echo     dist\hookCLI.exe --attach ^<PID^> --format json
echo     dist\hookCLI.exe --attach ^<PID^> --hookcode /HS-8@4025A0
echo     dist\hookCLI.exe --attach ^<PID^> --auto-hooks --output log.txt
echo     dist\hookCLI.exe --help
echo ===================================================================
echo.
echo You can now copy the "dist" folder anywhere. It contains:
echo   - hookCLI.exe     (the CLI tool)
echo   - lunahook/       (required DLLs, must stay next to the exe)
pause
