import sys as _sys, io as _io
if _sys.stdout is None: _sys.stdout = _io.StringIO()
if _sys.stderr is None: _sys.stderr = _io.StringIO()

import customtkinter as ctk
import tkinter as tk
from tkinter import filedialog, messagebox
import threading
import json
import os
import subprocess
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
    candidates = [base / name]
    if os.name == "nt" and not name.lower().endswith(".exe"):
        candidates.append(base / f"{name}.exe")
    elif os.name != "nt" and name.lower().endswith(".exe"):
        candidates.append(base / name[:-4])
    for local in candidates:
        if local.exists(): return str(local)
    path_name = shutil.which(name)
    return path_name if path_name else name

FFMPEG  = _get_bin("ffmpeg")
FFPROBE = _get_bin("ffprobe")

GRADIENTS = {
    "Viola → Blu":    [(80,0,160),(0,20,180)],
    "Rosso → Arancio":[(180,0,40),(200,80,0)],
    "Verde → Ciano":  [(0,120,40),(0,160,160)],
}

QR_POS_MAP = {
    "Basso destra":   ("W-s-20", "H-s-20"),
    "Basso sinistra": ("20", "H-s-20"),
    "Alto destra":    ("W-s-20", "20"),
    "Alto sinistra":  ("20", "20"),
}

