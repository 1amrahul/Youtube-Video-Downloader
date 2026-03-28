import os
import sys
import threading
import queue
import time
import tkinter as tk
from tkinter import filedialog
import datetime

try:
    import customtkinter as ctk
except ImportError:
    print("❌  customtkinter not installed.\n    Run: pip install customtkinter")
    sys.exit(1)

try:
    import yt_dlp
except ImportError:
    print("❌  yt-dlp not installed")
    sys.exit(1)
ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("blue")

C = {
    "bg":        "#080C10",
    "surface":   "#0E1419",
    "card":      "#111820",
    "border":    "#1E2D3D",
    "border2":   "#243447",
    "accent":    "#00D4FF",
    "accent2":   "#0095FF",
    "accent3":   "#00FF9F",
    "red":       "#FF4060",
    "orange":    "#FF8C42",
    "yellow":    "#FFD166",
    "text":      "#E8F4FD",
    "text2":     "#7A9AB8",
    "text3":     "#3D5A73",
    "success":   "#00FF9F",
    "warning":   "#FFD166",
    "error":     "#FF4060",
}

LOG_Q: queue.Queue = queue.Queue()


def qlog(msg: str, kind: str = "info") -> None:
    ts = datetime.datetime.now().strftime("%H:%M:%S")
    LOG_Q.put((f"[{ts}]  {msg}", kind))


# ══════════════════════════════════════════════════
#  PROGRESS HOOK
# ══════════════════════════════════════════════════
def make_hook(prog_cb, status_cb, speed_cb, eta_cb, file_cb):
    def hook(d):
        s = d.get("status")
        if s == "downloading":
            raw_pct = d.get("_percent_str", "0%").strip()
            speed   = d.get("_speed_str",   "—").strip()
            eta     = d.get("_eta_str",     "—").strip()
            fname   = os.path.basename(d.get("filename", ""))
            try:
                pct = float(raw_pct.replace("%", ""))
            except Exception:
                pct = 0.0
            prog_cb(pct)
            status_cb(raw_pct)
            speed_cb(speed)
            eta_cb(eta)
            file_cb(fname)
            qlog(f"  {raw_pct:>7}  {speed:>12}  ETA {eta:>6}  ·  {fname}", "dl")
        elif s == "finished":
            fname = os.path.basename(d.get("filename", ""))
            prog_cb(100.0)
            status_cb("100%")
            file_cb(fname)
            qlog(f"✔  Finished: {fname}", "success")
        elif s == "error":
            qlog(f"✖  Error on: {d.get('filename','?')}", "error")
            status_cb("Error")
    return hook


# ══════════════════════════════════════════════════
#  BUILD YT-DLP OPTIONS
# ══════════════════════════════════════════════════
def build_opts(cfg: dict, hook) -> dict:
    out     = cfg["output_dir"]
    audio   = cfg["audio_only"]
    nomerge = cfg["no_merge"]
    subs    = cfg["subtitles"]
    pl      = cfg["playlist"]
    chan    = cfg["channel_all"]
    rate    = cfg["rate_limit"] or None
    cookies = cfg["cookies"]    or None
    proxy   = cfg["proxy"]      or None

    if audio:
        fmt = "bestaudio/best"
        pp  = [{"key": "FFmpegExtractAudio",
                "preferredcodec": "mp3", "preferredquality": "320"}]
    elif nomerge:
        fmt = "bestvideo*+bestaudio/best"
        pp  = []
    else:
        fmt = ("bestvideo[height<=2160][ext=mp4]+bestaudio[ext=m4a]/"
               "bestvideo[height<=2160]+bestaudio/"
               "bestvideo+bestaudio/best")
        pp  = [{"key": "FFmpegVideoConvertor", "preferedformat": "mp4"}]

    if chan:
        tmpl = os.path.join(out, "%(uploader)s", "%(title)s [%(id)s].%(ext)s")
    else:
        tmpl = os.path.join(out, "%(title)s [%(id)s].%(ext)s")

    opts = {
        "format":              fmt,
        "outtmpl":             tmpl,
        "progress_hooks":      [hook],
        "postprocessors":      pp,
        "merge_output_format": "mp4",
        "noplaylist":          not (pl or chan),
        "writesubtitles":      subs,
        "subtitleslangs":      ["en"] if subs else [],
        "ignoreerrors":        True,
        "retries":             5,
        "fragment_retries":    10,
        "continuedl":          True,
    }
    if cookies: opts["cookiefile"] = cookies
    if rate:    opts["ratelimit"]  = rate
    if proxy:   opts["proxy"]      = proxy
    return opts


