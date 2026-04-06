@echo off
chcp 65001 >nul
echo ========================================
echo  OrionParser VSIX ビルド
echo ========================================
echo.

cd /d "%~dp0"

:: --- 依存パッケージのインストール ---
echo [1/3] npm install ...
call npm install
if errorlevel 1 (
    echo ERROR: npm install に失敗しました
    pause
    exit /b 1
)
echo.

:: --- TypeScript コンパイル ---
echo [2/3] TypeScript コンパイル ...
call npx tsc -p ./
if errorlevel 1 (
    echo ERROR: コンパイルに失敗しました
    pause
    exit /b 1
)
echo.

:: --- VSIX パッケージ作成 ---
echo [3/3] VSIX パッケージ作成 ...
call npx --yes @vscode/vsce package --no-dependencies
if errorlevel 1 (
    echo ERROR: VSIX パッケージ作成に失敗しました
    pause
    exit /b 1
)
echo.

:: --- 結果表示 ---
for %%f in (*.vsix) do (
    echo ========================================
    echo  完成: %%f
    echo ========================================
    echo.
    echo インストール方法:
    echo   code --install-extension %%f
    echo.
    echo または VSCode で Ctrl+Shift+P ^>
    echo   "Extensions: Install from VSIX..." ^> %%f を選択
)

pause
