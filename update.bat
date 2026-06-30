@echo off
chcp 65001 >nul
cd /d "%~dp0"

rem Pythonを自動検出（py → python の順で試す）
set "PYEXE="
where py >nul 2>nul && set "PYEXE=py"
if not defined PYEXE where python >nul 2>nul && set "PYEXE=python"
if not defined PYEXE (
  echo [エラー] Python が見つかりません。python.org から Python をインストールし、「Add to PATH」にチェックを入れてください。
  goto end
)

echo 使用 Python: %PYEXE%
%PYEXE% --version
echo.
echo 初回のみ必要: ライブラリを確認・インストール...
%PYEXE% -m pip install -r requirements.txt
echo.
echo 戦績を更新します...
%PYEXE% update.py

:end
echo.
echo === 終了しました（エラーがあれば上に表示） ===
pause
