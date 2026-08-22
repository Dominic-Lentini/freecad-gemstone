@echo off
REM Run the test suite under FreeCAD 1.1's bundled Python (see CLAUDE.md).
REM Works from any worktree: cd's to the directory containing this script.
REM Usage:  run_tests.cmd                              -> whole suite
REM         run_tests.cmd tests/test_gemmath.py -k azimuth
cd /d "%~dp0"
set FCPY=C:\Program Files\FreeCAD 1.1\bin\python.exe
if not exist "%FCPY%" (
  echo ERROR: FreeCAD Python not found at "%FCPY%"
  echo Check the FreeCAD version/install path and update CLAUDE.md if it moved.
  exit /b 1
)
if "%~1"=="" (
  "%FCPY%" -m pytest tests -q
) else (
  "%FCPY%" -m pytest %* -q
)
set RC=%ERRORLEVEL%
echo EXITCODE=%RC%
exit /b %RC%
