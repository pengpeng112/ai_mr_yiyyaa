@echo off
chcp 65001 >nul 2>&1
setlocal
cd /d "%~dp0"

set IMAGE_NAME=med-audit
set IMAGE_TAG=latest
set OUTPUT_DIR=%~dp0..

echo.
echo ============================================================
echo   Med-Audit - Docker Image Build and Export
echo ============================================================
echo.

REM ---- Check Docker ----
docker version >nul 2>&1
if %errorlevel% neq 0 (
    echo [ERROR] Docker not found. Please install Docker Desktop.
    pause & exit /b 1
)
for /f "tokens=3" %%i in ('docker version --format "{{.Client.Version}}" 2^>nul') do set DOCKER_VER=%%i
echo [OK] Docker ready
echo.

REM ---- Check oracle-client/linux ----
echo [CHECK] Oracle Client files...
if exist "oracle-client\linux\libclntsh.so.11.1" (
    echo [OK] Oracle Client found
) else (
    echo [WARN] oracle-client\linux\libclntsh.so.11.1 not found
    echo        Oracle query will not be available
)
echo.

REM ---- Build Docker image ----
echo [1/2] Building Docker image %IMAGE_NAME%:%IMAGE_TAG%...
echo       This may take 5-10 minutes on first build...
echo.
docker build -t %IMAGE_NAME%:%IMAGE_TAG% .
if %errorlevel% neq 0 (
    echo [ERROR] Docker build failed
    pause & exit /b 1
)
echo.
echo [OK] Image built successfully
echo.

REM ---- Show image size ----
docker image inspect %IMAGE_NAME%:%IMAGE_TAG% --format "Image size: {{.Size}}" 2>nul
echo.

REM ---- Export image to tar ----
echo [2/2] Exporting image to tar file...
set TARFILE=%OUTPUT_DIR%\med-audit-image.tar
if exist "%TARFILE%" del /f "%TARFILE%"
docker save -o "%TARFILE%" %IMAGE_NAME%:%IMAGE_TAG%
if %errorlevel% neq 0 (
    echo [ERROR] Export failed
    pause & exit /b 1
)
echo [OK] Image exported
echo.

REM Show file sizes
for %%A in ("%TARFILE%") do set TAR_SIZE=%%~zA
set /a TAR_MB=%TAR_SIZE% / 1048576

echo.
echo ============================================================
echo   [DONE] Build complete!
echo ============================================================
echo.
echo   Image tar : %TARFILE% (%TAR_MB% MB)
echo.
echo   Transfer to server:
echo     scp med-audit-image.tar user@192.168.x.x:/opt/
echo.
echo   On server - first deploy:
echo     cd /opt
echo     docker load -i med-audit-image.tar
echo     bash docker_deploy.sh
echo.
echo   On server - upgrade (re-run after new image transfer):
echo     docker load -i med-audit-image.tar
echo     docker-compose up -d
echo ============================================================
echo.
pause
