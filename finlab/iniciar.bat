@echo off
REM Gab's FinLab - sobe o painel e abre no navegador.
setlocal

cd /d "%~dp0.."
set RAIZ=%cd%

if not exist "%RAIZ%\.venv" (
  echo -^> criando ambiente virtual em .venv
  python -m venv "%RAIZ%\.venv"
)

echo -^> instalando dependencias
"%RAIZ%\.venv\Scripts\pip.exe" install -q --upgrade pip
"%RAIZ%\.venv\Scripts\pip.exe" install -q -r "%RAIZ%\finlab\requirements.txt"

if "%FINLAB_PORT%"=="" set FINLAB_PORT=8777
if "%FINLAB_HOST%"=="" set FINLAB_HOST=127.0.0.1

echo -^> Gab's FinLab em http://%FINLAB_HOST%:%FINLAB_PORT%
start "" "http://%FINLAB_HOST%:%FINLAB_PORT%"

"%RAIZ%\.venv\Scripts\python.exe" -m uvicorn finlab.backend.app:app --host %FINLAB_HOST% --port %FINLAB_PORT%

endlocal
