name: Build KaraokeAI Studio EXE

on:
  push:
    branches: [ main ]
  workflow_dispatch:

env:
  FORCE_JAVASCRIPT_ACTIONS_TO_NODE24: true

jobs:
  build-windows:
    runs-on: windows-latest

    steps:
      - name: Checkout codice
        uses: actions/checkout@v4

      - name: Installa Python 3.11
        uses: actions/setup-python@v5
        with:
          python-version: "3.11"
          cache: 'pip'

      - name: Installa dipendenze Python
        run: |
          python -m pip install --upgrade pip
          pip install customtkinter openai-whisper pillow numpy pyinstaller tiktoken torch torchaudio --index-url https://download.pytorch.org/whl/cpu

      - name: Scarica modello Whisper tiny
        run: |
          python -c "import whisper; whisper.load_model('tiny')"

      - name: Scarica FFmpeg
        run: |
          curl -L "https://github.com/BtbN/FFmpeg-Builds/releases/download/latest/ffmpeg-master-latest-win64-gpl.zip" -o ffmpeg.zip
          Expand-Archive -Path ffmpeg.zip -DestinationPath . -Force
          Get-ChildItem -Path "ffmpeg-master-latest-win64-gpl" -Recurse -Filter "ffmpeg.exe" | Copy-Item -Destination "ffmpeg.exe" -Force
          Get-ChildItem -Path "ffmpeg-master-latest-win64-gpl" -Recurse -Filter "ffprobe.exe" | Copy-Item -Destination "ffprobe.exe" -Force

      - name: Copia modelli Whisper
        run: |
          python -c "
          import os, shutil, whisper
          model_dir = os.path.join(os.path.expanduser('~'), '.cache', 'whisper')
          dest = 'whisper_models'
          os.makedirs(dest, exist_ok=True)
          for f in os.listdir(model_dir):
              if 'tiny' in f.lower():
                  shutil.copy2(os.path.join(model_dir, f), os.path.join(dest, f))
                  print('Copiato:', f)
          "

      - name: Compila EXE con PyInstaller
        run: |
          pyinstaller `
            --noconfirm `
            --onefile `
            --windowed `
            --name "KaraokeAI_Studio" `
            --add-binary "ffmpeg.exe;." `
            --add-binary "ffprobe.exe;." `
            --add-data "whisper_models;whisper_models" `
            --collect-all torch `
            --collect-all torchaudio `
            --collect-all whisper `
            --collect-all customtkinter `
            --collect-all tiktoken `
            --hidden-import whisper `
            --hidden-import whisper.transcribe `
            --hidden-import whisper.model `
            --hidden-import whisper.decoding `
            --hidden-import customtkinter `
            --hidden-import torch `
            --hidden-import tiktoken `
            --hidden-import numpy `
            --hidden-import PIL.Image `
            --hidden-import tkinter.filedialog `
            main.py

      - name: Carica EXE come artifact
        uses: actions/upload-artifact@v4
        with:
          name: KaraokeAI_Studio_Windows
          path: dist/KaraokeAI_Studio.exe
          retention-days: 30
