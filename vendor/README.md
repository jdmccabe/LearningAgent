# Offline Wheelhouse

This directory supports offline installation for locked-down environments.

- `requirements-runtime.txt` lists the runtime packages needed by the desktop UI and CLI.
- `wheels/` contains the resolved wheel files for those packages and their dependencies.

Build or refresh the wheelhouse on a network-enabled Windows machine:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\build_offline_wheelhouse.ps1
```

Install from the wheelhouse without internet access:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\install_offline.ps1
```

`run_ui.bat` also uses this wheelhouse automatically if LangGraph, llama-cpp-python, or openpyxl are missing.

The checked-in wheels are intended for Windows amd64 with CPython 3.14. Rebuild the wheelhouse when changing Python versions, operating systems, or dependency versions.
