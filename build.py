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
          # Installazione ottimizzata: usiamo CPU-only per torch per ridurre drasticamente la dimensione dell'EXE
          pip install torch torchaudio --index-url https://download.pytorch.org/whl/cpu
          pip install customtkinter openai-whisper pillow numpy pyinstaller tiktoken

      - name: Scarica FFmpeg (Static Build)
        shell: pwsh
        run: |
          # Scarichiamo una versione specifica e stabile per evitare problemi con "latest"
          $url = "https://www.gyan.dev/ffmpeg/builds/ffmpeg-release-essentials.zip"
          Invoke-WebRequest -Uri $url -OutFile ffmpeg.zip
          Expand-Archive -Path ffmpeg.zip -DestinationPath temp_ffmpeg
          # Cerchiamo i binari e li portiamo nella root
          Get-ChildItem -Path "temp_ffmpeg" -Recurse -Filter "ffmpeg.exe" | Select-Object -First 1 | Copy-Item -Destination "ffmpeg.exe"
          Get-ChildItem -Path "temp_ffmpeg" -Recurse -Filter "ffprobe.exe" | Select-Object -First 1 | Copy-Item -Destination "ffprobe.exe"
          Remove-Item -Recurse -Force temp_ffmpeg, ffmpeg.zip

      - name: Pre-scarica modello Whisper tiny
        run: |
          # Scarica il modello nella cache standard di sistema
          python -c "import whisper; whisper.load_model('tiny')"

      - name: Organizza modelli per bundling
        shell: pwsh
        run: |
          $dest = "whisper_models"
          if (!(Test-Path $dest)) { New-Item -ItemType Directory -Path $dest }
          # Percorso standard della cache di Whisper su Windows
          $userProfile = $env:USERPROFILE
          $modelDir = Join-Path $userProfile ".cache\whisper"
          if (Test-Path $modelDir) {
              Get-ChildItem -Path $modelDir -Filter "*.pt" | Copy-Item -Destination $dest
              Write-Host "Modelli copiati in $dest"
          } else {
              Write-Error "Directory modelli non trovata!"
              exit 1
          }

      - name: Compila EXE con PyInstaller
        shell: pwsh
        run: |
          # Note sulla compilazione:
          # 1. --collect-all è necessario per librerie complesse come torch e whisper
          # 2. --exclude-module riduce il peso rimuovendo librerie pesanti non necessarie (es. test, notebook)
          pyinstaller `
            --noconfirm `
            --onefile `
            --windowed `
            --name "KaraokeAI_Studio" `
            --add-binary "ffmpeg.exe;." `
            --add-binary "ffprobe.exe;." `
            --add-data "whisper_models;whisper_models" `
            --collect-all whisper `
            --collect-all customtkinter `
            --collect-all tiktoken `
            --collect-submodules torch `
            --copy-metadata torch `
            --copy-metadata tqdm `
            --copy-metadata regex `
            --copy-metadata requests `
            --copy-metadata packaging `
            --copy-metadata filelock `
            --copy-metadata numpy `
            --copy-metadata tokenizers `
            --hidden-import whisper `
            --hidden-import PIL.ImageResampling `
            --exclude-module matplotlib `
            --exclude-module notebook `
            --exclude-module scipy `
            main.py

      - name: Carica EXE come artifact
        uses: actions/upload-artifact@v4
        with:
          name: KaraokeAI_Studio_Windows
          path: dist/KaraokeAI_Studio.exe
          retention-days: 30