class KaraokeApp(ctk.CTk):
    def __init__(self):
        super().__init__()
        self.title("KaraokeAI Studio Pro"); self.geometry("1280x900")
        self.audio_path=None; self.lyrics_data=[]; self.audio_duration=0.0
        self.qr_path=None; self.whisper_model=None
        self._build_ui()

    def _build_ui(self):
        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(0, weight=1)

        # PANNELLO SINISTRO (Scrollable)
        self.sidebar = ctk.CTkScrollableFrame(self, width=350, corner_radius=0, fg_color="#16161a")
        self.sidebar.grid(row=0, column=0, sticky="nsew")

        ctk.CTkLabel(self.sidebar, text="CONFIGURAZIONE", font=("Arial", 16, "bold")).pack(pady=20)

        # Audio
        ctk.CTkButton(self.sidebar, text="📂 Carica Audio", command=self._load_audio).pack(fill="x", padx=20, pady=10)
        self.audio_lbl = ctk.CTkLabel(self.sidebar, text="Nessun file", text_color="gray")
        self.audio_lbl.pack()

        # Qualità AI
        ctk.CTkLabel(self.sidebar, text="Modello Whisper:").pack(pady=(10,0))
        self.model_var = ctk.StringVar(value="base")
        ctk.CTkOptionMenu(self.sidebar, variable=self.model_var, values=["tiny", "base", "small"]).pack(pady=5)

        # Risoluzione (Fix Visualizzazione)
        ctk.CTkLabel(self.sidebar, text="Risoluzione Video:").pack(pady=(10,0))
        self.res_var = ctk.StringVar(value="1080p")
        self.res_map = {"1080p":(1920,1080), "720p":(1280,720), "480p":(854,480)}
        ctk.CTkOptionMenu(self.sidebar, variable=self.res_var, values=list(self.res_map.keys())).pack(pady=5)

        # Export
        self.sync_btn = ctk.CTkButton(self.sidebar, text="🎙 Genera Trascrizione", fg_color="#7c3aed", command=self._start_sync)
        self.sync_btn.pack(fill="x", padx=20, pady=20)

        self.export_btn = ctk.CTkButton(self.sidebar, text="⬇ ESPORTA MP4", fg_color="#22c55e", command=self._export_video)
        self.export_btn.pack(fill="x", padx=20, pady=10)
        
        self.prog = ctk.CTkProgressBar(self.sidebar)
        self.prog.pack(fill="x", padx=20); self.prog.set(0)

        # AREA DESTRA
        self.main_view = ctk.CTkFrame(self, fg_color="#0d0d0f")
        self.main_view.grid(row=0, column=1, sticky="nsew", padx=10, pady=10)
        
        ctk.CTkLabel(self.main_view, text="Editor Testi (Parola per Parola attivato)").pack(pady=10)
        self.txt_edit = ctk.CTkTextbox(self.main_view, font=("Courier New", 13))
        self.txt_edit.pack(fill="both", expand=True, padx=20, pady=20)

    def _load_audio(self):
        p = filedialog.askopenfilename()
        if p:
            self.audio_path = p
            self.audio_lbl.configure(text=Path(p).name, text_color="#22c55e")

    def _start_sync(self):
        if not self.audio_path: return
        self.sync_btn.configure(state="disabled")
        threading.Thread(target=self._sync_worker, daemon=True).start()

    def _sync_worker(self):
        model = whisper.load_model(self.model_var.get())
        result = model.transcribe(self.audio_path, word_timestamps=True)
        self.lyrics_data = result["segments"]
        
        full_text = ""
        for seg in self.lyrics_data:
            full_text += f"[{seg['start']:.2f} -> {seg['end']:.2f}] {seg['text']}\n"
        
        self.after(0, lambda: self.txt_edit.insert("1.0", full_text))
        self.after(0, lambda: self.sync_btn.configure(state="normal"))

    def _export_video(self):
        if not self.lyrics_data: return
        out = filedialog.asksaveasfilename(defaultextension=".mp4")
        if not out: return
        
        self.export_btn.configure(state="disabled")
        threading.Thread(target=self._export_worker, args=(out,), daemon=True).start()

    def _export_worker(self, out_path):
        try:
            res = self.res_map[self.res_var.get()]
            ass_file = self._generate_karaoke_ass(res[0], res[1])
            
            # Check per GPU NVIDIA
            has_gpu = False
            try:
                chk = subprocess.run([FFMPEG, "-encoders"], capture_output=True, text=True)
                if "h264_nvenc" in chk.stdout: has_gpu = True
            except: pass

            v_encoder = "libx264" if not has_gpu else "h264_nvenc"
            
            cmd = [
                FFMPEG, "-y",
                "-f", "lavfi", "-i", f"color=c=black:s={res[0]}x{res[1]}:d=100", # placeholder dur
                "-i", self.audio_path,
                "-vf", f"ass={ass_file.replace(':', r'\:')}",
                "-c:v", v_encoder, "-pix_fmt", "yuv420p", "-shortest",
                out_path
            ]
            
            subprocess.run(cmd, check=True)
            self.after(0, lambda: messagebox.showinfo("Successo", "Video Creato!"))
        except Exception as e:
            self.after(0, lambda: messagebox.showerror("Errore", str(e)))
        finally:
            self.after(0, lambda: self.export_btn.configure(state="normal"))

    def _generate_karaoke_ass(self, w, h):
        path = Path(_get_base()) / f"{uuid.uuid4().hex}.ass"
        with open(path, "w", encoding="utf-8") as f:
            f.write(f"[Script Info]\nPlayResX: {w}\nPlayResY: {h}\n\n")
            f.write("[V4+ Styles]\nFormat: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Alignment, BorderStyle, Outline, Shadow, MarginV\n")
            # SecondaryColour è il colore della parola "attiva"
            f.write(f"Style: Default,Arial,48,&H00FFFFFF,&H0000FFFF,&H00000000,&H00000000,-1,2,1,2,1,50\n\n")
            f.write("[Events]\nFormat: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n")
            
            for seg in self.lyrics_data:
                start = self._fmt_ass(seg["start"])
                end = self._fmt_ass(seg["end"])
                
                # Generazione Karaoke Tag {\k...}
                karaoke_text = ""
                for word in seg["words"]:
                    duration = int((word["end"] - word["start"]) * 100)
                    karaoke_text += f"{{\\k{duration}}}{word['word']} "
                
                f.write(f"Dialogue: 0,{start},{end},Default,,0,0,0,,{karaoke_text}\n")
        return str(path)

    def _fmt_ass(self, s):
        m, s = divmod(s, 60); h, m = divmod(m, 60)
        return f"{int(h)}:{int(m):02d}:{s:05.2f}"

if __name__ == "__main__":
    app = KaraokeApp()
    app.mainloop()
