@echo off
title Bot Wallapop - Launcher
:menu
cls
echo ============================
echo      BOT WALLAPOP MENU
echo ============================
echo [1] Configurar entorno (setup completo)
echo [2] Arrancar bot
echo [3] Resetear dependencias
echo [4] Salir
echo ============================
set /p choice=Elige una opcion: 

if "%choice%"=="1" goto setup
if "%choice%"=="2" goto run
if "%choice%"=="3" goto reset
if "%choice%"=="4" exit
goto menu

:setup
echo === Creando entorno virtual (si no existe) ===
if not exist ".venv" (
    python -m venv .venv
)
call .venv\Scripts\activate

echo === Instalando dependencias ===
pip install --upgrade pip
pip install -r requirements.txt

echo === Instalando Playwright chromium ===
playwright install chromium

echo ok > .venv\installed.flag
echo === Setup completo ===
pause
goto menu

:run
if not exist ".venv" (
    echo Entorno no encontrado. Ejecuta primero la opcion [1] Setup.
    pause
    goto menu
)
call .venv\Scripts\activate

REM === Comprobar si existe .env ===
if not exist ".env" (
    call :ask_token
)

REM === Mostrar token actual y preguntar si cambiar ===
set TOKEN_CURRENT=
for /f "tokens=2 delims==" %%A in ('findstr "TELEGRAM_TOKEN" ".env"') do set TOKEN_CURRENT=%%A

echo Token actual: %TOKEN_CURRENT%
set /p CHANGE_TOKEN=Token api correcto? (s/N): 
if /I "%CHANGE_TOKEN%"=="n" call :ask_token

REM === Cargar token desde .env ===
for /f "tokens=2 delims==" %%A in ('findstr "TELEGRAM_TOKEN" ".env"') do set TELEGRAM_TOKEN=%%A

echo === Arrancando bot ===
python src\bot.py
pause
goto menu

:ask_token
echo Introduce tu token de Telegram (desde @BotFather):
set /p TOKEN=
echo TELEGRAM_TOKEN=%TOKEN%> .env
goto :eof

:reset
if not exist ".venv" (
    echo Entorno virtual no encontrado. Ejecuta primero la opcion [1] Setup.
    pause
    goto menu
)
echo === Reseteando dependencias ===
del .venv\installed.flag >nul 2>&1
call .venv\Scripts\activate
pip install --upgrade pip
pip install -r requirements.txt
playwright install chromium
echo ok > .venv\installed.flag
echo === Dependencias reinstaladas ===
pause
goto menu
