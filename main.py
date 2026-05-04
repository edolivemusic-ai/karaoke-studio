import sys as _sys, io as _io
if _sys.stdout is None: _sys.stdout = _io.StringIO()
if _sys.stderr is None: _sys.stderr = _io.StringIO()

import customtkinter as ctk
import tkinter as tk
from tkinter import filedialog, messagebox
import threading, json, os, subprocess, shutil, uuid
from pathlib import Path
import whisper

# --- LOGICA BINARI (FFmpeg/FFprobe) ---
def _get_base():
    if getattr(_sys, "frozen", False): return Path(_sys.executable).parent
    return Path(__file__).parent

def _get_bin(name):
    base = _get_base()
    ext = ".exe" if os.name == "nt" else ""
    local = base / f"{name}{ext}"
    if local.exists(): return str(local)
    return shutil.which(name) or name

FFMPEG = _get_bin("ffmpeg")
FFPROBE = _get_bin("ffprobe")
WHISPER_MODEL_DIR = str(_get_base() / "whisper_models")

# --- COSTANTI PROFESSIONALI ---
GRADIENTS = {
    "Viola Notturno": [(80,0,160),(0,20,180)],
    "Fuoco Vulcanico": [(180,0,40),(200,80,0)],
    "Oceano Profondo": [(0,120,40),(0,160,160)],
    "Elegance Black": [(5,5,10),(60,0,120)]
}

QR_POS = {
    "Basso DX": ("W-{s}-30", "H-{s}-30"),
    "Basso SX": ("30", "H-{s}-30"),
    "Alto DX": ("W-{s}-30", "30"),
    "Alto SX": ("30", "30"),
}

