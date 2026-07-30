@echo off
REM Cria (ou atualiza) o atalho "Gab's FinLab" na area de trabalho,
REM com o icone do cerebro e apontando para o iniciar.bat.
setlocal

set RAIZ=%~dp0
set ALVO=%RAIZ%iniciar.bat
set ICONE=%RAIZ%web\assets\finlab.ico

powershell -NoProfile -ExecutionPolicy Bypass -Command ^
  "$desktop = [Environment]::GetFolderPath('Desktop');" ^
  "$ws = New-Object -ComObject WScript.Shell;" ^
  "$lnk = $ws.CreateShortcut((Join-Path $desktop 'Gab''s FinLab.lnk'));" ^
  "$lnk.TargetPath = '%ALVO%';" ^
  "$lnk.WorkingDirectory = '%RAIZ%';" ^
  "$lnk.IconLocation = '%ICONE%,0';" ^
  "$lnk.Description = 'Gab''s FinLab - monitor fundamentalista B3';" ^
  "$lnk.Save();" ^
  "Write-Host '';" ^
  "Write-Host 'Atalho criado na area de trabalho: Gab''s FinLab' -ForegroundColor Green"

if errorlevel 1 (
  echo.
  echo [ERRO] Nao foi possivel criar o atalho.
  pause
  exit /b 1
)

echo.
echo Pronto! Duplo clique no atalho "Gab's FinLab" da area de trabalho abre o painel.
pause
endlocal
