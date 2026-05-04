import sys as _sys, io as _io
# Fix critico PyInstaller --windowed: stdout/stderr sono None prima di qualsiasi import
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

def _get_base():
    """Cartella base: accanto all exe se frozen, altrimenti accanto al .py"""
    if getattr(_sys, "frozen", False):
        return Path(_sys.executable).parent
    return Path(__file__).parent

def _get_bin(name):
    """Restituisce il binario bundled o quello disponibile nel PATH.

    La versione originale cercava sempre `ffmpeg.exe` / `ffprobe.exe`; su macOS/Linux
    questo impedisce di usare correttamente i binari installati nel sistema.
    """
    base = _get_base()
    candidates = [base / name]

    if os.name == "nt" and not name.lower().endswith(".exe"):
        candidates.append(base / f"{name}.exe")
    elif os.name != "nt" and name.lower().endswith(".exe"):
        candidates.append(base / name[:-4])

    for local in candidates:
        if local.exists():
            return str(local)

    path_name = shutil.which(name)
    if path_name:
        return path_name

    if name.lower().endswith(".exe"):
        path_name = shutil.which(name[:-4])
        if path_name:
            return path_name
    elif os.name == "nt":
        path_name = shutil.which(f"{name}.exe")
        if path_name:
            return path_name

    return name

def _get_whisper_model_dir():
    """Usa modello bundled se esiste, altrimenti cache standard."""
    bundled = _get_base() / "whisper_models"
    if bundled.exists() and any(bundled.iterdir()):
        return str(bundled)
    return None  # whisper userà la cache di default

FFMPEG  = _get_bin("ffmpeg")
FFPROBE = _get_bin("ffprobe")
WHISPER_MODEL_DIR = _get_whisper_model_dir()

ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("blue")

BG      = "#0d0d0f"
SURFACE = "#16161a"
CARD    = "#1e1e24"
ACCENT  = "#7c3aed"
ACCENT2 = "#a855f7"
TEXT    = "#f0eeff"
MUTED   = "#6b6880"
SUCCESS = "#22c55e"
WARN    = "#f59e0b"
DANGER  = "#ef4444"

def fmt_time(sec):
    sec = max(0.0, sec)
    m = int(sec)//60; s = int(sec)%60; ms = int((sec-int(sec))*100)
    return f"{m:02d}:{s:02d}.{ms:02d}"

def parse_time(s):
    """Converte `MM:SS.cc`, `HH:MM:SS.cc` o secondi in float.

    Corregge un bug della versione originale: valori come `01:02.500` venivano
    interpretati come 67 secondi invece di 62,5 perché `500` era diviso per 100.
    """
    try:
        value = str(s).strip().replace(",", ".")
        if not value:
            return 0.0

        parts = value.split(":")
        if len(parts) == 1:
            return max(0.0, float(parts[0]))
        if len(parts) == 2:
            minutes, seconds = parts
            return max(0.0, int(minutes) * 60 + float(seconds))
        if len(parts) == 3:
            hours, minutes, seconds = parts
            return max(0.0, int(hours) * 3600 + int(minutes) * 60 + float(seconds))
    except (TypeError, ValueError):
        pass
    return 0.0


def _ffmpeg_filter_path(path):
    """Escapa un path per l'uso dentro i filtri FFmpeg/libass."""
    return Path(path).resolve().as_posix().replace("\\", "\\\\").replace(":", r"\:").replace("'", r"\'")


def _ass_filter(path):
    return f"ass=filename='{_ffmpeg_filter_path(path)}'"

# Gradient presets: list of (r,g,b) color stops
GRADIENTS = {
    "Viola → Blu":    [(80,0,160),(0,20,180)],
    "Rosso → Arancio":[(180,0,40),(200,80,0)],
    "Verde → Ciano":  [(0,120,40),(0,160,160)],
    "Blu → Viola":    [(0,20,180),(120,0,200)],
    "Nero → Viola":   [(5,5,10),(60,0,120)],
    "Tramonto":       [(120,0,80),(200,60,0)],
}

