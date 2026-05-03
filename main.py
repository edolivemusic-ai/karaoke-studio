import customtkinter as ctk
import tkinter as tk
from tkinter import filedialog, messagebox
import threading
import json
import os
import subprocess
import tempfile
from pathlib import Path
import whisper
import numpy as np

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

class KaraokeApp(ctk.CTk):
    def __init__(self):
        super().__init__()
        self.title("KaraokeAI Studio"); self.geometry("1280x820"); self.minsize(960,660)
        self.configure(fg_color=BG)
        self.audio_path=None; self.lyrics_lines=[]; self.audio_duration=0.0; self.whisper_model=None
        self.model_map={"tiny (veloce)":"tiny","base (consigliato)":"base","small (preciso)":"small","medium (lento)":"medium"}
        self._build_ui()

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
        frame=ctk.CTkFrame(parent,fg_color=CARD,corner_radius=14); frame.grid(row=0,column=0,sticky="nsew",padx=(0,8))
        # Step 1
        s1=self._section(frame,"① Carica la canzone")
        ctk.CTkLabel(s1,text="Carica il file audio completo (con voce).\nWhisper riconosce e sincronizza il testo cantato automaticamente.",
            text_color=MUTED,font=ctk.CTkFont(size=11),justify="left").pack(anchor="w",pady=(0,6))
        self.audio_label=ctk.CTkLabel(s1,text="Nessun file caricato",text_color=MUTED,font=ctk.CTkFont(size=12),wraplength=270); self.audio_label.pack(pady=(0,6))
        ctk.CTkButton(s1,text="📂  Scegli file audio",command=self._load_audio,fg_color=ACCENT,hover_color=ACCENT2,height=36,corner_radius=8).pack(fill="x")
        # Step 2
        s2=self._section(frame,"② Lingua del canto (opzionale)")
        ctk.CTkLabel(s2,text="Lascia 'Auto' per rilevamento automatico.",text_color=MUTED,font=ctk.CTkFont(size=11)).pack(anchor="w",pady=(0,6))
        self.lang_var=ctk.StringVar(value="Auto")
        ctk.CTkOptionMenu(s2,variable=self.lang_var,values=["Auto","Italiano","English","Español","Français","Deutsch","Português","日本語","한국어","中文","Русский","العربية"],
            fg_color=SURFACE,button_color=ACCENT,dropdown_fg_color=CARD,width=200).pack(anchor="w")
        # Step 3
        s3=self._section(frame,"③ Qualità trascrizione")
        ctk.CTkLabel(s3,text="Modello più grande = più preciso, più lento.",text_color=MUTED,font=ctk.CTkFont(size=11)).pack(anchor="w",pady=(0,6))
        self.model_var=ctk.StringVar(value="base (consigliato)")
        ctk.CTkOptionMenu(s3,variable=self.model_var,values=list(self.model_map.keys()),fg_color=SURFACE,button_color=ACCENT,dropdown_fg_color=CARD,width=200).pack(anchor="w")
        # Step 4
        s4=self._section(frame,"④ Trascrivi e Sincronizza")
        self.sync_btn=ctk.CTkButton(s4,text="🎙  Avvia Trascrizione AI",command=self._start_sync,
            fg_color=ACCENT,hover_color=ACCENT2,height=44,corner_radius=10,font=ctk.CTkFont(size=15,weight="bold")); self.sync_btn.pack(fill="x")
        self.progress=ctk.CTkProgressBar(s4,fg_color=SURFACE,progress_color=ACCENT); self.progress.pack(fill="x",pady=(10,0)); self.progress.set(0)
        self.status_lbl=ctk.CTkLabel(s4,text="",text_color=MUTED,font=ctk.CTkFont(size=11)); self.status_lbl.pack(anchor="w",pady=(4,0))
        # Step 5
        s5=self._section(frame,"⑤ Esporta Video MP4")
        r1=ctk.CTkFrame(s5,fg_color="transparent"); r1.pack(fill="x",pady=(0,6))
        ctk.CTkLabel(r1,text="Sfondo:",text_color=MUTED,width=64).pack(side="left")
        self.bg_var=ctk.StringVar(value="nero")
        ctk.CTkOptionMenu(r1,variable=self.bg_var,values=["nero","blu notte","viola scuro","rosso scuro","verde scuro"],
            fg_color=SURFACE,button_color=ACCENT,dropdown_fg_color=CARD,width=160).pack(side="left",padx=6)
        r2=ctk.CTkFrame(s5,fg_color="transparent"); r2.pack(fill="x",pady=(0,6))
        ctk.CTkLabel(r2,text="Font:",text_color=MUTED,width=64).pack(side="left")
        self.font_size=ctk.CTkSlider(r2,from_=32,to=96,number_of_steps=16,fg_color=SURFACE,progress_color=ACCENT); self.font_size.set(64); self.font_size.pack(side="left",fill="x",expand=True,padx=6)
        r3=ctk.CTkFrame(s5,fg_color="transparent"); r3.pack(fill="x",pady=(0,10))
        ctk.CTkLabel(r3,text="Colore:",text_color=MUTED,width=64).pack(side="left")
        self.txt_color_var=ctk.StringVar(value="bianco")
        ctk.CTkOptionMenu(r3,variable=self.txt_color_var,values=["bianco","giallo","ciano","rosa"],
            fg_color=SURFACE,button_color=ACCENT,dropdown_fg_color=CARD,width=160).pack(side="left",padx=6)
        self.export_btn=ctk.CTkButton(s5,text="⬇  Esporta MP4 1080p",command=self._export_video,
            fg_color=SUCCESS,hover_color="#16a34a",height=40,corner_radius=10,font=ctk.CTkFont(size=14,weight="bold")); self.export_btn.pack(fill="x")
        self.export_status=ctk.CTkLabel(s5,text="",text_color=MUTED,font=ctk.CTkFont(size=11)); self.export_status.pack(anchor="w",pady=(4,0))

    def _right_panel(self,parent):
        frame=ctk.CTkFrame(parent,fg_color=CARD,corner_radius=14); frame.grid(row=0,column=1,sticky="nsew",padx=(8,0))
        hdr=ctk.CTkFrame(frame,fg_color="transparent"); hdr.pack(fill="x",padx=16,pady=(14,4))
        ctk.CTkLabel(hdr,text="✏️  Editor Sincronizzazione",font=ctk.CTkFont(size=15,weight="bold"),text_color=TEXT).pack(side="left")
        ctk.CTkButton(hdr,text="🗑 Tutto",width=80,height=28,command=self._clear_rows,fg_color=SURFACE,hover_color=DANGER,corner_radius=6).pack(side="right",padx=6)
        ctk.CTkButton(hdr,text="+ Riga",width=80,height=28,command=self._add_row,fg_color=SURFACE,hover_color=ACCENT,corner_radius=6).pack(side="right")
        cols=ctk.CTkFrame(frame,fg_color=SURFACE,corner_radius=6); cols.pack(fill="x",padx=16,pady=(0,4))
        for txt,w in [("#",36),("Testo trascritto",0),("Inizio",88),("Fine",88),("",40)]:
            ctk.CTkLabel(cols,text=txt,text_color=MUTED,font=ctk.CTkFont(size=11),width=w or 1).pack(side="left",padx=6,pady=4)
        self.rows_frame=ctk.CTkScrollableFrame(frame,fg_color="transparent"); self.rows_frame.pack(fill="both",expand=True,padx=16,pady=(0,8))
        prev_hdr=ctk.CTkFrame(frame,fg_color=SURFACE,corner_radius=8,height=34); prev_hdr.pack(fill="x",padx=16,pady=(0,4)); prev_hdr.pack_propagate(False)
        ctk.CTkLabel(prev_hdr,text="🖥  Anteprima karaoke",font=ctk.CTkFont(size=12,weight="bold"),text_color=ACCENT2).pack(side="left",padx=12,pady=5)
        self.preview=tk.Canvas(frame,bg="#08080f",height=120,highlightthickness=1,highlightbackground=ACCENT)
        self.preview.pack(fill="x",padx=16,pady=(0,12)); self._draw_preview()

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
        ctk.CTkButton(row,text="✕",width=32,height=24,fg_color="transparent",hover_color=DANGER,text_color=MUTED,corner_radius=4,
            command=lambda idx=i: self._delete_row(idx)).pack(side="left",padx=4)

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

    def _load_audio(self):
        path=filedialog.askopenfilename(title="Scegli file audio",
            filetypes=[("Audio","*.mp3 *.wav *.flac *.aac *.ogg *.m4a *.wma"),("Tutti","*.*")])
        if not path: return
        self.audio_path=path; name=Path(path).name
        self.audio_label.configure(text=f"✅  {name}",text_color=SUCCESS)
        try:
            r=subprocess.run(["ffprobe","-v","quiet","-print_format","json","-show_format",path],capture_output=True,text=True)
            info=json.loads(r.stdout); self.audio_duration=float(info["format"]["duration"])
            self.audio_label.configure(text=f"✅  {name}  [{fmt_time(self.audio_duration)}]")
        except: self.audio_duration=0.0

    def _start_sync(self):
        if not self.audio_path:
            messagebox.showwarning("Attenzione","Prima carica un file audio!"); return
        self.sync_btn.configure(state="disabled",text="⏳  Elaborazione in corso...")
        self.progress.set(0); self.lyrics_lines=[]; self._render_rows()
        threading.Thread(target=self._sync_worker,daemon=True).start()

    def _sync_worker(self):
        try:
            model_name=self.model_map.get(self.model_var.get(),"base")
            self._set_status(f"Caricamento modello Whisper '{model_name}'...",0.05)
            if self.whisper_model is None or getattr(self.whisper_model,"_name","")!=model_name:
                self.whisper_model=whisper.load_model(model_name); self.whisper_model._name=model_name
            lang_map={"Auto":None,"Italiano":"it","English":"en","Español":"es","Français":"fr",
                "Deutsch":"de","Português":"pt","日本語":"ja","한국어":"ko","中文":"zh","Русский":"ru","العربية":"ar"}
            language=lang_map.get(self.lang_var.get(),None)
            self._set_status("Trascrizione audio in corso... (1-3 minuti)",0.15)
            import sys, io
            if sys.stdout is None: sys.stdout = io.StringIO()
            if sys.stderr is None: sys.stderr = io.StringIO()
            opts=dict(word_timestamps=True, verbose=None)
            if language: opts["language"]=language
            result=self.whisper_model.transcribe(self.audio_path,**opts)
            self._set_status("Costruzione versi...",0.85)
            lines=[]
            for seg in result.get("segments",[]):
                text=seg["text"].strip()
                if text: lines.append({"text":text,"start":round(seg["start"],2),"end":round(seg["end"],2)})
            if not lines:
                self.after(0,lambda: messagebox.showwarning("Nessun testo","Whisper non ha trovato parti vocali.\nProva un modello più grande.")); return
            self.lyrics_lines=lines; detected=result.get("language","?")
            self._set_status(f"✅ {len(lines)} versi  •  lingua: {detected}",1.0)
            self.after(0,self._render_rows)
            self.after(0,lambda: self.status_lbl.configure(text=f"✅ {len(lines)} versi trascritti  •  lingua: {detected}",text_color=SUCCESS))
        except Exception as ex:
            self.after(0,lambda: messagebox.showerror("Errore trascrizione",str(ex)))
            self.after(0,lambda: self.status_lbl.configure(text=f"❌ {ex}",text_color=DANGER))
        finally:
            self.after(0,lambda: self.sync_btn.configure(state="normal",text="🎙  Avvia Trascrizione AI"))

    def _set_status(self,msg,progress):
        self.after(0,lambda: self.status_lbl.configure(text=msg,text_color=MUTED))
        self.after(0,lambda: self.progress.set(progress))

    def _draw_preview(self):
        c=self.preview; c.delete("all")
        w=c.winfo_width() or 600; h=c.winfo_height() or 120
        for y in range(0,h,2):
            r=y/h; c.create_line(0,y,w,y,fill=f"#{int(8+r*8):02x}{int(8+r*4):02x}{int(15+r*12):02x}")
        if not self.lyrics_lines:
            c.create_text(w//2,h//2,text="Trascrivi la canzone per vedere l'anteprima",fill=MUTED,font=("Courier New",12)); return
        curr=self.lyrics_lines[0]["text"]; nxt=self.lyrics_lines[1]["text"] if len(self.lyrics_lines)>1 else ""
        c.create_rectangle(16,h//2-26,w-16,h//2+6,fill="#2d1060",outline="#7c3aed",width=1)
        c.create_text(w//2,h//2-10,text=curr.upper(),fill="#d8b4fe",font=("Courier New",16,"bold"),anchor="center")
        if nxt: c.create_text(w//2,h//2+28,text=nxt,fill=MUTED,font=("Courier New",11),anchor="center")
        by=h-12; c.create_rectangle(20,by-3,w-20,by+3,fill="#1e1e24",outline="")
        ex=int((w-40)*0.25)+20; c.create_rectangle(20,by-3,ex,by+3,fill=ACCENT,outline="")
        c.create_oval(ex-5,by-5,ex+5,by+5,fill=ACCENT2,outline="")

    def _export_video(self):
        if not self.audio_path:
            messagebox.showwarning("Attenzione","Carica prima un file audio!"); return
        if not self.lyrics_lines:
            messagebox.showwarning("Attenzione","Trascrivi prima la canzone!"); return
        out_path=filedialog.asksaveasfilename(title="Salva video karaoke",defaultextension=".mp4",filetypes=[("Video MP4","*.mp4")])
        if not out_path: return
        self.export_btn.configure(state="disabled",text="⏳  Esportazione...")
        self.export_status.configure(text="Generazione video...",text_color=MUTED)
        threading.Thread(target=self._export_worker,args=(out_path,self.bg_var.get(),int(self.font_size.get()),self.txt_color_var.get()),daemon=True).start()

    def _export_worker(self,out_path,bg_choice,font_size,txt_color):
        try:
            bg_map={"nero":"0x000000","blu notte":"0x050510","viola scuro":"0x110020","rosso scuro":"0x150000","verde scuro":"0x001508"}
            color_map={"bianco":"&H00FFFFFF","giallo":"&H0000FFFF","ciano":"&H00FFFF00","rosa":"&H00FF80FF"}
            bg_hex=bg_map.get(bg_choice,"0x000000"); ass_color=color_map.get(txt_color,"&H00FFFFFF")
            ass_path=self._build_ass(font_size,ass_color); dur=self.audio_duration or 300.0
            cmd=["ffmpeg","-y","-f","lavfi","-i",f"color=c={bg_hex}:s=1920x1080:r=30:d={dur}",
                "-i",self.audio_path,"-vf",f"ass={ass_path}",
                "-c:v","libx264","-preset","fast","-crf","22","-c:a","aac","-b:a","192k","-shortest",out_path]
            proc=subprocess.run(cmd,capture_output=True,text=True,timeout=900)
            os.unlink(ass_path)
            if proc.returncode==0:
                self.after(0,lambda: self.export_status.configure(text="✅ Video salvato!",text_color=SUCCESS))
                self.after(0,lambda: messagebox.showinfo("Esportazione completata",f"Video salvato in:\n{out_path}"))
            else: raise RuntimeError(proc.stderr[-600:])
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
    app=KaraokeApp(); app.mainloop()

if __name__=="__main__":
    main()
