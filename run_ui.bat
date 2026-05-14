@echo off
setlocal

cd /d "%~dp0"
set "PYTHONPATH=%CD%\src;%PYTHONPATH%"

python -c "import langgraph, llama_cpp, openpyxl" >nul 2>nul
if errorlevel 1 (
    echo Installing LearningAgent runtime dependencies from the offline wheelhouse...
    if not exist "%CD%\vendor\wheels" (
        echo.
        echo Offline wheelhouse not found: %CD%\vendor\wheels
        echo Build it on a network-enabled machine with scripts\build_offline_wheelhouse.ps1.
        pause
        exit /b 1
    )
    python -m pip install --no-index --find-links "%CD%\vendor\wheels" -r "%CD%\vendor\requirements-runtime.txt"
    if errorlevel 1 (
        echo.
        echo Could not install LearningAgent dependencies from the offline wheelhouse.
        pause
        exit /b 1
    )
    python -m pip install --no-build-isolation --no-deps -e .
    if errorlevel 1 (
        echo.
        echo Could not register LearningAgent from this checkout.
        pause
        exit /b 1
    )
)

python -m learning_agent.ui
if errorlevel 1 (
    echo.
    echo LearningAgent UI exited with an error.
    pause
)
