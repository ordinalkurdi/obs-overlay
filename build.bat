@echo off
py -m pip install -r requirements.txt
py -m PyInstaller --noconfirm --clean --windowed --name ObsOverlay ^
  --collect-all qtawesome ^
  --collect-submodules keyring ^
  --collect-submodules pynput ^
  --hidden-import pynput.keyboard._win32 ^
  --hidden-import pynput.mouse._win32 ^
  main.py
echo.
echo Done: dist\ObsOverlay\ObsOverlay.exe
pause
