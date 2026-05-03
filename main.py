import customtkinter as ctk
import tkinter as tk
from tkinter import filedialog, messagebox
import threading
import json
import os
import subprocess
import tempfile
import math
from pathlib import Path
import whisper
import numpy as np

import sys as _sys

def _get_bin(name):
    """Trova ffmpeg/ffprobe dentro l exe oppure nel sistema."""
    if getattr(_sys, "frozen", False):
        base = Path(_sys.executable).parent
    else:
        base = Path(__file__).parent
    local = base / name
    if local.exists():
        return str(local)
    return name  # fallback: cerca nel PATH di sistema

FFMPEG  = _get_bin("ffmpeg.exe")
FFPROBE = _get_bin("ffprobe.exe")

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
    try:
        parts = s.strip().replace(",",".").split(":")
        if len(parts)==2:
            m,rest=parts; sv,ms=rest.split(".") if "." in rest else (rest,"0")
            return int(m)*60+int(sv)+int(ms)/100
        return float(s)
    except: return 0.0

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
        self.model_map={"tiny ⚡ (1-2 min)":"tiny","base (3-5 min)":"base","small (8-12 min)":"small","medium (15+ min)":"medium"}
        self._build_ui()

    def _on_close(self):
        import sys
        self.destroy()
        sys.exit(0)

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
        frame=ctk.CTkScrollableFrame(outer,fg_color="transparent",scrollbar_button_color=ACCENT)
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
        self.model_var=ctk.StringVar(value="tiny (veloce)")
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
            r=subprocess.run([FFPROBE,"-v","quiet","-print_format","json","-show_format",path],capture_output=True,text=True)
            info=json.loads(r.stdout); self.audio_duration=float(info["format"]["duration"])
            self.audio_label.configure(text=f"✅  {name}  [{fmt_time(self.audio_duration)}]")
        except: self.audio_duration=0.0

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
        if hasattr(self,"_pulse_job"):
            self.after_cancel(self._pulse_job)
        self.progress.stop()
        self.progress.configure(mode="determinate")
        self.progress.set(1.0)

    def _sync_worker(self):
        try:
            model_name=self.model_map.get(self.model_var.get(),"base")
            if self.whisper_model is None or getattr(self.whisper_model,"_name","")!=model_name:
                self.whisper_model=whisper.load_model(model_name); self.whisper_model._name=model_name
            lang_map={"Auto":None,"Italiano":"it","English":"en","Español":"es","Français":"fr",
                "Deutsch":"de","Português":"pt","日本語":"ja","한국어":"ko","中文":"zh","Русский":"ru","العربية":"ar"}
            language=lang_map.get(self.lang_var.get(),None)
            import sys,io
            if sys.stdout is None: sys.stdout=io.StringIO()
            if sys.stderr is None: sys.stderr=io.StringIO()
            opts=dict(word_timestamps=True,verbose=None)
            if language: opts["language"]=language
            result=self.whisper_model.transcribe(self.audio_path,**opts)
            lines=[]
            for seg in result.get("segments",[]):
                text=seg["text"].strip()
                if text: lines.append({"text":text,"start":round(seg["start"],2),"end":round(seg["end"],2)})
            if not lines:
                self.after(0,self._stop_pulse)
                self.after(0,lambda: messagebox.showwarning("Nessun testo","Nessuna voce trovata. Prova un modello più grande.")); return
            self.lyrics_lines=lines; detected=result.get("language","?")
            self.after(0,self._stop_pulse)
            self.after(0,self._render_rows)
            self.after(0,lambda: self.status_lbl.configure(
                text=f"✅ {len(lines)} versi trascritti  •  lingua: {detected}",text_color=SUCCESS))
        except Exception as ex:
            self.after(0,self._stop_pulse)
            self.after(0,lambda: messagebox.showerror("Errore trascrizione",str(ex)))
        finally:
            self.after(0,lambda: self.sync_btn.configure(state="normal",text="🎙  Avvia Trascrizione AI"))

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
        params=(out_path, self.grad_var.get(), int(self.font_size.get()),
                self.txt_color_var.get(), self.qr_path,
                int(self.qr_size.get()), self.qr_pos_var.get())
        threading.Thread(target=self._export_worker,args=params,daemon=True).start()

    def _export_worker(self,out_path,grad_name,font_size,txt_color,qr_path,qr_size,qr_pos):
        try:
            dur=self.audio_duration or 300.0
            color_map={"bianco":"&H00FFFFFF","giallo":"&H0000FFFF","ciano":"&H00FFFF00","rosa":"&H00FF80FF"}
            ass_color=color_map.get(txt_color,"&H00FFFFFF")

            # Build gradient background video using ffmpeg lavfi
            stops=GRADIENTS.get(grad_name,[(80,0,160),(0,20,180)])
            r1,g1,b1=stops[0]; r2,g2,b2=stops[1]

            # Generate gradient frames via Python script → pipe to ffmpeg
            # Use ffmpeg geq filter for gradient
            # geq: r/g/b are functions of X,Y,W,H
            # color1 at top, color2 at bottom
            geq=(
                f"r='({r1}+(({r2}-{r1})*Y/H))':g='({g1}+(({g2}-{g1})*Y/H))':b='({b1}+(({b2}-{b1})*Y/H))'"
            )

            ass_path=self._build_ass(font_size,ass_color)

            # Build filter chain
            vf_parts=[f"geq={geq}"]
            vf_parts.append(f"ass={ass_path}")

            # Add QR overlay if present
            if qr_path and os.path.exists(qr_path):
                pos_info=QR_POS_MAP.get(qr_pos,QR_POS_MAP["Basso destra"])
                x_expr,y_expr,_=pos_info
                x_expr=x_expr.replace("{s}",str(qr_size)).replace("W","main_w").replace("H","main_h")
                y_expr=y_expr.replace("{s}",str(qr_size)).replace("W","main_w").replace("H","main_h")

                cmd=[
                    FFMPEG,"-y",
                    "-f","lavfi","-i",f"color=black:s=1920x1080:r=30:d={dur}",
                    "-i",self.audio_path,
                    "-i",qr_path,
                    "-filter_complex",
                    f"[0:v]geq={geq}[bg];"
                    f"[2:v]scale={qr_size}:{qr_size}[qr];"
                    f"[bg][qr]overlay={x_expr}:{y_expr}[bgqr];"
                    f"[bgqr]ass={ass_path}[v]",
                    "-map","[v]","-map","1:a",
                    "-c:v","libx264","-preset","fast","-crf","22",
                    "-c:a","aac","-b:a","192k","-shortest",out_path
                ]
            else:
                cmd=[
                    FFMPEG,"-y",
                    "-f","lavfi","-i",f"color=black:s=1920x1080:r=30:d={dur}",
                    "-i",self.audio_path,
                    "-filter_complex",
                    f"[0:v]geq={geq}[bg];[bg]ass={ass_path}[v]",
                    "-map","[v]","-map","1:a",
                    "-c:v","libx264","-preset","fast","-crf","22",
                    "-c:a","aac","-b:a","192k","-shortest",out_path
                ]

            proc=subprocess.run(cmd,capture_output=True,text=True,timeout=900)
            os.unlink(ass_path)
            if proc.returncode==0:
                self.after(0,lambda: self.export_status.configure(text="✅ Video salvato!",text_color=SUCCESS))
                self.after(0,lambda: messagebox.showinfo("Completato",f"Video salvato in:\n{out_path}"))
            else:
                raise RuntimeError(proc.stderr[-800:])
        except Exception as ex:
            self.after(0,lambda: messagebox.showerror("Errore esportazione",str(ex)))
            self.after(0,lambda: self.export_status.configure(text="❌ Errore",text_color=DANGER))
        finally:
            self.after(0,lambda: self.export_btn.configure(state="normal",text="⬇  Esporta MP4 1080p"))

    def _build_ass(self,font_size,primary_color):
        tmp=tempfile.NamedTemporaryFile(suffix=".ass",delete=False,mode="w",encoding="utf-8")
        tmp.write("[Script Info]\nScriptType: v4.00+\nPlayResX: 1920\nPlayResY: 1080\nCollisions: Normal\n\n")
        tmp.write("[V4+ Styles]\nFormat: Name,Fontname,Fontsize,PrimaryColour,SecondaryColour,OutlineColour,BackColour,Bold,Italic,Underline,StrikeOut,ScaleX,ScaleY,Spacing,Angle,BorderStyle,Outline,Shadow,Alignment,MarginL,MarginR,MarginV,Encoding\n")
        tmp.write(f"Style: Default,Arial,{font_size},{primary_color},&H00C084FC,&H00000000,&HA0000000,-1,0,0,0,100,100,2,0,1,4,2,2,80,80,90,1\n\n")
        tmp.write("[Events]\nFormat: Layer,Start,End,Style,Name,MarginL,MarginR,MarginV,Effect,Text\n")
        def at(sec):
            h=int(sec)//3600; m=(int(sec)%3600)//60; s=int(sec)%60; cs=int((sec-int(sec))*100)
            return f"{h}:{m:02d}:{s:02d}.{cs:02d}"
        for line in self.lyrics_lines:
            text=line["text"].replace("\n","\\N").replace("{","{{").replace("}","}}")
            tmp.write(f"Dialogue: 0,{at(line['start'])},{at(line['end'])},Default,,0,0,0,,{text}\n")
        tmp.close(); return tmp.name

def main():
    app=KaraokeApp()
    app.mainloop()
    import sys; sys.exit(0)

if __name__=="__main__":
    main()
