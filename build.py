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

      - name: Installa dipendenze Python
        run: |
          python -m pip install --upgrade pip
          pip install customtkinter
          pip install openai-whisper
          pip install pillow
          pip install numpy
          pip install pyinstaller
          pip install tiktoken
          pip install torch torchaudio --index-url https://download.pytorch.org/whl/cpu

      - name: Scarica modello Whisper tiny
        run: |
          python -c "import whisper; whisper.load_model('tiny')"
          echo "Modello tiny scaricato"

      - name: Scarica FFmpeg per Windows
        run: |
          curl -L "https://github.com/BtbN/FFmpeg-Builds/releases/download/latest/ffmpeg-master-latest-win64-gpl.zip" -o ffmpeg.zip
          Expand-Archive -Path ffmpeg.zip -DestinationPath ffmpeg_extracted
          $ffmpegBin = Get-ChildItem -Path "ffmpeg_extracted" -Recurse -Filter "ffmpeg.exe" | Select-Object -First 1
          $ffprobeBin = Get-ChildItem -Path "ffmpeg_extracted" -Recurse -Filter "ffprobe.exe" | Select-Object -First 1
          Copy-Item $ffmpegBin.FullName -Destination "ffmpeg.exe"
          Copy-Item $ffprobeBin.FullName -Destination "ffprobe.exe"

      - name: Copia modello Whisper nella cartella progetto
        run: |
          python -c "
          import os, shutil, whisper
          model_dir = os.path.join(os.path.expanduser('~'), '.cache', 'whisper')
          dest = 'whisper_models'
          os.makedirs(dest, exist_ok=True)
          for f in os.listdir(model_dir):
              if 'tiny' in f:
                  shutil.copy(os.path.join(model_dir, f), os.path.join(dest, f))
                  print(f'Copiato: {f}')
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
            --collect-data whisper `
            --collect-data customtkinter `
            --collect-all torch `
            --collect-all tiktoken `
            --hidden-import whisper `
            --hidden-import whisper.audio `
            --hidden-import whisper.model `
            --hidden-import whisper.tokenizer `
            --hidden-import whisper.transcribe `
            --hidden-import whisper.utils `
            --hidden-import customtkinter `
            --hidden-import torch `
            --hidden-import tiktoken `
            --hidden-import tiktoken_ext `
            --hidden-import tiktoken_ext.openai_public `
            --hidden-import numpy `
            --hidden-import PIL `
            --hidden-import PIL.Image `
            --hidden-import tkinter `
            --hidden-import tkinter.filedialog `
            --hidden-import tkinter.messagebox `
            main.py

      - name: Carica EXE come artifact
        uses: actions/upload-artifact@v4
        with:
          name: KaraokeAI_Studio_Windows
          path: dist/KaraokeAI_Studio.exe
          retention-days: 30
