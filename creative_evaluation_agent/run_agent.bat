@echo off
setlocal
chcp 65001 >nul
set PYTHONIOENCODING=utf-8
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
    echo [Setup] 최초 실행: 가상환경 생성 중...
    python -m venv .venv
    if errorlevel 1 (
        echo Python이 설치되어 있지 않거나 PATH에 없습니다. Python 3.10+ 설치 후 다시 실행하세요.
        pause
        exit /b 1
    )
    echo [Setup] 패키지 설치 중... ^(최초 1회, 몇 분 걸릴 수 있습니다^)
    ".venv\Scripts\python.exe" -m pip install --quiet --upgrade pip
    ".venv\Scripts\python.exe" -m pip install --quiet -r requirements.txt
)

".venv\Scripts\python.exe" run.py

echo.
pause
