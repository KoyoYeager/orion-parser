@echo off
echo ========================================
echo  OrionParser VSIX Build
echo ========================================
echo.

cd /d "%~dp0"

:: --- Install dependencies ---
echo [1/3] npm install ...
call npm install
if errorlevel 1 (
    echo ERROR: npm install failed
    pause
    exit /b 1
)
echo.

:: --- TypeScript compile ---
echo [2/3] TypeScript compile ...
call npx tsc -p ./
if errorlevel 1 (
    echo ERROR: TypeScript compile failed
    pause
    exit /b 1
)
echo.

:: --- Create VSIX package ---
echo [3/3] Creating VSIX package ...
call npx --yes @vscode/vsce package --no-dependencies
if errorlevel 1 (
    echo ERROR: VSIX packaging failed
    pause
    exit /b 1
)
echo.

:: --- Show result ---
for %%f in (*.vsix) do (
    echo ========================================
    echo  Done: %%f
    echo ========================================
    echo.
    echo Install:
    echo   code --install-extension %%f
    echo.
    echo Or in VSCode: Ctrl+Shift+P
    echo   "Extensions: Install from VSIX..."
)

pause
