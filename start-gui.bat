@echo off
REM ====================================================================
REM  BTX Windows Miner - GUI launcher (double-click me)
REM ====================================================================
cd /d "%~dp0"

where pythonw >nul 2>nul
if %errorlevel%==0 (
    start "" pythonw "gui\btx_miner_gui.py"
    goto :eof
)

where python >nul 2>nul
if %errorlevel%==0 (
    python "gui\btx_miner_gui.py"
    goto :eof
)

echo.
echo  Python was not found on your PATH.
echo  Install Python 3.10+ from https://www.python.org/downloads/
echo  and tick "Add python.exe to PATH" during setup.
echo.
pause