# ══════════════════════════════════════════════════
#  DOWNLOAD THREAD
# ══════════════════════════════════════════════════
def run_download(urls, cfg, prog_cb, status_cb, speed_cb, eta_cb, file_cb, done_cb):
    hook = make_hook(prog_cb, status_cb, speed_cb, eta_cb, file_cb)
    opts = build_opts(cfg, hook)
    os.makedirs(cfg["output_dir"], exist_ok=True)

    with yt_dlp.YoutubeDL(opts) as ydl:
        for url in urls:
            url = url.strip()
            if not url:
                continue
            qlog(f"🔍  Resolving: {url}", "info")
            try:
                info = ydl.extract_info(url, download=False)
                if info:
                    if info.get("_type") in ("playlist", "channel"):
                        entries = list(info.get("entries") or [])
                        qlog(f"📋  Channel/Playlist — {len(entries)} videos found", "info")
                    else:
                        title = info.get("title", "Unknown")
                        res   = info.get("resolution") or f"{info.get('height','?')}p"
                        dur   = info.get("duration_string", "?")
                        up    = info.get("uploader", "?")
                        qlog(f"   Title    : {title}", "info")
                        qlog(f"   Uploader : {up}  |  Duration : {dur}  |  Res : {res}", "info")
            except Exception as e:
                qlog(f"⚠  Pre-fetch error: {e}", "warning")

            qlog("⬇  Starting download …", "info")
            ydl.download([url])

    qlog("🏁  All downloads complete!", "success")
    done_cb()


