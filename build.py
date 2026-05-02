#!/usr/bin/env python3
"""
Build script per KaraokeAI Studio
Esegui: python build.py
Output: dist/KaraokeAI_Studio.exe (Windows) o dist/KaraokeAI_Studio (Mac)
"""
import subprocess
import sys
import os

def main():
    print("=== KaraokeAI Studio - Build ===\n")

    # 1. Install dependencies
    print("[1/3] Installazione dipendenze...")
    deps = [
        "customtkinter",
        "openai-whisper",
        "pillow",
        "numpy",
        "ffmpeg-python",
        "pyinstaller",
        "torch",          # required by whisper
        "torchaudio",
    ]
    for dep in deps:
        print(f"  → {dep}")
        subprocess.run([sys.executable, "-m", "pip", "install", dep, "-q"], check=False)

    print("\n[2/3] Compilazione con PyInstaller...")

    # PyInstaller command
    cmd = [
        sys.executable, "-m", "PyInstaller",
        "--noconfirm",
        "--onefile",                  # single exe
        "--windowed",                 # no console window (GUI app)
        "--name", "KaraokeAI_Studio",
        "--add-data", f"main.py{os.pathsep}.",
        # collect whisper data files
        "--collect-data", "whisper",
        "--collect-data", "customtkinter",
        "--hidden-import", "whisper",
        "--hidden-import", "customtkinter",
        "--hidden-import", "torch",
        "--hidden-import", "numpy",
        "--hidden-import", "PIL",
        "main.py"
    ]

    result = subprocess.run(cmd, capture_output=False)

    if result.returncode == 0:
        print("\n✅ Build completato!")
        if sys.platform == "win32":
            print("   → dist\\KaraokeAI_Studio.exe")
        else:
            print("   → dist/KaraokeAI_Studio")
        print("\nNOTA: Assicurati che ffmpeg sia installato sul PC target:")
        print("  Windows: https://ffmpeg.org/download.html")
        print("  Mac:     brew install ffmpeg")
    else:
        print("\n❌ Build fallito. Controlla gli errori sopra.")
        sys.exit(1)

if __name__ == "__main__":
    main()
