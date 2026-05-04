import sys as _sys, io as _io
# Fix per PyInstaller windowed mode
if _sys.stdout is None: _sys.stdout = _io.StringIO()
if _sys.stderr is None: _sys.stderr = _io.StringIO()

import customtkinter as ctk
import tkinter as tk
from tkinter import filedialog, messagebox
import threading
import subprocess
import os
import shutil
from pathlib import Path
import whisper
import uuid

def _get_base():
    if getattr(_sys, "frozen", False):
        return Path(_sys.executable).parent
    return Path(__file__).parent

def _get_bin(name):
    base = _get_base()
    ext = ".exe" if os.name == "nt" else ""
    local = base / f"{name}{ext}"
    if local.exists(): return str(local)
    path_name = shutil.which(name)
    return path_name if path_name else name

FFMPEG = _get_bin("ffmpeg")

class KaraokeApp(ctk.CTk):
    def __init__(self):
        super().__init__()
        self.title("KaraokeAI Studio Pro")
        self.geometry("1100x700")
        self.configure(fg_color="#0d0d0f")
        
        self.audio_path = None
        self.lyrics_data = []
        
        self._setup_ui()

    def _setup_ui(self):
        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(0, weight=1)

        # Sidebar con larghezza fissa e scroll per i menu
        self.sidebar = ctk.CTkScrollableFrame(self, width=300, corner_radius=0, fg_color="#16161a")
        self.sidebar.grid(row=0, column=0, sticky="nsew")

        # Sezione Caricamento
        ctk.CTkLabel(self.sidebar, text="1. AUDIO", font=("Arial", 12, "bold")).pack(pady=(20,5))
        self.btn_load = ctk.CTkButton(self.sidebar, text="Scegli File", command=self._load_audio)
        self.btn_load.pack(pady=5, padx=20)
        self.lbl_audio = ctk.CTkLabel(self.sidebar, text="Nessun file", text_color="gray", wraplength=250)
        self.lbl_audio.pack(pady=5)

        # Sezione Parametri
        ctk.CTkLabel(self.sidebar, text="2. IMPOSTAZIONI", font=("Arial", 12, "bold")).pack(pady=(20,5))
        
        self.res_var = ctk.StringVar(value="1080p")
        ctk.CTkLabel(self.sidebar, text="Risoluzione:").pack()
        self.menu_res = ctk.CTkOptionMenu(self.sidebar, variable=self.res_var, values=["1080p", "720p", "480p"])
        self.menu_res.pack(pady=5)

        self.model_var = ctk.StringVar(value="base")
        ctk.CTkLabel(self.sidebar, text="Modello AI:").pack()
        self.menu_model = ctk.CTkOptionMenu(self.sidebar, variable=self.model_var, values=["tiny", "base", "small"])
        self.menu_model.pack(pady=5)

        # Azioni
        ctk.CTkLabel(self.sidebar, text="3. AZIONI", font=("Arial", 12, "bold")).pack(pady=(20,5))
        self.btn_sync = ctk.CTkButton(self.sidebar, text="Avvia Trascrizione", fg_color="#7c3aed", command=self._start_sync)
        self.btn_sync.pack(pady=10, padx=20)
        
        self.btn_export = ctk.CTkButton(self.sidebar, text="Esporta Video", fg_color="#22c55e", command=self._export_video)
        self.btn_export.pack(pady=10, padx=20)
        
        self.progress = ctk.CTkProgressBar(self.sidebar)
        self.progress.pack(pady=10, padx=20); self.progress.set(0)

        # Editor di testo a destra
        self.editor = ctk.CTkTextbox(self, font=("Courier New", 12))
        self.editor.grid(row=0, column=1, sticky="nsew", padx=20, pady=20)

    def _load_audio(self):
        path = filedialog.askopenfilename()
        if path:
            self.audio_path = path
            self.lbl_audio.configure(text=os.path.basename(path), text_color="#22c55e")

    def _start_sync(self):
        if not self.audio_path:
            return messagebox.showwarning("Errore", "Carica un file audio!")
        self.btn_sync.configure(state="disabled")
        self.progress.set(0.2)
        threading.Thread(target=self._worker_sync, daemon=True).start()

    def _worker_sync(self):
        try:
            model = whisper.load_model(self.model_var.get())
            result = model.transcribe(self.audio_path, word_timestamps=True)
            self.lyrics_data = result["segments"]
            
            self.after(0, self._update_editor)
        except Exception as e:
            self.after(0, lambda: messagebox.showerror("Errore AI", str(e)))
        finally:
            self.after(0, lambda: [self.btn_sync.configure(state="normal"), self.progress.set(1)])

    def _update_editor(self):
        self.editor.delete("1.0", "end")
        for s in self.lyrics_data:
            self.editor.insert("end", f"[{s['start']:.2f}] {s['text']}\n")

    def _export_video(self):
        if not self.lyrics_data:
            return messagebox.showwarning("Errore", "Trascrivi prima l'audio!")
        out = filedialog.asksaveasfilename(defaultextension=".mp4")
        if out:
            self.btn_export.configure(state="disabled")
            threading.Thread(target=self._worker_export, args=(out,), daemon=True).start()

    def _worker_export(self, out_path):
        ass_path = self._build_ass()
        res = {"1080p": "1920x1080", "720p": "1280x720", "480p": "854x480"}[self.res_var.get()]
        
        # Prova accelerazione hardware, altrimenti fallback su cpu
        cmd = [
            FFMPEG, "-y", "-f", "lavfi", "-i", f"color=c=black:s={res}:d=3600",
            "-i", self.audio_path,
            "-vf", f"ass='{ass_path.replace(':', r'\:')}'",
            "-c:v", "libx264", "-preset", "fast", "-crf", "22", "-c:a", "aac", "-shortest", out_path
        ]
        
        try:
            subprocess.run(cmd, check=True, creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0)
            self.after(0, lambda: messagebox.showinfo("Fatto", "Video esportato con successo!"))
        except Exception as e:
            self.after(0, lambda: messagebox.showerror("Errore Export", str(e)))
        finally:
            if os.path.exists(ass_path): os.remove(ass_path)
            self.after(0, lambda: self.btn_export.configure(state="normal"))

    def _build_ass(self):
        res_map = {"1080p": (1920, 1080), "720p": (1280, 720), "480p": (854, 480)}
        w, h = res_map[self.res_var.get()]
        temp_ass = Path(os.getcwd()) / f"tmp_{uuid.uuid4().hex}.ass"
        
        with open(temp_ass, "w", encoding="utf-8") as f:
            f.write(f"[Script Info]\nPlayResX: {w}\nPlayResY: {h}\n\n")
            f.write("[V4+ Styles]\nFormat: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Alignment, BorderStyle, Outline, Shadow, MarginV\n")
            f.write(f"Style: Default,Arial,45,&H00FFFFFF,&H0000FFFF,&H00000000,&H00000000,-1,2,1,2,0,60\n\n")
            f.write("[Events]\nFormat: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n")
            
            for seg in self.lyrics_data:
                start = self._fmt_time(seg["start"])
                end = self._fmt_time(seg["end"])
                # Effetto Karaoke parola per parola
                k_text = ""
                if "words" in seg:
                    for w_data in seg["words"]:
                        dur = int((w_data["end"] - w_data["start"]) * 100)
                        k_text += f"{{\\k{dur}}}{w_data['word']} "
                else:
                    k_text = seg["text"]
                f.write(f"Dialogue: 0,{start},{end},Default,,0,0,0,,{k_text}\n")
        return str(temp_ass)

    def _fmt_time(self, s):
        m, s = divmod(s, 60); h, m = divmod(m, 60)
        return f"{int(h)}:{int(m):02d}:{s:05.2f}"

if __name__ == "__main__":
    app = KaraokeApp()
    app.mainloop()