# ══════════════════════════════════════════════════
#  CUSTOM CANVAS PROGRESS BAR
# ══════════════════════════════════════════════════
class GlowProgressBar(tk.Canvas):
    def __init__(self, parent, **kw):
        super().__init__(parent, bg=C["surface"], bd=0,
                         highlightthickness=0, height=28, **kw)
        self._pct = 0.0
        self.bind("<Configure>", lambda e: self._draw())

    def set(self, pct: float):
        self._pct = max(0.0, min(100.0, pct))
        self._draw()

    def _draw(self):
        self.delete("all")
        W = self.winfo_width()
        H = self.winfo_height()
        if W < 2:
            return
        r = H // 2

        def rr(x1, y1, x2, y2, rad, **kw):
            if x2 - x1 < 2: return
            rad = min(rad, (x2 - x1) // 2, (y2 - y1) // 2)
            if rad < 1:
                self.create_rectangle(x1, y1, x2, y2, **kw)
                return
            pts = [x1+rad,y1, x2-rad,y1, x2,y1, x2,y1+rad,
                   x2,y2-rad, x2,y2, x2-rad,y2, x1+rad,y2,
                   x1,y2, x1,y2-rad, x1,y1+rad, x1,y1]
            self.create_polygon(pts, smooth=True, **kw)

        rr(0, 0, W, H, r, fill=C["border"], outline="")
        fill_w = int(W * self._pct / 100)
        if fill_w > r * 2:
            rr(0, 0, fill_w, H, r, fill=C["accent2"], outline="")
            shine_h = max(3, H // 4)
            rr(2, 2, fill_w - 2, 2 + shine_h, shine_h // 2,
               fill="#FFFFFF22", outline="")

        txt = f"{self._pct:.1f}%"
        self.create_text(W // 2, H // 2, text=txt,
                         fill=C["text"], font=("Consolas", 10, "bold"))


# ══════════════════════════════════════════════════
#  TOGGLE SWITCH
# ══════════════════════════════════════════════════
class ToggleSwitch(tk.Canvas):
    def __init__(self, parent, variable: ctk.BooleanVar, on_color=None, **kw):
        super().__init__(parent, width=46, height=24,
                         bg=C["card"], bd=0, highlightthickness=0, **kw)
        self._var = variable
        self._on  = on_color or C["accent"]
        self._var.trace_add("write", lambda *_: self._draw())
        self.bind("<Button-1>", lambda e: self._var.set(not self._var.get()))
        self._draw()

    def _draw(self):
        self.delete("all")
        on = self._var.get()
        W, H, r = 46, 24, 12
        col = self._on if on else C["border2"]
        self.create_oval(0, 0, H, H, fill=col, outline="")
        self.create_oval(W-H, 0, W, H, fill=col, outline="")
        self.create_rectangle(r, 0, W-r, H, fill=col, outline="")
        m = 3
        kx = W-H+m if on else m
        self.create_oval(kx, m, kx+H-2*m, H-m, fill=C["text"], outline="")


# ══════════════════════════════════════════════════
#  MAIN APP
# ══════════════════════════════════════════════════
class App(ctk.CTk):

    def __init__(self):
        super().__init__()
        self.title("4K Downloader  ·  Built with love by Rahul")
        self.geometry("960x920")
        self.minsize(820, 800)
        self.configure(fg_color=C["bg"])

        self._busy = False

        self._audio_v = ctk.BooleanVar(value=False)
        self._nomerge_v = ctk.BooleanVar(value=False)
        self._subs_v  = ctk.BooleanVar(value=False)
        self._pl_v    = ctk.BooleanVar(value=False)
        self._chan_v  = ctk.BooleanVar(value=False)
        self._dir_v   = ctk.StringVar(
            value=os.path.join(os.path.expanduser("~"), "Downloads", "YT4K"))
        self._rate_v  = ctk.StringVar(value="")
        self._cook_v  = ctk.StringVar(value="")
        self._proxy_v = ctk.StringVar(value="")

        self._build()
        self._poll()

    # ─── POLL LOG ───────────────────────────
    def _poll(self):
        try:
            while True:
                msg, kind = LOG_Q.get_nowait()
                self._write_log(msg, kind)
        except queue.Empty:
            pass
        self.after(80, self._poll)

    def _write_log(self, msg, kind="info"):
        self._log.configure(state="normal")
        self._log.insert("end", msg + "\n", kind)
        self._log.see("end")
        self._log.configure(state="disabled")

    # ─── BUILD ──────────────────────────────
    def _build(self):
        # ── TOP BAR ──────────────────────────
        bar = tk.Frame(self, bg=C["surface"], height=68)
        bar.pack(fill="x")
        bar.pack_propagate(False)

        tk.Frame(bar, bg=C["accent"], width=4).pack(side="left", fill="y")

        lf = tk.Frame(bar, bg=C["surface"])
        lf.pack(side="left", padx=20, pady=0)
        tk.Label(lf, text="▶", bg=C["surface"], fg=C["accent"],
                 font=("Consolas", 24, "bold")).pack(side="left", padx=(0,10))
        lt = tk.Frame(lf, bg=C["surface"])
        lt.pack(side="left")
        tk.Label(lt, text="4K DOWNLOADER",
                 bg=C["surface"], fg=C["text"],
                 font=("Consolas", 17, "bold")).pack(anchor="w")
        tk.Label(lt, text="built with love by Rahul",
                 bg=C["surface"], fg=C["text3"],
                 font=("Consolas", 9)).pack(anchor="w")

        pill = tk.Frame(bar, bg="#0E2030", padx=12, pady=6)
        pill.pack(side="right", padx=22, pady=18)
        tk.Label(pill, text="chetta", bg="#0E2030",
                 fg=C["accent"], font=("Consolas", 9, "bold")).pack()
        body = ctk.CTkScrollableFrame(self, fg_color=C["bg"],
                                      scrollbar_button_color=C["border2"])
        body.pack(fill="both", expand=True)
        self._sec(body, "01", "SOURCE URLs")
        uw = self._panel(body)
        tk.Label(uw, text="One URL per line  ·  Video  /  Playlist  /  Channel",
                 bg=C["card"], fg=C["text3"],
                 font=("Consolas", 10)).pack(anchor="w", padx=14, pady=(10, 4))
        self._url_box = tk.Text(uw, height=7, bg="#090E14", fg=C["text"],
                                insertbackground=C["accent"],
                                font=("Consolas", 12), bd=0, relief="flat",
                                wrap="word", selectbackground=C["border2"],
                                padx=10, pady=8)
        self._url_box.pack(fill="x", padx=10, pady=(0, 10))
        self._url_box.insert("end", "https://www.youtube.com/watch?v=")

        self._sec(body, "02", "OUTPUT DIRECTORY")
        dw = self._panel(body)
        di = tk.Frame(dw, bg=C["card"])
        di.pack(fill="x", padx=14, pady=12)
        de = tk.Entry(di, textvariable=self._dir_v,
                      bg="#090E14", fg=C["text"],
                      insertbackground=C["accent"],
                      font=("Consolas", 12), bd=0,
                      highlightthickness=1,
                      highlightbackground=C["border"],
                      highlightcolor=C["accent"])
        de.pack(side="left", fill="x", expand=True, ipady=7, padx=(0, 10))
        tk.Button(di, text="Browse",
                  bg=C["border2"], fg=C["text"],
                  font=("Consolas", 11, "bold"),
                  relief="flat", padx=16, pady=7,
                  activebackground=C["accent2"],
                  activeforeground=C["text"],
                  cursor="hand2",
                  command=self._browse).pack(side="right")

        self._sec(body, "03", "DOWNLOAD MODE")
        mw = self._panel(body)
        mg = tk.Frame(mw, bg=C["card"])
        mg.pack(fill="x", padx=14, pady=14)

        toggles = [
            ("🎵  Audio Only  —  MP3 320 kbps", self._audio_v,  C["accent"]),
            ("📦  No Merge  —  skip ffmpeg",    self._nomerge_v, C["accent2"]),
            ("📝  Download Subtitles (EN)",      self._subs_v,   C["accent3"]),
            ("📋  Playlist Mode",                self._pl_v,     C["yellow"]),
        ]
        for i, (lbl, var, col) in enumerate(toggles):
            r, c = divmod(i, 2)
            f = tk.Frame(mg, bg=C["card"])
            f.grid(row=r, column=c, sticky="w", padx=(0, 50), pady=7)
            ts = ToggleSwitch(f, var, on_color=col)
            ts.pack(side="left", padx=(0, 10))
            tk.Label(f, text=lbl, bg=C["card"], fg=C["text"],
                     font=("Consolas", 12)).pack(side="left")

        self._sec(body, "04", "CHANNEL MODE  —  download everything from a channel")
        cw = tk.Frame(body, bg="#081810",
                      highlightbackground=C["accent3"],
                      highlightthickness=1)
        cw.pack(fill="x", padx=20, pady=(0, 20))
        ci = tk.Frame(cw, bg="#081810")
        ci.pack(fill="x", padx=14, pady=14)
        ToggleSwitch(ci, self._chan_v, on_color=C["accent3"]).pack(side="left", padx=(0,14))
        ct = tk.Frame(ci, bg="#081810")
        ct.pack(side="left", fill="x", expand=True)
        tk.Label(ct, text="Download ALL videos from a channel",
                 bg="#081810", fg=C["accent3"],
                 font=("Consolas", 13, "bold")).pack(anchor="w")
        tk.Label(ct,
                 text="Paste a channel URL  ·  e.g.  https://www.youtube.com/@ChannelName/videos\n"
                      "Videos are saved in a sub-folder named after the channel.",
                 bg="#081810", fg=C["text2"],
                 font=("Consolas", 10), justify="left").pack(anchor="w", pady=(3, 0))

        self._sec(body, "05", "ADVANCED OPTIONS")
        aw = self._panel(body)
        ag = tk.Frame(aw, bg=C["card"])
        ag.pack(fill="x", padx=14, pady=14)
        ag.columnconfigure(0, weight=1)
        ag.columnconfigure(1, weight=1)
        ag.columnconfigure(2, weight=1)

        adv_fields = [
            ("Rate Limit", "e.g. 2M or 500K",        self._rate_v),
            ("Cookies File", "path/to/cookies.txt",   self._cook_v),
            ("Proxy",      "socks5://127.0.0.1:1080", self._proxy_v),
        ]
        for col, (lbl, ph, var) in enumerate(adv_fields):
            f = tk.Frame(ag, bg=C["card"])
            f.grid(row=0, column=col, sticky="ew", padx=(0, 14))
            tk.Label(f, text=lbl, bg=C["card"], fg=C["text2"],
                     font=("Consolas", 10)).pack(anchor="w", pady=(0, 3))
            e = tk.Entry(f, textvariable=var,
                         bg="#090E14", fg=C["text3"],
                         insertbackground=C["accent"],
                         font=("Consolas", 11), bd=0,
                         highlightthickness=1,
                         highlightbackground=C["border"],
                         highlightcolor=C["accent"])
            e.pack(fill="x", ipady=6)
            e.insert(0, ph)

            def _in(ev, en=e, p=ph, fg=C["text"]):
                if en.get() == p:
                    en.delete(0, "end")
                    en.config(fg=fg)

            def _out(ev, en=e, p=ph, fg=C["text3"]):
                if not en.get():
                    en.insert(0, p)
                    en.config(fg=fg)

            e.bind("<FocusIn>",  _in)
            e.bind("<FocusOut>", _out)

        self._sec(body, "06", "LIVE PROGRESS")
        pw = self._panel(body)
        pi = tk.Frame(pw, bg=C["card"])
        pi.pack(fill="x", padx=14, pady=14)

        self._file_lbl = tk.Label(pi, text="No file selected",
                                   bg=C["card"], fg=C["text3"],
                                   font=("Consolas", 10), anchor="w")
        self._file_lbl.pack(fill="x", pady=(0, 8))

        self._pbar = GlowProgressBar(pi)
        self._pbar.pack(fill="x", pady=(0, 12))

        sr = tk.Frame(pi, bg=C["card"])
        sr.pack(fill="x")

        self._status_lbl = tk.Label(sr, text="Ready",
                                     bg=C["card"], fg=C["text"],
                                     font=("Consolas", 12, "bold"), anchor="w")
        self._status_lbl.pack(side="left")

        for label, attr, color in [("ETA", "_eta_lbl", C["accent3"]),
                                    ("SPEED", "_speed_lbl", C["accent"])]:
            sf = tk.Frame(sr, bg=C["card"])
            sf.pack(side="right", padx=(0, 28))
            tk.Label(sf, text=label, bg=C["card"], fg=C["text3"],
                     font=("Consolas", 8, "bold")).pack(anchor="e")
            lb = tk.Label(sf, text="—", bg=C["card"], fg=color,
                          font=("Consolas", 13, "bold"))
            lb.pack(anchor="e")
            setattr(self, attr, lb)

        self._sec(body, "07", "REAL-TIME LOG")
        lw = tk.Frame(body, bg=C["surface"],
                      highlightbackground=C["border"],
                      highlightthickness=1)
        lw.pack(fill="x", padx=20, pady=(0, 20))

        log_header = tk.Frame(lw, bg=C["card"])
        log_header.pack(fill="x")
        tk.Label(log_header, text=" OUTPUT", bg=C["card"], fg=C["text3"],
                 font=("Consolas", 9, "bold")).pack(side="left", padx=8, pady=6)

        for txt, cmd in [("Save", self._save_log), ("Clear", self._clear_log)]:
            tk.Button(log_header, text=txt,
                      bg=C["card"], fg=C["text3"],
                      font=("Consolas", 9), relief="flat",
                      activebackground=C["border2"],
                      activeforeground=C["text"],
                      cursor="hand2", padx=10, pady=4,
                      command=cmd).pack(side="right")

        log_body = tk.Frame(lw, bg=C["surface"])
        log_body.pack(fill="x")

        self._log = tk.Text(log_body, height=15,
                            bg=C["surface"], fg=C["text"],
                            insertbackground=C["accent"],
                            font=("Consolas", 10),
                            bd=0, relief="flat",
                            wrap="word", state="disabled",
                            selectbackground=C["border2"],
                            padx=12, pady=10)
        self._log.pack(side="left", fill="x", expand=True)

        sb = tk.Scrollbar(log_body, orient="vertical",
                          command=self._log.yview,
                          troughcolor=C["surface"],
                          bg=C["border"])
        sb.pack(side="right", fill="y")
        self._log.configure(yscrollcommand=sb.set)

        self._log.tag_config("info",    foreground=C["text2"])
        self._log.tag_config("dl",      foreground="#4FA3E0")
        self._log.tag_config("success", foreground=C["success"])
        self._log.tag_config("warning", foreground=C["warning"])
        self._log.tag_config("error",   foreground=C["error"])
        bf = tk.Frame(body, bg=C["bg"])
        bf.pack(fill="x", padx=20, pady=(8, 8))

        self._dl_btn = tk.Button(
            bf,
            text="⬇   START DOWNLOAD",
            bg=C["accent2"], fg="#FFFFFF",
            font=("Consolas", 15, "bold"),
            relief="flat", bd=0,
            pady=18,
            activebackground=C["accent"],
            activeforeground="#FFFFFF",
            cursor="hand2",
            command=self._start,
        )
        self._dl_btn.pack(fill="x")
        tk.Label(body,
                 text="built with love by Rahul ",
                 bg=C["bg"], fg=C["text3"],
                 font=("Consolas", 9)).pack(pady=(12, 24))

    def _sec(self, parent, num, title):
        f = tk.Frame(parent, bg=C["bg"])
        f.pack(fill="x", padx=20, pady=(22, 6))
        tk.Label(f, text=num, bg=C["bg"], fg=C["accent"],
                 font=("Consolas", 9, "bold")).pack(side="left", padx=(0, 8))
        tk.Label(f, text=title, bg=C["bg"], fg=C["text3"],
                 font=("Consolas", 10, "bold")).pack(side="left")
        tk.Frame(f, bg=C["border"], height=1).pack(
            side="left", fill="x", expand=True, padx=(12, 0), pady=7)

    def _panel(self, parent):
        f = tk.Frame(parent, bg=C["card"],
                     highlightbackground=C["border"],
                     highlightthickness=1)
        f.pack(fill="x", padx=20, pady=(0, 4))
        return f

    def _prog_cb(self, pct):
        self.after(0, lambda: self._pbar.set(pct))

    def _status_cb(self, s):
        self.after(0, lambda: self._status_lbl.config(text=s))

    def _speed_cb(self, s):
        self.after(0, lambda: self._speed_lbl.config(text=s))

    def _eta_cb(self, s):
        self.after(0, lambda: self._eta_lbl.config(text=s))

    def _file_cb(self, s):
        short = (s[:72] + "…") if len(s) > 72 else s
        self.after(0, lambda: self._file_lbl.config(text=short))

    def _on_done(self):
        self._busy = False
        self.after(0, lambda: self._dl_btn.config(
            text="⬇   START DOWNLOAD",
            bg=C["accent2"], state="normal"))

    def _browse(self):
        d = filedialog.askdirectory(title="Select Output Folder")
        if d:
            self._dir_v.set(d)

    def _clear_log(self):
        self._log.configure(state="normal")
        self._log.delete("1.0", "end")
        self._log.configure(state="disabled")

    def _save_log(self):
        p = filedialog.asksaveasfilename(
            defaultextension=".txt",
            filetypes=[("Text files", "*.txt"), ("All files", "*.*")],
            title="Save Log")
        if p:
            with open(p, "w", encoding="utf-8") as f:
                f.write(self._log.get("1.0", "end"))

    def _start(self):
        if self._busy:
            return

        raw  = self._url_box.get("1.0", "end").strip().splitlines()
        urls = [u.strip() for u in raw
                if u.strip() and u.strip().startswith("http")]

        if not urls:
            qlog("⚠  Please enter at least one valid URL (must start with http).", "warning")
            return

        self._busy = True
        self._dl_btn.config(text="⏳  Downloading …",
                             bg="#1A3A4A", state="disabled")
        self._pbar.set(0)
        self._status_lbl.config(text="Starting …")

        placeholders = {"e.g. 2M or 500K", "path/to/cookies.txt",
                        "socks5://127.0.0.1:1080"}

        def _clean(v):
            s = v.get().strip()
            return None if (not s or s in placeholders) else s

        cfg = {
            "output_dir":  self._dir_v.get(),
            "audio_only":  self._audio_v.get(),
            "no_merge":    self._nomerge_v.get(),
            "subtitles":   self._subs_v.get(),
            "playlist":    self._pl_v.get(),
            "channel_all": self._chan_v.get(),
            "rate_limit":  _clean(self._rate_v),
            "cookies":     _clean(self._cook_v),
            "proxy":       _clean(self._proxy_v),
        }

        now = datetime.datetime.now().strftime("%H:%M:%S")
        qlog(f"━━  Session started  ·  {len(urls)} URL(s)  ·  {now}  ━━", "info")

        threading.Thread(
            target=run_download,
            args=(urls, cfg, self._prog_cb, self._status_cb,
                  self._speed_cb, self._eta_cb, self._file_cb, self._on_done),
            daemon=True
        ).start()
# ══════════════════════════════════════════════════
#  ENTRY
# ══════════════════════════════════════════════════
if __name__ == "__main__":
    app = App()
    app.mainloop()