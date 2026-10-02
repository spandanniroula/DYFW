@echo off
rem Builds dist\DYFW.exe
cd /d "%~dp0"

rem Find Python: the "py" launcher, then python on PATH, then the default per-user install.
set PY=
where py >nul 2>nul && set PY=py
if not defined PY where python >nul 2>nul && set PY=python
if not defined PY if exist "%LOCALAPPDATA%\Programs\Python\Python312\python.exe" set PY="%LOCALAPPDATA%\Programs\Python\Python312\python.exe"
if not defined PY (
    echo Python 3.10+ is required: https://www.python.org/downloads/
    exit /b 1
)

%PY% -m pip install --quiet --upgrade -r requirements.txt
%PY% -c "import platform_utils as p; p.make_icon_image(256).save('icon.ico', sizes=[(16,16),(24,24),(32,32),(48,48),(64,64),(128,128),(256,256)])"
%PY% -m PyInstaller --noconfirm --onefile --windowed --name DYFW --icon icon.ico ^
    --hidden-import pystray._win32 --collect-data tzdata --collect-submodules winrt ^
    sticky_note.py
echo.
echo Done: dist\DYFW.exe