class KaraokeApp(ctk.CTk):
    def __init__(self):
        super().__init__()
        self.title("KaraokeAI Studio Pro"); self.geometry("1300x900")
        self.audio_path = None; self.lyrics_lines = []; self.audio_duration = 0.0
        self.qr_path = None
        self._build_interface()

    def _build_interface(self):
        self.grid_columnconfigure(1, weight=1); self.grid_rowconfigure(0, weight=1)
        
        # Sidebar Scrollabile per non perdere i menu
        self.side = ctk.CTkScrollableFrame(self, width=340, corner_radius=0, fg_color="#16161a")
        self.side.grid(row=0, column=0, sticky="nsew")

        self._header("① SORGENTE AUDIO")
        self.btn_a = ctk.CTkButton(self.side, text="Carica Canzone", command=self._load_audio, fg_color="#7c3aed")
        self.btn_a.pack(pady=10, padx=20)
        self.lbl_a = ctk.CTkLabel(self.side, text="Nessun file", text_color="gray", font=("Arial", 11))
        self.lbl_a.pack()

        self._header("② MOTORE AI")
        self.mod_var = ctk.StringVar(value="base")
        ctk.CTkOptionMenu(self.side, variable=self.mod_var, values=["tiny", "base", "small"]).pack(pady=5)
        self.btn_s = ctk.CTkButton(self.side, text="Sincronizza Testo", command=self._start_sync)
        self.btn_s.pack(pady=10, padx=20)
        self.prog = ctk.CTkProgressBar(self.side); self.prog.pack(padx=20, pady=5); self.prog.set(0)

        self._header("③ STILE VIDEO")
        self.grad_var = ctk.StringVar(value="Viola Notturno")
        ctk.CTkOptionMenu(self.side, variable=self.grad_var, values=list(GRADIENTS.keys())).pack(pady=5)
        
        self.res_var = ctk.StringVar(value="1080p")
        self.res_map = {"1080p":(1920,1080),"720p":(1280,720),"480p":(854,480)}
        ctk.CTkOptionMenu(self.side, variable=self.res_var, values=list(self.res_map.keys())).pack(pady=5)

        self._header("④ BRANDING")
        ctk.CTkButton(self.side, text="Logo Pubblicitario", fg_color="#333", command=self._load_logo).pack(pady=5)
        self.qr_pos_var = ctk.StringVar(value="Basso DX")
        ctk.CTkOptionMenu(self.side, variable=self.qr_pos_var, values=list(QR_POS.keys())).pack(pady=5)

        self.btn_exp = ctk.CTkButton(self.side, text="ESPORTA MP4", fg_color="#22c55e", height=50, font=("Arial", 14, "bold"), command=self._export)
        self.btn_exp.pack(pady=40, padx=20)

        # Editor (Destra)
        self.edit_frame = ctk.CTkFrame(self, fg_color="#0d0d0f")
        self.edit_frame.grid(row=0, column=1, sticky="nsew", padx=15, pady=15)
        self.rows_box = ctk.CTkScrollableFrame(self.edit_frame, fg_color="#16161a", label_text="Editor Sincronizzazione Temporale")
        self.rows_box.pack(fill="both", expand=True, padx=10, pady=10)

    def _header(self, t): ctk.CTkLabel(self.side, text=t, font=("Arial", 12, "bold"), text_color="#a855f7").pack(pady=(20,5))

    def _load_audio(self):
        p = filedialog.askopenfilename()
        if p:
            self.audio_path = p
            self.lbl_a.configure(text=Path(p).name, text_color="#22c55e")
            try:
                # Usa FFPROBE per ottenere la durata precisa
                r = subprocess.run([FFPROBE, "-v", "quiet", "-show_format", "-print_format", "json", p], capture_output=True, text=True)
                self.audio_duration = float(json.loads(r.stdout)["format"]["duration"])
            except: self.audio_duration = 0.0

    def _load_logo(self): self.qr_path = filedialog.askopenfilename()

    def _start_sync(self):
        if not self.audio_path: return
        self.btn_s.configure(state="disabled")
        threading.Thread(target=self._worker_sync, daemon=True).start()

    def _worker_sync(self):
        try:
            # Carica il modello pre-scaricato nell'EXE
            model = whisper.load_model(self.mod_var.get(), download_root=WHISPER_MODEL_DIR)
            result = model.transcribe(self.audio_path, word_timestamps=True)
            self.lyrics_lines = result["segments"]
            self.after(0, self._draw_editor)
        except Exception as e: self.after(0, lambda: messagebox.showerror("Errore AI", str(e)))
        finally: self.after(0, lambda: self.btn_s.configure(state="normal"))

    def _draw_editor(self):
        for child in self.rows_box.winfo_children(): child.destroy()
        for i, line in enumerate(self.lyrics_lines):
            f = ctk.CTkFrame(self.rows_box, fg_color="#1e1e24")
            f.pack(fill="x", pady=3, padx=5)
            ctk.CTkLabel(f, text=f"[{self._fmt(line['start'])}]", width=80).pack(side="left", padx=10)
            e = ctk.CTkEntry(f, height=35); e.insert(0, line["text"].strip())
            e.pack(side="left", fill="x", expand=True, padx=5)
            e.bind("<FocusOut>", lambda ev, idx=i, entry=e: self._save_line(idx, entry.get()))

    def _save_line(self, idx, txt): self.lyrics_lines[idx]["text"] = txt

    def _export(self):
        if not self.lyrics_lines: return
        out = filedialog.asksaveasfilename(defaultextension=".mp4")
        if out:
            self.btn_exp.configure(state="disabled", text="ESPORTAZIONE...")
            threading.Thread(target=self._worker_export, args=(out,), daemon=True).start()

    def _worker_export(self, out_path):
        ass = self._gen_ass()
        w, h = self.res_map[self.res_var.get()]
        c1, c2 = GRADIENTS[self.grad_var.get()]
        geq = f"r='({c1[0]}+(({c2[0]}-{c1[0]})*Y/H))':g='({c1[1]}+(({c2[1]}-{c1[1]})*Y/H))':b='({c1[2]}+(({c2[2]}-{c1[2]})*Y/H))'"
        
        cmd = [FFMPEG, "-y", "-f", "lavfi", "-i", f"color=black:s={w}x{h}:d={self.audio_duration}", "-i", self.audio_path]
        f_str = f"geq={geq}[bg];"
        
        if self.qr_path:
            cmd.extend(["-i", self.qr_path])
            px, py = QR_POS[self.qr_pos_var.get()]
            px = px.replace("{s}", "240").replace("W", "main_w").replace("H", "main_h")
            py = py.replace("{s}", "240").replace("W", "main_w").replace("H", "main_h")
            f_str += f"[2:v]scale=240:240[logo];[bg][logo]overlay={px}:{py}[bgqr];[bgqr]"
        else: f_str += "[bg]"
        
        f_str += f"ass='{ass.replace(':', r'\:')}'[v]"
        cmd.extend(["-filter_complex", f_str, "-map", "[v]", "-map", "1:a", "-c:v", "libx264", "-shortest", out_path])

        try:
            subprocess.run(cmd, check=True, creationflags=0x08000000 if os.name == 'nt' else 0)
            self.after(0, lambda: messagebox.showinfo("Successo", "Video creato!"))
        except Exception as e: self.after(0, lambda: messagebox.showerror("Errore", str(e)))
        finally:
            if os.path.exists(ass): os.remove(ass)
            self.after(0, lambda: self.btn_exp.configure(state="normal", text="ESPORTA MP4"))

    def _gen_ass(self):
        w, h = self.res_map[self.res_var.get()]
        p = Path(os.getcwd()) / f"tmp_{uuid.uuid4().hex}.ass"
        with open(p, "w", encoding="utf-8") as f:
            f.write(f"[Script Info]\nPlayResX: {w}\nPlayResY: {h}\n\n[V4+ Styles]\n")
            f.write("Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Alignment, BorderStyle, Outline, Shadow, MarginV\n")
            f.write(f"Style: Default,Arial,55,&H00FFFFFF,&H0000FFFF,&H00000000,&H00000000,-1,2,1,2,0,90\n\n[Events]\n")
            f.write("Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n")
            for l in self.lyrics_lines:
                f.write(f"Dialogue: 0,{self._fmt(l['start'])},{self._fmt(l['end'])},Default,,0,0,0,,{l['text'].strip()}\n")
        return str(p)

    def _fmt(self, s):
        m, s = divmod(s, 60); h, m = divmod(m, 60)
        return f"{int(h)}:{int(m):02d}:{s:05.2f}"

if __name__ == "__main__": KaraokeApp().mainloop()
