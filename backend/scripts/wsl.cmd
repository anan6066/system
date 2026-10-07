@echo off
rem ============================================================================
rem  Run the backend inside WSL (Ubuntu-22.04) instead of on Windows.
rem
rem  Why: the real toolchain (CANN / AMCT / ATC) and the target server are Linux,
rem  so running here keeps behaviour closer to deployment. The code itself stays
rem  on the Windows filesystem and is reached through /mnt/c, so there is only
rem  one copy to edit -- the venv lives inside Linux to keep I/O fast.
rem
rem  Usage (works from cmd and PowerShell, run from the backend directory):
rem    scripts\wsl.cmd serve    start the backend on http://localhost:8000
rem    scripts\wsl.cmd test     full pytest suite
rem    scripts\wsl.cmd quick    fast subset - no end-to-end cases
rem    scripts\wsl.cmd shell    interactive shell inside the distro
rem    scripts\wsl.cmd ssh      start sshd (makes the distro a deploy target)
rem    scripts\wsl.cmd stop     stop the backend
rem    scripts\wsl.cmd doctor   show distro / venv / port status
rem
rem  Note: this file is ASCII only. cmd.exe mangles UTF-8 batch files.
rem ============================================================================
setlocal
set "DISTRO=Ubuntu-22.04"
set "VENV=/root/.venvs/quant"

rem Resolve the backend directory into a WSL path (C:\... -> /mnt/c/...)
set "PROJ="
for /f "usebackq delims=" %%i in (`wsl -d %DISTRO% -u root wslpath -a "%~dp0.." 2^>nul`) do set "PROJ=%%i"
if not defined PROJ set "PROJ=/mnt/c/Users/PC/Desktop/system/backend"

set "MODE=%~1"
if "%MODE%"=="" set "MODE=serve"

if /i "%MODE%"=="serve"  goto serve
if /i "%MODE%"=="test"   goto test
if /i "%MODE%"=="quick"  goto quick
if /i "%MODE%"=="shell"  goto shell
if /i "%MODE%"=="ssh"    goto ssh
if /i "%MODE%"=="stop"   goto stop
if /i "%MODE%"=="doctor" goto doctor

echo Unknown mode: %MODE%
echo Available: serve ^| test ^| quick ^| shell ^| ssh ^| stop ^| doctor
exit /b 1

:serve
rem WSL2 stops an idle distro after ~30s, which closes the forwarded port.
rem A detached sleep keeps the VM up so localhost:8000 stays reachable.
wsl -d %DISTRO% -u root -- bash -c "setsid nohup sleep 100000 >/dev/null 2>&1 < /dev/null & sleep 1; systemctl start ssh"
echo [wsl] backend dir: %PROJ%
echo [wsl] starting on http://localhost:8000   (Ctrl+C to stop)
echo [wsl] Swagger UI: http://localhost:8000/docs
wsl -d %DISTRO% -u root -- bash -c "cd %PROJ% && exec %VENV%/bin/python -m uvicorn app.main:app --host 0.0.0.0 --port 8000"
goto done

:test
echo [wsl] full pytest suite
wsl -d %DISTRO% -u root -- bash -c "cd %PROJ% && %VENV%/bin/python -m pytest tests/ --no-header"
goto done

:quick
echo [wsl] fast subset
wsl -d %DISTRO% -u root -- bash -c "cd %PROJ% && %VENV%/bin/python -m pytest tests/test_health.py tests/test_devices.py tests/test_models_upload.py tests/test_stats.py tests/test_pipeline.py tests/test_executor.py tests/test_algo_scripts.py tests/test_models_smoke.py --no-header"
goto done

:shell
wsl -d %DISTRO% -u root -- bash -c "cd %PROJ% && exec bash"
goto done

:ssh
echo [wsl] starting sshd in %DISTRO%
wsl -d %DISTRO% -u root -- bash -c "setsid nohup sleep 100000 >/dev/null 2>&1 < /dev/null & systemctl start ssh; sleep 2; systemctl is-active ssh"
goto done

:stop
wsl -d %DISTRO% -u root -- pkill -f "uvicorn app.main:app"
echo [wsl] backend stopped
goto done

:doctor
echo [wsl] distros:
wsl -l -v
echo.
echo [wsl] project dir: %PROJ%
wsl -d %DISTRO% -u root -- %VENV%/bin/python -V
echo [wsl] ssh service:
wsl -d %DISTRO% -u root -- systemctl is-active ssh
echo [wsl] listening on 8000:
wsl -d %DISTRO% -u root -- ss -tln
goto done

:done
endlocal
