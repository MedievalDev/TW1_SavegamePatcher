@echo off
rem Baut den TW1 Savegame Patcher als eine Exe (PyInstaller, onefile, ohne Konsole).
rem Ergebnis: %~dp0dist\TW1 Savegame Patcher.exe - danach auf den Desktop kopieren.
setlocal
pushd "%~dp0"
"C:\Users\marco\AppData\Local\Programs\Python\Python313\python.exe" -m PyInstaller --noconfirm --onefile --windowed ^
  --name "TW1 Savegame Patcher" --icon "%~dp0save_patcher.ico" --add-data "%~dp0save_patcher.ico;." ^
  --hidden-import patcher_core --hidden-import theme ^
  --hidden-import tw1_save --hidden-import tw1_save_scripts --hidden-import tw1_save_patch ^
  --hidden-import tw1_save_tiles --hidden-import tw1_lnd --hidden-import wd_metadaten ^
  --distpath "%~dp0dist" --workpath "%TEMP%\save_patcher_build" --specpath "%TEMP%\save_patcher_build" save_patcher.py
set rc=%errorlevel%
popd
if %rc% neq 0 (echo BUILD FEHLGESCHLAGEN & exit /b %rc%)
echo BUILD OK: %~dp0dist\TW1 Savegame Patcher.exe
