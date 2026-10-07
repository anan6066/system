@echo off
rem ============================================================================
rem  Local helper for the backend (ASCII only - cmd.exe mangles UTF-8 batch files)
rem
rem  This workspace has no system Python (the `python` on PATH is the Microsoft
rem  Store stub), so we prefer tools\py38\python.exe: Python 3.8.10 with the
rem  exact dependency set from requirements.txt. Falls back to `python` if the
rem  embedded interpreter is missing (e.g. after copying backend/ to a server).
rem
rem  Usage (works from cmd and PowerShell):
rem    scripts\local.cmd test     full pytest suite (76 cases, ~105 s)
rem    scripts\local.cmd quick    fast subset - no end-to-end cases (47 cases, ~30 s)
rem    scripts\local.cmd e2e      end-to-end only: jobs flow + deploy + compare (29 cases, ~75 s)
rem    scripts\local.cmd lint     pyflakes static check
rem    scripts\local.cmd serve    start backend on http://127.0.0.1:8000
rem    scripts\local.cmd smoke    run the HTTP end-to-end script (needs serve running)
rem    scripts\local.cmd clean    delete local app.db and workspace (reset data)
rem ============================================================================
setlocal
pushd "%~dp0.."

set "PY=%~dp0..\..\tools\py38\python.exe"
if not exist "%PY%" set "PY=python"

set "MODE=%~1"
if "%MODE%"=="" set "MODE=test"

if /i "%MODE%"=="test"  goto test
if /i "%MODE%"=="quick" goto quick
if /i "%MODE%"=="e2e"   goto e2e
if /i "%MODE%"=="lint"  goto lint
if /i "%MODE%"=="serve" goto serve
if /i "%MODE%"=="smoke" goto smoke
if /i "%MODE%"=="clean" goto clean

echo Unknown mode: %MODE%
echo Available: test ^| quick ^| e2e ^| lint ^| serve ^| smoke ^| clean
popd
exit /b 1

:test
echo [local] interpreter: %PY%
"%PY%" -m pytest tests/ --no-header
goto done

:quick
echo [local] fast subset (no end-to-end deploy cases)
"%PY%" -m pytest tests/test_health.py tests/test_devices.py tests/test_models_upload.py tests/test_stats.py tests/test_pipeline.py tests/test_executor.py tests/test_algo_scripts.py tests/test_models_smoke.py --no-header
goto done

:e2e
echo [local] end-to-end subset (jobs flow + deployments + comparison)
"%PY%" -m pytest tests/test_jobs_flow.py tests/test_jobs_api.py tests/test_deployments.py tests/test_comparison.py --no-header
goto done

:lint
"%PY%" -m pyflakes app algorithms tests scripts
goto done

:serve
echo [local] starting backend on http://127.0.0.1:8000  (Ctrl+C to stop)
echo [local] Swagger UI: http://127.0.0.1:8000/docs    contract: http://127.0.0.1:8000/api/meta
"%PY%" -m uvicorn app.main:app --host 127.0.0.1 --port 8000
goto done

:smoke
set "BASE=%~2"
if "%BASE%"=="" set "BASE=http://127.0.0.1:8000"
echo [local] HTTP end-to-end check against %BASE%
"%PY%" scripts\smoke_http.py %BASE%
goto done

:clean
if exist app.db del /q app.db
if exist app.db-journal del /q app.db-journal
if exist app.db-wal del /q app.db-wal
if exist workspace rmdir /s /q workspace
echo [local] removed app.db and workspace (tables are recreated on next start)
goto done

:done
popd
endlocal
