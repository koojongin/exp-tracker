# EXP Tracker

A compact Windows desktop EXP tracker that reads the visible EXP number and percentage using OCR.

[한국어 사용법](README.ko.md)

## Download

Download **ExpTracker-v1.9.1-windows-x64.exe** from the [latest release](https://github.com/koojongin/exp-tracker/releases/latest). Run it directly; Python is not required.

Windows 10/11, 64-bit. This is an unsigned executable.

## Quick start

1. Open the game in windowed or borderless mode, with its EXP HUD visible.
2. Open **Settings** and select the game window. Click **Refresh** if needed.
3. Use **Select EXP area** to include the EXP number and `[percentage%]`, with some margin. Exclude the bar. Select the level number separately, or turn off **Auto level** and enter the level manually.
4. Click **Test OCR**, confirm the reading, then **Start**. Keep the capture areas visible.
5. Choose **Language / 언어 → English** or **한국어** in Settings. The choice is saved and takes effect immediately, including during a session.

**Start / Pause**, **Reset**, session time and statistics stay on the compact main window. Capture settings, preview and CSV export are in Settings. The default main window is 360 × 440 at 100% scaling and adapts to monitor DPI.

**If the level is not detected:** click **Re-select level area**, then drag around the level number only, excluding `LV`. OCR is tested automatically after a valid selection. Settings shows separate EXP and level capture previews. Default areas are only a starting point; select both areas for your own game layout. Settings opens automatically on a new installation. Alternatively, turn off Auto level and enter the correct level manually; update it yourself after leveling up.

## Statistics

- Session EXP gained and percentage gained.
- Average EXP per minute, estimated EXP per hour and EXP gained in the last 60 seconds.
- Start/current level and EXP, EXP remaining and estimated time to the next level.
- Elapsed session time in `HH:MM:SS`, active measurement time and level-ups.

The percentage adds progress within each level. For example, starting at 45.70% and reaching 10% of the next level gives **+64.30%**, even though those levels require different amounts of EXP.

Gains during pauses, focus gaps and capture outages longer than 20 seconds are excluded. Session time continues during pauses; average rates use active measurement time. EXP losses do not reduce the displayed total gains. The ETA uses the net rate, including losses. Short sessions produce estimated rates.

## Capture and data

The app captures small visible screen regions. It does not read game memory, inject input, install hooks or send captured images to a server. OCR runs locally, with one thread and a default three-second sampling interval. Changing the UI language does not reset the session.

Settings and CSV logs are stored in `%LOCALAPPDATA%\MapleExpMeter`. **Open log folder** opens the CSV directory. These personal files are not included in this repository or release.

The bundled EXP table supports levels **1–99** for the target client. A level-100/MAX display is not supported. It is not a universal EXP table: other clients or versions need their own data. Readings that disagree with the level/EXP table are rejected. Multiple level-ups between two readings are not supported. Re-select capture areas after changing the game resolution or HUD layout.

## Run from source

Use Windows x64 and Python 3.12:

```powershell
python -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements.txt
.venv\Scripts\python.exe maple_exp_meter.py
```

## Test and build

```powershell
.venv\Scripts\python.exe -m unittest test_meter test_i18n -v
.venv\Scripts\python.exe -m pip install -r requirements-build.txt
.venv\Scripts\python.exe -m PyInstaller --noconfirm MapleExpMeter.spec
```

The executable is written to `dist\MapleExpMeter.exe`. The spec uses relative paths and embeds the per-monitor DPI manifest. The Windows GUI test creates a test window with OCR/capture disabled. Catalog/core tests also run without a Windows desktop.

Original application code is MIT licensed. Third-party components and reference data retain their respective licenses; see [THIRD_PARTY_NOTICES.txt](THIRD_PARTY_NOTICES.txt). This is an unofficial community tool.