# QR positions
QR_POSITIONS = ["Basso destra","Basso sinistra","Alto destra","Alto sinistra","Centro destra","Centro sinistra"]
QR_POS_MAP = {
    "Basso destra":   ("W-{s}-20", "H-{s}-20", "BR"),
    "Basso sinistra": ("20",        "H-{s}-20", "BL"),
    "Alto destra":    ("W-{s}-20", "20",        "TR"),
    "Alto sinistra":  ("20",        "20",        "TL"),
    "Centro destra":  ("W-{s}-20", "(H-{s})/2", "CR"),
    "Centro sinistra":("20",        "(H-{s})/2", "CL"),
}

class KaraokeApp(ctk.CTk):
    def __init__(self):
        super().__init__()
        self.title("KaraokeAI Studio"); self.geometry("1280x860"); self.minsize(960,700)
        self.protocol("WM_DELETE_WINDOW", self._on_close)
        self.configure(fg_color=BG)
        self.audio_path=None; self.lyrics_lines=[]; self.audio_duration=0.0; self.whisper_model=None
        self.qr_path=None
        self._pulse_running=False; self._pulse_job=None
        self.model_map={"tiny ⚡ (1-2 min)":"tiny","base (3-5 min)":"base","small (8-12 min)":"small","medium (15+ min)":"medium"}
        self._build_ui()

    def _on_close(self):
        self._pulse_running = False
        try:
            self.destroy()
        except tk.TclError:
            pass
        os._exit(0)

    def _build_ui(self):
        hdr=ctk.CTkFrame(self,fg_color=SURFACE,corner_radius=0,height=58); hdr.pack(fill="x",side="top"); hdr.pack_propagate(False)
        ctk.CTkLabel(hdr,text="🎤  KaraokeAI Studio",font=ctk.CTkFont("Courier New",22,"bold"),text_color=ACCENT2).pack(side="left",padx=24)
        ctk.CTkLabel(hdr,text="trascrivi  •  sincronizza  •  esporta",font=ctk.CTkFont("Courier New",11),text_color=MUTED).pack(side="left",padx=4)
        body=ctk.CTkFrame(self,fg_color=BG); body.pack(fill="both",expand=True,padx=16,pady=12)
        body.columnconfigure(0,weight=1); body.columnconfigure(1,weight=2); body.rowconfigure(0,weight=1)
        self._left_panel(body); self._right_panel(body)

    def _section(self,parent,title):
        outer=ctk.CTkFrame(parent,fg_color="transparent"); outer.pack(fill="x",padx=14,pady=(14,0))
        ctk.CTkLabel(outer,text=title,font=ctk.CTkFont(size=13,weight="bold"),text_color=ACCENT2).pack(anchor="w",pady=(0,4))
        return outer

    def _left_panel(self,parent):
        outer=ctk.CTkFrame(parent,fg_color=CARD,corner_radius=14)
        outer.grid(row=0,column=0,sticky="nsew",padx=(0,8))
        # Aumentata la larghezza minima per garantire visibilità dei menu
        frame=ctk.CTkScrollableFrame(outer,fg_color="transparent",scrollbar_button_color=ACCENT,width=320)
        frame.pack(fill="both",expand=True,padx=0,pady=0)

        # ── Step 1: Audio ──
        s1=self._section(frame,"① Carica la canzone")
        ctk.CTkLabel(s1,text="Audio completo con voce. Whisper trascrive e sincronizza.",
            text_color=MUTED,font=ctk.CTkFont(size=11),justify="left").pack(anchor="w",pady=(0,6))
        self.audio_label=ctk.CTkLabel(s1,text="Nessun file caricato",text_color=MUTED,font=ctk.CTkFont(size=12),wraplength=270)
        self.audio_label.pack(pady=(0,6))
        ctk.CTkButton(s1,text="📂  Scegli file audio",command=self._load_audio,fg_color=ACCENT,hover_color=ACCENT2,height=36,corner_radius=8).pack(fill="x")

        # ── Step 2: Lingua ──
        s2=self._section(frame,"② Lingua (opzionale)")
        self.lang_var=ctk.StringVar(value="Auto")
        ctk.CTkOptionMenu(s2,variable=self.lang_var,
            values=["Auto","Italiano","English","Español","Français","Deutsch","Português","日本語","한국어","中文","Русский","العربية"],
            fg_color=SURFACE,button_color=ACCENT,dropdown_fg_color=CARD,width=200).pack(anchor="w")

        # ── Step 3: Modello ──
        s3=self._section(frame,"③ Qualità trascrizione")
        self.model_var=ctk.StringVar(value="tiny ⚡ (1-2 min)")
        ctk.CTkOptionMenu(s3,variable=self.model_var,values=list(self.model_map.keys()),
            fg_color=SURFACE,button_color=ACCENT,dropdown_fg_color=CARD,width=200).pack(anchor="w")

        # ── Step 4: Trascrivi ──
        s4=self._section(frame,"④ Trascrivi e Sincronizza")
        self.sync_btn=ctk.CTkButton(s4,text="🎙  Avvia Trascrizione AI",command=self._start_sync,
            fg_color=ACCENT,hover_color=ACCENT2,height=44,corner_radius=10,font=ctk.CTkFont(size=15,weight="bold"))
        self.sync_btn.pack(fill="x")
        self.progress=ctk.CTkProgressBar(s4,fg_color=SURFACE,progress_color=ACCENT)
        self.progress.pack(fill="x",pady=(10,0)); self.progress.set(0)
        self.status_lbl=ctk.CTkLabel(s4,text="",text_color=MUTED,font=ctk.CTkFont(size=11))
        self.status_lbl.pack(anchor="w",pady=(4,0))

        # ── Step 5: Export ──
        s5=self._section(frame,"⑤ Esporta Video MP4")

        # Gradiente
        rg=ctk.CTkFrame(s5,fg_color="transparent"); rg.pack(fill="x",pady=(0,4))
        ctk.CTkLabel(rg,text="Gradiente:",text_color=MUTED,width=80).pack(side="left")
        self.grad_var=ctk.StringVar(value="Viola → Blu")
        ctk.CTkOptionMenu(rg,variable=self.grad_var,values=list(GRADIENTS.keys()),
            fg_color=SURFACE,button_color=ACCENT,dropdown_fg_color=CARD,width=170).pack(side="left",padx=6)

        # Font size
        rf=ctk.CTkFrame(s5,fg_color="transparent"); rf.pack(fill="x",pady=(0,4))
        ctk.CTkLabel(rf,text="Font:",text_color=MUTED,width=80).pack(side="left")
        self.font_size=ctk.CTkSlider(rf,from_=32,to=96,number_of_steps=16,fg_color=SURFACE,progress_color=ACCENT)
        self.font_size.set(64); self.font_size.pack(side="left",fill="x",expand=True,padx=6)

        # Colore testo
        rc=ctk.CTkFrame(s5,fg_color="transparent"); rc.pack(fill="x",pady=(0,4))
        ctk.CTkLabel(rc,text="Colore:",text_color=MUTED,width=80).pack(side="left")
        self.txt_color_var=ctk.StringVar(value="bianco")
        ctk.CTkOptionMenu(rc,variable=self.txt_color_var,values=["bianco","giallo","ciano","rosa"],
            fg_color=SURFACE,button_color=ACCENT,dropdown_fg_color=CARD,width=170).pack(side="left",padx=6)

        # Risoluzione
        rr=ctk.CTkFrame(s5,fg_color="transparent"); rr.pack(fill="x",pady=(0,4))
        ctk.CTkLabel(rr,text="Qualità:",text_color=MUTED,width=80).pack(side="left")
        self.res_var=ctk.StringVar(value="1080p")
        self.res_map={"1080p":(1920,1080),"720p":(1280,720),"480p":(854,480),"320p":(480,320)}
        # Aggiunto scroll automatico al cambio risoluzione per mostrare il pulsante export
        def _on_res_change(val):
            self.export_btn.configure(text=f"⬇  Esporta MP4 {val}")
            try: frame._canvas.yview_moveto(1.0)
            except: pass

        ctk.CTkOptionMenu(rr,variable=self.res_var,values=list(self.res_map.keys()),
            fg_color=SURFACE,button_color=ACCENT,dropdown_fg_color=CARD,width=170,
            command=_on_res_change).pack(side="left",padx=6)

        # QR code
        sq=self._section(frame,"🖼  Logo / Immagine pub (opzionale)")
        self.qr_label=ctk.CTkLabel(sq,text="Nessuna immagine caricata",text_color=MUTED,font=ctk.CTkFont(size=11),wraplength=260)
        self.qr_label.pack(anchor="w",pady=(0,4))
        ctk.CTkButton(sq,text="📂  Carica immagine (JPG/PNG)",command=self._load_qr,
            fg_color=SURFACE,hover_color=ACCENT,height=30,corner_radius=8).pack(fill="x",pady=(0,6))

        rqp=ctk.CTkFrame(sq,fg_color="transparent"); rqp.pack(fill="x",pady=(0,4))
        ctk.CTkLabel(rqp,text="Posizione:",text_color=MUTED,width=80).pack(side="left")
        self.qr_pos_var=ctk.StringVar(value="Basso destra")
        ctk.CTkOptionMenu(rqp,variable=self.qr_pos_var,values=QR_POSITIONS,
            fg_color=SURFACE,button_color=ACCENT,dropdown_fg_color=CARD,width=170).pack(side="left",padx=6)

        rqs=ctk.CTkFrame(sq,fg_color="transparent"); rqs.pack(fill="x",pady=(0,8))
        ctk.CTkLabel(rqs,text="Dimensione:",text_color=MUTED,width=80).pack(side="left")
        self.qr_size=ctk.CTkSlider(rqs,from_=80,to=400,number_of_steps=32,fg_color=SURFACE,progress_color=ACCENT)
        self.qr_size.set(160); self.qr_size.pack(side="left",fill="x",expand=True,padx=6)
        self.qr_size_lbl=ctk.CTkLabel(rqs,text="160px",text_color=MUTED,width=48,font=ctk.CTkFont(size=11))
        self.qr_size_lbl.pack(side="left")
        self.qr_size.configure(command=lambda v: self.qr_size_lbl.configure(text=f"{int(v)}px"))

        self.export_btn=ctk.CTkButton(sq,text="⬇  Esporta MP4 1080p",command=self._export_video,
            fg_color=SUCCESS,hover_color="#16a34a",height=40,corner_radius=10,font=ctk.CTkFont(size=14,weight="bold"))
        self.export_btn.pack(fill="x")
        self.export_status=ctk.CTkLabel(sq,text="",text_color=MUTED,font=ctk.CTkFont(size=11))
        self.export_status.pack(anchor="w",pady=(4,0))

    def _right_panel(self,parent):
        frame=ctk.CTkFrame(parent,fg_color=CARD,corner_radius=14)
        frame.grid(row=0,column=1,sticky="nsew",padx=(8,0))
        hdr=ctk.CTkFrame(frame,fg_color="transparent"); hdr.pack(fill="x",padx=16,pady=(14,4))
        ctk.CTkLabel(hdr,text="✏️  Editor Sincronizzazione",font=ctk.CTkFont(size=15,weight="bold"),text_color=TEXT).pack(side="left")
        ctk.CTkButton(hdr,text="🗑 Tutto",width=80,height=28,command=self._clear_rows,fg_color=SURFACE,hover_color=DANGER,corner_radius=6).pack(side="right",padx=6)
        ctk.CTkButton(hdr,text="+ Riga",width=80,height=28,command=self._add_row,fg_color=SURFACE,hover_color=ACCENT,corner_radius=6).pack(side="right")
        cols=ctk.CTkFrame(frame,fg_color=SURFACE,corner_radius=6); cols.pack(fill="x",padx=16,pady=(0,4))
        for txt,w in [("#",36),("Testo trascritto",0),("Inizio",88),("Fine",88),("",40)]:
            ctk.CTkLabel(cols,text=txt,text_color=MUTED,font=ctk.CTkFont(size=11),width=w or 1).pack(side="left",padx=6,pady=4)
        self.rows_frame=ctk.CTkScrollableFrame(frame,fg_color="transparent")
        self.rows_frame.pack(fill="both",expand=True,padx=16,pady=(0,8))
        prev_hdr=ctk.CTkFrame(frame,fg_color=SURFACE,corner_radius=8,height=34)
        prev_hdr.pack(fill="x",padx=16,pady=(0,4)); prev_hdr.pack_propagate(False)
        ctk.CTkLabel(prev_hdr,text="🖥  Anteprima",font=ctk.CTkFont(size=12,weight="bold"),text_color=ACCENT2).pack(side="left",padx=12,pady=5)
        self.preview=tk.Canvas(frame,bg="#08080f",height=130,highlightthickness=1,highlightbackground=ACCENT)
        self.preview.pack(fill="x",padx=16,pady=(0,12))
        self._draw_preview()

    # ── Row management ────────────────────────────────────────────────────
    def _render_rows(self):
        for w in self.rows_frame.winfo_children(): w.destroy()
        for i,line in enumerate(self.lyrics_lines): self._make_row(i,line)
        self._draw_preview()

    def _make_row(self,i,line):
        bg=SURFACE if i%2==0 else "#18181f"
        row=ctk.CTkFrame(self.rows_frame,fg_color=bg,corner_radius=6); row.pack(fill="x",pady=2)
        ctk.CTkLabel(row,text=str(i+1),width=32,text_color=MUTED,font=ctk.CTkFont(size=11)).pack(side="left",padx=4)
        txt_e=ctk.CTkEntry(row,font=ctk.CTkFont("Courier New",12),fg_color="transparent",text_color=TEXT,border_width=0)
        txt_e.insert(0,line["text"]); txt_e.pack(side="left",fill="x",expand=True,padx=4)
        txt_e.bind("<FocusOut>",lambda e,idx=i,en=txt_e: self._update_text(idx,en.get()))
        se=ctk.CTkEntry(row,width=84,font=ctk.CTkFont("Courier New",11),fg_color="#0d0d0f",text_color=SUCCESS,border_color=SURFACE)
        se.insert(0,fmt_time(line["start"])); se.pack(side="left",padx=4)
        se.bind("<FocusOut>",lambda e,idx=i,en=se: self._update_time(idx,"start",en.get()))
        ee=ctk.CTkEntry(row,width=84,font=ctk.CTkFont("Courier New",11),fg_color="#0d0d0f",text_color=WARN,border_color=SURFACE)
        ee.insert(0,fmt_time(line["end"])); ee.pack(side="left",padx=4)
        ee.bind("<FocusOut>",lambda e,idx=i,en=ee: self._update_time(idx,"end",en.get()))
        ctk.CTkButton(row,text="✕",width=32,height=24,fg_color="transparent",hover_color=DANGER,
            text_color=MUTED,corner_radius=4,command=lambda idx=i: self._delete_row(idx)).pack(side="left",padx=4)

    def _update_text(self,idx,val):
        if 0<=idx<len(self.lyrics_lines): self.lyrics_lines[idx]["text"]=val
    def _update_time(self,idx,key,val):
        if 0<=idx<len(self.lyrics_lines): self.lyrics_lines[idx][key]=parse_time(val)
    def _delete_row(self,idx):
        if 0<=idx<len(self.lyrics_lines): self.lyrics_lines.pop(idx); self._render_rows()
    def _add_row(self):
        last=self.lyrics_lines[-1]["end"] if self.lyrics_lines else 0.0
        self.lyrics_lines.append({"text":"Nuovo verso","start":last,"end":last+3.0}); self._render_rows()
    def _clear_rows(self):
        if messagebox.askyesno("Conferma","Eliminare tutti i versi?"):
            self.lyrics_lines=[]; self._render_rows()

    # ── Load files ────────────────────────────────────────────────────────
    def _load_audio(self):
        path=filedialog.askopenfilename(title="Scegli file audio",
            filetypes=[("Audio","*.mp3 *.wav *.flac *.aac *.ogg *.m4a *.wma"),("Tutti","*.*")])
        if not path: return
        self.audio_path=path; name=Path(path).name
        self.audio_label.configure(text=f"✅  {name}",text_color=SUCCESS)
        try:
            r=subprocess.run([FFPROBE,"-v","quiet","-print_format","json","-show_format",path],timeout=10,capture_output=True,text=True)
            if r.returncode != 0 or not r.stdout.strip():
                raise RuntimeError(r.stderr.strip() or "ffprobe non ha restituito dati")
            info=json.loads(r.stdout); self.audio_duration=float(info["format"]["duration"])
            self.audio_label.configure(text=f"✅  {name}  [{fmt_time(self.audio_duration)}]")
        except Exception:
            self.audio_duration=0.0

    def _load_qr(self):
        path=filedialog.askopenfilename(title="Scegli immagine pubblicitaria",
            filetypes=[("Immagini","*.jpg *.jpeg *.png"),("Tutti","*.*")])
        if not path: return
        self.qr_path=path
        self.qr_label.configure(text=f"✅  {Path(path).name}",text_color=SUCCESS)

    # ── Whisper ───────────────────────────────────────────────────────────
    def _start_sync(self):
        if not self.audio_path:
            messagebox.showwarning("Attenzione","Prima carica un file audio!"); return
        self.sync_btn.configure(state="disabled",text="⏳  Elaborazione in corso...")
        self.progress.configure(mode="indeterminate")
        self.progress.start()
        self.lyrics_lines=[]; self._render_rows()
        self._pulse_msgs=["Caricamento modello AI...","Analisi audio in corso...","Riconoscimento vocale...","Allineamento testo...","Quasi pronto..."]
        self._pulse_idx=0
        self._pulse_running=True
        self._pulse_tick()
        threading.Thread(target=self._sync_worker,daemon=True).start()

    def _pulse_tick(self):
        if not self._pulse_running: return
        model=self.model_var.get()
        dur=self.audio_duration or 0
        # Stima tempo in minuti
        speed={"tiny ⚡ (1-2 min)":32,"base (3-5 min)":16,"small (8-12 min)":8,"medium (15+ min)":4}
        rtf=speed.get(model,16)
        est=int(dur/rtf/60)+1 if dur>0 else "?"
        msgs=[
            f"🎙 Analisi audio... (stima: ~{est} min)",
            "🔍 Riconoscimento vocale in corso...",
            "📝 Trascrizione testo...",
            "⏱ Allineamento tempi...",
            f"🔄 Elaborazione... (~{est} min totali)",
        ]
        self.status_lbl.configure(text=msgs[self._pulse_idx % len(msgs)],text_color=MUTED)
        self._pulse_idx+=1
        self._pulse_job=self.after(2500,self._pulse_tick)

    def _stop_pulse(self):
        self._pulse_running=False
        if getattr(self,"_pulse_job",None):
            try:
                self.after_cancel(self._pulse_job)
            except tk.TclError:
                pass
            self._pulse_job=None
        self.progress.stop()
        self.progress.configure(mode="determinate")
        self.progress.set(1.0)

    def _sync_worker(self):
        try:
            model_name=self.model_map.get(self.model_var.get(),"base")
            if self.whisper_model is None or getattr(self.whisper_model,"_name","")!=model_name:
                self.whisper_model=whisper.load_model(model_name, download_root=WHISPER_MODEL_DIR); self.whisper_model._name=model_name
            lang_map={"Auto":None,"Italiano":"it","English":"en","Español":"es","Français":"fr",
                "Deutsch":"de","Português":"pt","日本語":"ja","한국어":"ko","中文":"zh","Русский":"ru","العربية":"ar"}
            language=lang_map.get(self.lang_var.get(),None)
            opts=dict(word_timestamps=True,verbose=False)
            if language: opts["language"]=language
            result=self.whisper_model.transcribe(self.audio_path,**opts)
            lines=[]
            for seg in result.get("segments",[]):
                text=seg["text"].strip()
                if text: lines.append({"text":text,"start":round(seg["start"],2),"end":round(seg["end"],2)})
            if not lines:
                self.after(0,self._stop_pulse)
                self.after(0,lambda: messagebox.showwarning("Nessun testo","Nessuna voce trovata. Prova un modello più grande.")); return
            detected=result.get("language","?")
            self.after(0,lambda l=lines,d=detected: self._finish_sync(l,d))
        except Exception as ex:
            err=str(ex)
            self.after(0,self._stop_pulse)
            self.after(0,lambda e=err: messagebox.showerror("Errore trascrizione",e))
        finally:
            self.after(0,lambda: self.sync_btn.configure(state="normal",text="🎙  Avvia Trascrizione AI"))

    def _finish_sync(self,lines,detected):
        self.lyrics_lines=lines
        self._stop_pulse()
        self._render_rows()
        self.status_lbl.configure(text=f"✅ {len(lines)} versi trascritti  •  lingua: {detected}",text_color=SUCCESS)

    def _set_status(self,msg,progress):
        self.after(0,lambda: self.status_lbl.configure(text=msg,text_color=MUTED))
        self.after(0,lambda: self.progress.set(progress))

    # ── Preview ───────────────────────────────────────────────────────────
    def _draw_preview(self):
        c=self.preview; c.delete("all")
        w=c.winfo_width() or 600; h=c.winfo_height() or 130
        # Gradient preview
        stops=GRADIENTS.get(self.grad_var.get() if hasattr(self,"grad_var") else "Viola → Blu",[(80,0,160),(0,20,180)])
        r1,g1,b1=stops[0]; r2,g2,b2=stops[1]
        for y in range(0,h,2):
            t=y/h
            r=int(r1+(r2-r1)*t); g=int(g1+(g2-g1)*t); b=int(b1+(b2-b1)*t)
            c.create_line(0,y,w,y,fill=f"#{r:02x}{g:02x}{b:02x}")
        if not self.lyrics_lines:
            c.create_text(w//2,h//2,text="Trascrivi per vedere l'anteprima",fill="white",font=("Courier New",11)); return
        curr=self.lyrics_lines[0]["text"]
        nxt=self.lyrics_lines[1]["text"] if len(self.lyrics_lines)>1 else ""
        c.create_rectangle(10,h//2-28,w-10,h//2+8,fill="#00000060",outline="")
        c.create_text(w//2,h//2-10,text=curr.upper(),fill="white",font=("Courier New",15,"bold"),anchor="center")
        if nxt: c.create_text(w//2,h//2+26,text=nxt,fill="#cccccc",font=("Courier New",10),anchor="center")

    # ── Export ────────────────────────────────────────────────────────────
    def _export_video(self):
        if not self.audio_path:
            messagebox.showwarning("Attenzione","Carica prima un file audio!"); return
        if not self.lyrics_lines:
            messagebox.showwarning("Attenzione","Trascrivi prima la canzone!"); return
        out_path=filedialog.asksaveasfilename(title="Salva video karaoke",defaultextension=".mp4",filetypes=[("Video MP4","*.mp4")])
        if not out_path: return
        self.export_btn.configure(state="disabled",text="⏳  Esportazione...")
        self.export_status.configure(text="Generazione video...",text_color=MUTED)
        
        res_name = self.res_var.get()
        width, height = self.res_map.get(res_name, (1920, 1080))
        
        params=(out_path, self.grad_var.get(), int(self.font_size.get()),
                self.txt_color_var.get(), self.qr_path,
                int(self.qr_size.get()), self.qr_pos_var.get(), width, height)
        threading.Thread(target=self._export_worker,args=params,daemon=True).start()

    def _export_worker(self,out_path,grad_name,font_size,txt_color,qr_path,qr_size,qr_pos,width,height):
        try:
            dur=self.audio_duration or 300.0
            color_map={"bianco":"&H00FFFFFF","giallo":"&H0000FFFF","ciano":"&H00FFFF00","rosa":"&H00FF80FF"}
            ass_color=color_map.get(txt_color,"&H00FFFFFF")
            
            # Adatta la dimensione del font alla risoluzione (base 1080p)
            scale_factor = height / 1080.0
            scaled_font_size = int(font_size * scale_factor)
            scaled_qr_size = int(qr_size * scale_factor)

            # Configurazione per evitare finestre di console su Windows
            creationflags = 0
            if os.name == 'nt':
                # CREATE_NO_WINDOW = 0x08000000
                creationflags = 0x08000000

            # Metodo veloce per il gradiente: crea due colori e usa lo scale con interpolazione
            stops=GRADIENTS.get(grad_name,[(80,0,160),(0,20,180)])
            c1 = f"0x{stops[0][0]:02x}{stops[0][1]:02x}{stops[0][2]:02x}"
            c2 = f"0x{stops[1][0]:02x}{stops[1][1]:02x}{stops[1][2]:02x}"
            
            # Creiamo un'immagine 1x2 e la scaliamo alla risoluzione finale per un gradiente perfetto e istantaneo
            fast_grad = f"color={c1}:s=1x1[top];color={c2}:s=1x1[bot];[top][bot]vstack,scale={width}:{height}:flags=bilinear"

            ass_path=self._build_ass(font_size,ass_color,width,height)
            ass_filter=_ass_filter(ass_path)

            # Add QR overlay if present
            if qr_path and os.path.exists(qr_path):
                pos_info=QR_POS_MAP.get(qr_pos,QR_POS_MAP["Basso destra"])
                x_expr,y_expr,_=pos_info
                x_expr=x_expr.replace("{s}",str(qr_size)).replace("W","main_w").replace("H","main_h")
                y_expr=y_expr.replace("{s}",str(qr_size)).replace("W","main_w").replace("H","main_h")

                cmd=[
                    FFMPEG,"-y",
                    "-f","lavfi","-i",f"anullsrc=r=44100:cl=stereo", # Input dummy per sicurezza
                    "-i",self.audio_path,
                    "-i",qr_path,
                    "-filter_complex",
                    f"{fast_grad}[bg];"
                    f"[2:v]scale={scaled_qr_size}:{scaled_qr_size}[qr];"
                    f"[bg][qr]overlay={x_expr.replace(str(qr_size), str(scaled_qr_size))}:{y_expr.replace(str(qr_size), str(scaled_qr_size))}[bgqr];"
                    f"[bgqr]{ass_filter},setsar=1[v]",
                    "-map","[v]","-map","1:a",
                    "-t",str(dur),
                    "-c:v","libx264","-preset","ultrafast","-crf","23",
                    "-c:a","aac","-b:a","192k",out_path
                ]
            else:
                cmd=[
                    FFMPEG,"-y",
                    "-f","lavfi","-i",f"anullsrc=r=44100:cl=stereo",
                    "-i",self.audio_path,
                    "-filter_complex",
                    f"{fast_grad}[bg];[bg]{ass_filter},setsar=1[v]",
                    "-map","[v]","-map","1:a",
                    "-t",str(dur),
                    "-c:v","libx264","-preset","ultrafast","-crf","23",
                    "-c:a","aac","-b:a","192k",out_path
                ]

            proc=subprocess.run(cmd,capture_output=True,text=True,timeout=1800,creationflags=creationflags)
            try:
                os.unlink(ass_path)
            except OSError:
                pass
            if proc.returncode==0:
                self.after(0,lambda: self.export_status.configure(text="✅ Video salvato!",text_color=SUCCESS))
                self.after(0,lambda: messagebox.showinfo("Completato",f"Video salvato in:\n{out_path}"))
            else:
                raise RuntimeError(proc.stderr[-800:])
        except Exception as ex:
            err=str(ex)
            self.after(0,lambda e=err: messagebox.showerror("Errore esportazione",e))
            self.after(0,lambda: self.export_status.configure(text="❌ Errore",text_color=DANGER))
        finally:
            self.after(0,lambda: self.export_btn.configure(state="normal",text=f"⬇  Esporta MP4 {self.res_var.get()}"))

    def _build_ass(self,font_size,primary_color,width,height):
        # Salva in cartella senza spazi per compatibilità FFmpeg
        import uuid
        safe_dir = Path(os.environ.get("TEMP") or os.environ.get("TMP") or os.environ.get("TMPDIR") or _get_base())
        safe_dir.mkdir(parents=True, exist_ok=True)
        safe_path = safe_dir / f"karaoke_{uuid.uuid4().hex[:8]}.ass"
        tmp=open(safe_path,"w",encoding="utf-8")
        tmp.write(f"[Script Info]\nScriptType: v4.00+\nPlayResX: {width}\nPlayResY: {height}\nCollisions: Normal\n\n")
        tmp.write("[V4+ Styles]\nFormat: Name,Fontname,Fontsize,PrimaryColour,SecondaryColour,OutlineColour,BackColour,Bold,Italic,Underline,StrikeOut,ScaleX,ScaleY,Spacing,Angle,BorderStyle,Outline,Shadow,Alignment,MarginL,MarginR,MarginV,Encoding\n")
        tmp.write(f"Style: Default,Arial,{font_size},{primary_color},&H00C084FC,&H00000000,&HA0000000,-1,0,0,0,100,100,2,0,1,4,2,2,80,80,90,1\n\n")
        tmp.write("[Events]\nFormat: Layer,Start,End,Style,Name,MarginL,MarginR,MarginV,Effect,Text\n")
        def at(sec):
            h=int(sec)//3600; m=(int(sec)%3600)//60; s=int(sec)%60; cs=int((sec-int(sec))*100)
            return f"{h}:{m:02d}:{s:02d}.{cs:02d}"
        for line in self.lyrics_lines:
            text=(line["text"].replace("\\", r"\\")
                               .replace("\n","\\N")
                               .replace("{", r"\{")
                               .replace("}", r"\}"))
            tmp.write(f"Dialogue: 0,{at(line['start'])},{at(line['end'])},Default,,0,0,0,,{text}\n")
        tmp.close(); return str(safe_path)

def main():
    app=KaraokeApp()
    app.mainloop()
    os._exit(0)

if __name__=="__main__":
    main()
