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

# --- LOGICA DI SISTEMA ---
def _get_base():
    if getattr(_sys, "frozen", False): return Path(_sys.executable).parent
    return Path(__file__).parent

def _get_bin(name):
    base = _get_base()
    ext = ".exe" if os.name == "nt" else ""
    candidates = [base / f"{name}{ext}"]
    for c in candidates:
        if c.exists(): return str(c)
    return shutil.which(name) or name

FFMPEG = _get_bin("ffmpeg")
FFPROBE = _get_bin("ffprobe")

# --- COSTANTI E PRESET ---
GRADIENTS = {
    "Viola → Blu":    [(80,0,160),(0,20,180)],
    "Rosso → Arancio":[(180,0,40),(200,80,0)],
    "Verde → Ciano":  [(0,120,40),(0,160,160)],
    "Tramonto":       [(120,0,80),(200,60,0)],
}

QR_POS_MAP = {
    "Basso destra":   ("W-{s}-20", "H-{s}-20"),
    "Basso sinistra": ("20",        "H-{s}-20"),
    "Alto destra":    ("W-{s}-20", "20"),
    "Alto sinistra":  ("20",        "20"),
}

class KaraokeApp(ctk.CTk):
    def __init__(self):
        super().__init__()
        self.title("KaraokeAI Studio Pro"); self.geometry("1280x860")
        self.audio_path=None; self.lyrics_lines=[]; self.audio_duration=0.0
        self.qr_path=None; self.whisper_model=None
        self._build_ui()

    def _build_ui(self):
        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(0, weight=1)

        # SIDEBAR (Ora Scrollable per contenere tutto senza nascondere i menu)
        self.sidebar = ctk.CTkScrollableFrame(self, width=320, corner_radius=0, fg_color="#16161a")
        self.sidebar.grid(row=0, column=0, sticky="nsew")

        # 1. Caricamento Audio
        ctk.CTkLabel(self.sidebar, text="① AUDIO", font=("Arial", 12, "bold"), text_color="#a855f7").pack(pady=(20,5))
        self.btn_audio = ctk.CTkButton(self.sidebar, text="Scegli Canzone", command=self._load_audio, fg_color="#7c3aed")
        self.btn_audio.pack(pady=5, padx=20)
        self.lbl_audio = ctk.CTkLabel(self.sidebar, text="Nessun file", text_color="gray", font=("Arial", 10))
        self.lbl_audio.pack()

        # 2. Parametri AI
        ctk.CTkLabel(self.sidebar, text="② TRASCRIZIONE", font=("Arial", 12, "bold"), text_color="#a855f7").pack(pady=(20,5))
        self.model_var = ctk.StringVar(value="base")
        ctk.CTkOptionMenu(self.sidebar, variable=self.model_var, values=["tiny", "base", "small"]).pack(pady=5)
        self.btn_sync = ctk.CTkButton(self.sidebar, text="Avvia Trascrizione AI", command=self._start_sync)
        self.btn_sync.pack(pady=10, padx=20)
        self.progress = ctk.CTkProgressBar(self.sidebar); self.progress.pack(padx=20); self.progress.set(0)

        # 3. Personalizzazione Video
        ctk.CTkLabel(self.sidebar, text="③ STILE VIDEO", font=("Arial", 12, "bold"), text_color="#a855f7").pack(pady=(20,5))
        self.grad_var = ctk.StringVar(value="Viola → Blu")
        ctk.CTkOptionMenu(self.sidebar, variable=self.grad_var, values=list(GRADIENTS.keys())).pack(pady=5)
        
        ctk.CTkLabel(self.sidebar, text="Risoluzione:").pack()
        self.res_var = ctk.StringVar(value="1080p")
        self.res_map = {"1080p":(1920,1080),"720p":(1280,720),"480p":(854,480)}
        ctk.CTkOptionMenu(self.sidebar, variable=self.res_var, values=list(self.res_map.keys())).pack(pady=5)

        # 4. Logo / Pubblicità
        ctk.CTkLabel(self.sidebar, text="④ LOGO / PUB", font=("Arial", 12, "bold"), text_color="#a855f7").pack(pady=(20,5))
        ctk.CTkButton(self.sidebar, text="Carica Immagine", command=self._load_qr, fg_color="#333").pack(pady=5)
        self.qr_pos_var = ctk.StringVar(value="Basso destra")
        ctk.CTkOptionMenu(self.sidebar, variable=self.qr_pos_var, values=list(QR_POS_MAP.keys())).pack(pady=5)

        # 5. Export
        ctk.CTkLabel(self.sidebar, text="⑤ ESPORTAZIONE", font=("Arial", 12, "bold"), text_color="#a855f7").pack(pady=(20,5))
        self.btn_export = ctk.CTkButton(self.sidebar, text="ESPORTA MP4", fg_color="#22c55e", command=self._export_video)
        self.btn_export.pack(pady=20, padx=20)

        # EDITOR PRINCIPALE (Destra)
        self.main_container = ctk.CTkFrame(self, fg_color="#0d0d0f")
        self.main_container.grid(row=0, column=1, sticky="nsew", padx=10, pady=10)
        
        self.rows_frame = ctk.CTkScrollableFrame(self.main_container, fg_color="#16161a", label_text="Editor Sincronizzazione")
        self.rows_frame.pack(fill="both", expand=True, padx=10, pady=10)

    # --- FUNZIONALITÀ ---
    def _load_audio(self):
        p = filedialog.askopenfilename()
        if p:
            self.audio_path = p
            self.lbl_audio.configure(text=Path(p).name, text_color="#22c55e")
            try:
                r = subprocess.run([FFPROBE, "-v", "quiet", "-show_format", "-print_format", "json", p], capture_output=True, text=True)
                self.audio_duration = float(json.loads(r.stdout)["format"]["duration"])
            except: self.audio_duration = 0.0

    def _load_qr(self):
        p = filedialog.askopenfilename()
        if p: self.qr_path = p

    def _start_sync(self):
        if not self.audio_path: return
        self.btn_sync.configure(state="disabled")
        threading.Thread(target=self._sync_worker, daemon=True).start()

    def _sync_worker(self):
        try:
            model = whisper.load_model(self.model_var.get())
            result = model.transcribe(self.audio_path, word_timestamps=True)
            self.lyrics_lines = result["segments"]
            self.after(0, self._render_rows)
        except Exception as e: self.after(0, lambda: messagebox.showerror("Errore AI", str(e)))
        finally: self.after(0, lambda: self.btn_sync.configure(state="normal"))

    def _render_rows(self):
        for w in self.rows_frame.winfo_children(): w.destroy()
        for i, line in enumerate(self.lyrics_lines):
            row = ctk.CTkFrame(self.rows_frame, fg_color="#1e1e24")
            row.pack(fill="x", pady=2, padx=5)
            ctk.CTkLabel(row, text=f"{i+1}", width=30).pack(side="left")
            e = ctk.CTkEntry(row); e.insert(0, line["text"]); e.pack(side="left", fill="x", expand=True, padx=5)
            # Salvataggio automatico testo
            e.bind("<FocusOut>", lambda event, idx=i, entry=e: self._update_text(idx, entry.get()))

    def _update_text(self, idx, val):
        self.lyrics_lines[idx]["text"] = val

    def _export_video(self):
        if not self.lyrics_lines: return
        out = filedialog.asksaveasfilename(defaultextension=".mp4")
        if out:
            self.btn_export.configure(state="disabled")
            threading.Thread(target=self._export_worker, args=(out,), daemon=True).start()

    def _export_worker(self, out_path):
        ass_path = self._build_ass()
        w, h = self.res_map[self.res_var.get()]
        stops = GRADIENTS[self.grad_var.get()]
        r1,g1,b1 = stops[0]; r2,g2,b2 = stops[1]
        geq = f"r='({r1}+(({r2}-{r1})*Y/H))':g='({g1}+(({g2}-{g1})*Y/H))':b='({b1}+(({b2}-{b1})*Y/H))'"

        cmd = [
            FFMPEG, "-y", "-f", "lavfi", "-i", f"color=black:s={w}x{h}:d={self.audio_duration}",
            "-i", self.audio_path,
        ]
        
        filter_str = f"geq={geq}[bg];"
        if self.qr_path:
            cmd.extend(["-i", self.qr_path])
            x, y = QR_POS_MAP[self.qr_pos_var.get()]
            x = x.replace("{s}", "200").replace("W", "main_w").replace("H", "main_h")
            y = y.replace("{s}", "200").replace("W", "main_w").replace("H", "main_h")
            filter_str += f"[2:v]scale=200:200[qr];[bg][qr]overlay={x}:{y}[bgqr];[bgqr]"
        else: filter_str += "[bg]"
        
        filter_str += f"ass='{ass_path.replace(':', r'\:')}'[v]"
        cmd.extend(["-filter_complex", filter_str, "-map", "[v]", "-map", "1:a", "-c:v", "libx264", "-shortest", out_path])

        try:
            subprocess.run(cmd, check=True, creationflags=0x08000000 if os.name == 'nt' else 0)
            self.after(0, lambda: messagebox.showinfo("Fatto", "Video pronto!"))
        except Exception as e: self.after(0, lambda: messagebox.showerror("Errore", str(e)))
        finally:
            if os.path.exists(ass_path): os.remove(ass_path)
            self.after(0, lambda: self.btn_export.configure(state="normal"))

    def _build_ass(self):
        w, h = self.res_map[self.res_var.get()]
        path = Path(os.getcwd()) / f"tmp_{uuid.uuid4().hex}.ass"
        with open(path, "w", encoding="utf-8") as f:
            f.write(f"[Script Info]\nPlayResX: {w}\nPlayResY: {h}\n\n[V4+ Styles]\n")
            f.write("Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Alignment, BorderStyle, Outline, Shadow, MarginV\n")
            f.write(f"Style: Default,Arial,50,&H00FFFFFF,&H0000FFFF,&H00000000,&H00000000,-1,2,1,2,0,80\n\n[Events]\n")
            f.write("Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n")
            for s in self.lyrics_lines:
                start, end = self._fmt(s["start"]), self._fmt(s["end"])
                f.write(f"Dialogue: 0,{start},{end},Default,,0,0,0,,{s['text']}\n")
        return str(path)

    def _fmt(self, s):
        m, s = divmod(s, 60); h, m = divmod(m, 60)
        return f"{int(h)}:{int(m):02d}:{s:05.2f}"

if __name__ == "__main__": KaraokeApp().mainloop()
