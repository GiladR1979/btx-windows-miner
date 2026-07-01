#!/usr/bin/env python3
"""
BTX Native Windows Miner — GUI
================================

A self-contained Tkinter front-end for mining BTX (BitcoinTX) on Windows with
a native (non-WSL) CUDA solver. It drives the `dexbtx_miner` stratum client,
which in turn spawns the native `btx-gbt-solve.exe` GPU solver built for
Windows/MSVC+CUDA.

No third-party Python packages required — Tkinter ships with CPython on Windows.

What it does:
  * Collects your payout WALLET ADDRESS, worker name, pool, and GPU tuning.
  * Launches the miner as a subprocess, streaming its output live.
  * Parses accepted/rejected shares, blocks, and hashrate into a status bar.
  * Cleanly stops the whole process tree (miner + solver) on Stop / close.

Author: github.com/GiladR1979  ·  MIT License
"""

from __future__ import annotations

import json
import os
import queue
import re
import socket
import subprocess
import sys
import threading
import time
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, font, messagebox, scrolledtext, ttk

# ───────────────────────────── paths & defaults ─────────────────────────────

APP_DIR = Path(__file__).resolve().parent
REPO_DIR = APP_DIR.parent
VENDORED_MINER = REPO_DIR / "miner"            # contains dexbtx_miner/ package
CONFIG_PATH = Path.home() / ".btx-miner-gui.json"

DEFAULTS = {
    "wallet": "",
    "worker": socket.gethostname().lower().replace(" ", "-") or "rig1",
    "pool": "pool.minebtx.com:3333",
    "solver": str(REPO_DIR / "bin" / "btx-gbt-solve.exe"),
    "threads": "8",
    "prepare_workers": "16",
    "batch_size": "128",
    "gpu_inputs": "1",
}

# Colours (dark theme)
BG = "#0f1419"
BG2 = "#1a2029"
FG = "#e6e6e6"
MUTED = "#8a93a0"
ACCENT = "#f7931a"        # bitcoin orange
GREEN = "#2ecc71"
RED = "#e74c3c"
BLUE = "#3498db"


# ───────────────────────────── the application ──────────────────────────────

class MinerGUI:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.proc: subprocess.Popen | None = None
        self.reader_thread: threading.Thread | None = None
        self.log_queue: "queue.Queue[str]" = queue.Queue()
        self.start_time: float | None = None

        # live stats
        self.accepted = 0
        self.rejected = 0
        self.blocks = 0
        self.hashrate = "—"
        self.difficulty = "—"

        self.cfg = self._load_config()

        root.title("BTX Native Windows Miner")
        root.configure(bg=BG)
        root.minsize(720, 640)
        try:
            root.iconbitmap(default=str(APP_DIR / "btx.ico"))
        except Exception:
            pass

        self._build_styles()
        self._build_ui()
        self._restore_config()

        root.protocol("WM_DELETE_WINDOW", self._on_close)
        self.root.after(120, self._drain_log)
        self.root.after(1000, self._tick)

    # ── persistence ──────────────────────────────────────────────────────────

    def _load_config(self) -> dict:
        cfg = dict(DEFAULTS)
        try:
            if CONFIG_PATH.exists():
                cfg.update(json.loads(CONFIG_PATH.read_text("utf-8")))
        except Exception:
            pass
        return cfg

    def _save_config(self) -> None:
        try:
            data = {
                "wallet": self.var_wallet.get().strip(),
                "worker": self.var_worker.get().strip(),
                "pool": self.var_pool.get().strip(),
                "solver": self.var_solver.get().strip(),
                "threads": self.var_threads.get().strip(),
                "prepare_workers": self.var_prep.get().strip(),
                "batch_size": self.var_batch.get().strip(),
                "gpu_inputs": self.var_gpu.get().strip(),
            }
            CONFIG_PATH.write_text(json.dumps(data, indent=2), "utf-8")
        except Exception:
            pass

    # ── styling ──────────────────────────────────────────────────────────────

    def _build_styles(self) -> None:
        self.f_title = font.Font(family="Segoe UI Semibold", size=16)
        self.f_sub = font.Font(family="Segoe UI", size=9)
        self.f_label = font.Font(family="Segoe UI", size=10)
        self.f_mono = font.Font(family="Consolas", size=9)
        self.f_stat = font.Font(family="Segoe UI Semibold", size=12)
        self.f_statlbl = font.Font(family="Segoe UI", size=8)

        st = ttk.Style()
        try:
            st.theme_use("clam")
        except Exception:
            pass
        st.configure("TEntry", fieldbackground=BG2, foreground=FG,
                     bordercolor=MUTED, insertcolor=FG, padding=5)
        st.configure("Adv.TLabelframe", background=BG, bordercolor=MUTED)
        st.configure("Adv.TLabelframe.Label", background=BG, foreground=MUTED)

    # ── UI construction ───────────────────────────────────────────────────────

    def _build_ui(self) -> None:
        pad = {"padx": 16}

        header = tk.Frame(self.root, bg=BG)
        header.pack(fill="x", pady=(14, 6), **pad)
        tk.Label(header, text="⛏  BTX Native Windows Miner", font=self.f_title,
                 bg=BG, fg=ACCENT).pack(anchor="w")
        tk.Label(header, text="Native CUDA solver (no WSL)  ·  drives dexbtx-miner",
                 font=self.f_sub, bg=BG, fg=MUTED).pack(anchor="w")

        form = tk.Frame(self.root, bg=BG)
        form.pack(fill="x", pady=4, **pad)
        form.columnconfigure(1, weight=1)

        # ── WALLET ADDRESS — the headline field ──
        tk.Label(form, text="Wallet address", font=self.f_label, bg=BG, fg=FG
                 ).grid(row=0, column=0, sticky="w", pady=(6, 2))
        self.var_wallet = tk.StringVar()
        self.e_wallet = ttk.Entry(form, textvariable=self.var_wallet, font=self.f_mono)
        self.e_wallet.grid(row=1, column=0, columnspan=2, sticky="ew", ipady=3)
        tk.Label(form, text="Your transparent BTX payout address (btx1z…). Earnings are paid here.",
                 font=self.f_sub, bg=BG, fg=MUTED).grid(row=2, column=0, columnspan=2,
                                                        sticky="w", pady=(2, 8))

        # ── Worker + Pool ──
        tk.Label(form, text="Worker name", font=self.f_label, bg=BG, fg=FG
                 ).grid(row=3, column=0, sticky="w", pady=(2, 2))
        tk.Label(form, text="Pool (host:port)", font=self.f_label, bg=BG, fg=FG
                 ).grid(row=3, column=1, sticky="w", pady=(2, 2), padx=(8, 0))
        self.var_worker = tk.StringVar()
        self.var_pool = tk.StringVar()
        ttk.Entry(form, textvariable=self.var_worker, font=self.f_mono
                  ).grid(row=4, column=0, sticky="ew", ipady=2)
        ttk.Entry(form, textvariable=self.var_pool, font=self.f_mono
                  ).grid(row=4, column=1, sticky="ew", ipady=2, padx=(8, 0))

        # ── Solver binary ──
        tk.Label(form, text="Solver binary  (btx-gbt-solve.exe)", font=self.f_label,
                 bg=BG, fg=FG).grid(row=5, column=0, columnspan=2, sticky="w", pady=(10, 2))
        solver_row = tk.Frame(form, bg=BG)
        solver_row.grid(row=6, column=0, columnspan=2, sticky="ew")
        solver_row.columnconfigure(0, weight=1)
        self.var_solver = tk.StringVar()
        ttk.Entry(solver_row, textvariable=self.var_solver, font=self.f_mono
                  ).grid(row=0, column=0, sticky="ew", ipady=2)
        tk.Button(solver_row, text="Browse…", command=self._browse_solver,
                  bg=BG2, fg=FG, relief="flat", font=self.f_label, padx=10,
                  activebackground=MUTED).grid(row=0, column=1, padx=(8, 0))

        # ── Advanced tuning ──
        adv = ttk.Labelframe(self.root, text=" GPU tuning (canonical defaults — fine for most cards) ",
                             style="Adv.TLabelframe")
        adv.pack(fill="x", pady=10, **pad)
        for i in range(8):
            adv.columnconfigure(i, weight=1)
        self.var_threads = tk.StringVar()
        self.var_prep = tk.StringVar()
        self.var_batch = tk.StringVar()
        self.var_gpu = tk.StringVar()

        def tune(col, label, var, hint):
            tk.Label(adv, text=label, font=self.f_statlbl, bg=BG, fg=MUTED
                     ).grid(row=0, column=col * 2, columnspan=2, sticky="w", padx=6, pady=(6, 0))
            ttk.Entry(adv, textvariable=var, font=self.f_mono, width=6
                      ).grid(row=1, column=col * 2, columnspan=2, sticky="w", padx=6, pady=(0, 8))

        tune(0, "Solver threads", self.var_threads, "")
        tune(1, "Prepare workers", self.var_prep, "")
        tune(2, "Batch size", self.var_batch, "")
        tune(3, "GPU inputs", self.var_gpu, "")

        # ── Action buttons ──
        actions = tk.Frame(self.root, bg=BG)
        actions.pack(fill="x", pady=(2, 8), **pad)
        self.btn_start = tk.Button(actions, text="▶  Start Mining", command=self.start,
                                   bg=GREEN, fg="#06251a", relief="flat",
                                   font=font.Font(family="Segoe UI Semibold", size=11),
                                   padx=18, pady=8, activebackground="#27ae60")
        self.btn_start.pack(side="left")
        self.btn_stop = tk.Button(actions, text="■  Stop", command=self.stop,
                                  bg=RED, fg="#2a0a06", relief="flat",
                                  font=font.Font(family="Segoe UI Semibold", size=11),
                                  padx=18, pady=8, activebackground="#c0392b",
                                  state="disabled")
        self.btn_stop.pack(side="left", padx=(10, 0))
        self.lbl_state = tk.Label(actions, text="● Idle", font=self.f_label, bg=BG, fg=MUTED)
        self.lbl_state.pack(side="right")

        # ── Stats bar ──
        stats = tk.Frame(self.root, bg=BG2)
        stats.pack(fill="x", **pad)
        self.stat_vals = {}
        for i, (key, label) in enumerate([
            ("difficulty", "POOL DIFF"), ("accepted", "ACCEPTED"),
            ("rejected", "REJECTED"), ("blocks", "BLOCKS"), ("uptime", "UPTIME"),
        ]):
            cell = tk.Frame(stats, bg=BG2)
            cell.grid(row=0, column=i, sticky="nsew", padx=2, pady=8)
            stats.columnconfigure(i, weight=1)
            v = tk.Label(cell, text="—", font=self.f_stat, bg=BG2,
                         fg=ACCENT if key == "difficulty" else FG)
            v.pack()
            tk.Label(cell, text=label, font=self.f_statlbl, bg=BG2, fg=MUTED).pack()
            self.stat_vals[key] = v

        # ── Log ──
        logframe = tk.Frame(self.root, bg=BG)
        logframe.pack(fill="both", expand=True, pady=(10, 14), **pad)
        tk.Label(logframe, text="Miner log", font=self.f_label, bg=BG, fg=MUTED
                 ).pack(anchor="w")
        self.log = scrolledtext.ScrolledText(
            logframe, bg="#0a0d12", fg="#c8d0da", insertbackground=FG,
            font=self.f_mono, relief="flat", height=12, wrap="word", state="disabled")
        self.log.pack(fill="both", expand=True, pady=(4, 0))
        self.log.tag_config("ok", foreground=GREEN)
        self.log.tag_config("bad", foreground=RED)
        self.log.tag_config("blk", foreground=ACCENT)
        self.log.tag_config("info", foreground=MUTED)

    # ── config <-> widgets ─────────────────────────────────────────────────────

    def _restore_config(self) -> None:
        self.var_wallet.set(self.cfg.get("wallet", ""))
        self.var_worker.set(self.cfg.get("worker", DEFAULTS["worker"]))
        self.var_pool.set(self.cfg.get("pool", DEFAULTS["pool"]))
        self.var_solver.set(self.cfg.get("solver", DEFAULTS["solver"]))
        self.var_threads.set(self.cfg.get("threads", DEFAULTS["threads"]))
        self.var_prep.set(self.cfg.get("prepare_workers", DEFAULTS["prepare_workers"]))
        self.var_batch.set(self.cfg.get("batch_size", DEFAULTS["batch_size"]))
        self.var_gpu.set(self.cfg.get("gpu_inputs", DEFAULTS["gpu_inputs"]))

    def _browse_solver(self) -> None:
        p = filedialog.askopenfilename(
            title="Select btx-gbt-solve.exe",
            filetypes=[("Executable", "*.exe"), ("All files", "*.*")])
        if p:
            self.var_solver.set(p)

    # ── start / stop ───────────────────────────────────────────────────────────

    def start(self) -> None:
        if self.proc is not None:
            return
        wallet = self.var_wallet.get().strip()
        pool = self.var_pool.get().strip()
        solver = self.var_solver.get().strip()

        if not wallet:
            messagebox.showerror("Missing wallet", "Enter your BTX payout address first.")
            return
        if not (wallet.startswith("btx1") or wallet.startswith("BTX1")):
            if not messagebox.askyesno(
                    "Unusual address",
                    f"'{wallet[:16]}…' doesn't look like a btx1z… address.\n"
                    "Mine to it anyway?"):
                return
        if not Path(solver).exists():
            messagebox.showerror(
                "Solver not found",
                f"btx-gbt-solve.exe not found at:\n{solver}\n\n"
                "Build it (see solver/build-windows.ps1) or point to it with Browse.")
            return

        miner_cmd = self._build_command(wallet, pool, solver)
        env = self._build_env()

        try:
            self.proc = subprocess.Popen(
                miner_cmd, env=env, cwd=str(REPO_DIR),
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                stdin=subprocess.DEVNULL, text=True, bufsize=1,
                encoding="utf-8", errors="replace",
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0)
                | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0),
            )
        except Exception as e:
            messagebox.showerror("Launch failed", str(e))
            self.proc = None
            return

        self.accepted = self.rejected = self.blocks = 0
        self.hashrate = "—"
        self.start_time = time.time()
        self._save_config()

        self.reader_thread = threading.Thread(target=self._reader, daemon=True)
        self.reader_thread.start()

        self.btn_start.config(state="disabled")
        self.btn_stop.config(state="normal")
        self.lbl_state.config(text="● Mining", fg=GREEN)
        self._set_inputs_state("disabled")
        self._append(f"$ {' '.join(self._display_cmd(miner_cmd))}\n", "info")

    def stop(self) -> None:
        p = self.proc
        if p is None:
            return
        self._append("\n[stopping miner …]\n", "info")
        self.proc = None  # signal reader to wind down
        try:
            # Kill the whole tree: python wrapper + btx-gbt-solve.exe child.
            subprocess.run(["taskkill", "/F", "/T", "/PID", str(p.pid)],
                           creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                           capture_output=True)
        except Exception:
            try:
                p.terminate()
            except Exception:
                pass
        self.btn_start.config(state="normal")
        self.btn_stop.config(state="disabled")
        self.lbl_state.config(text="● Idle", fg=MUTED)
        self._set_inputs_state("normal")

    @staticmethod
    def _python_exe() -> str:
        # Never launch the miner with pythonw.exe: under pythonw sys.stderr is
        # None, so the miner's logging (which we stream into the status panel) is
        # lost and its async subprocess handling misbehaves. Prefer python.exe.
        py = sys.executable
        if py.lower().endswith("pythonw.exe"):
            cand = py[:-len("pythonw.exe")] + "python.exe"
            if Path(cand).exists():
                return cand
        return py

    def _build_command(self, wallet: str, pool: str, solver: str) -> list[str]:
        cmd = [self._python_exe(), "-m", "dexbtx_miner",
               "--pool", pool,
               "--address", wallet,
               "--worker", self.var_worker.get().strip() or "default",
               "--gbt-solve", solver,
               "--log-level", "INFO"]
        for flag, var in [("--threads", self.var_threads),
                          ("--prepare-workers", self.var_prep),
                          ("--batch-size", self.var_batch),
                          ("--gpu-inputs", self.var_gpu)]:
            val = var.get().strip()
            if val:
                cmd += [flag, val]
        return cmd

    def _build_env(self) -> dict:
        env = dict(os.environ)
        # Make the vendored dexbtx_miner importable without a pip install.
        if (VENDORED_MINER / "dexbtx_miner").is_dir():
            env["PYTHONPATH"] = str(VENDORED_MINER) + os.pathsep + env.get("PYTHONPATH", "")
        env["PYTHONUNBUFFERED"] = "1"
        # We ship our own native solver — never let the wrapper phone home to
        # download/replace it or pip-upgrade itself (that path targets Linux).
        env["DEXBTX_NO_SOLVER_AUTOUPDATE"] = "1"
        env["DEXBTX_NO_WRAPPER_AUTOUPDATE"] = "1"
        env["DEXBTX_NO_SOLVER_RECHECK"] = "1"
        return env

    @staticmethod
    def _display_cmd(cmd: list[str]) -> list[str]:
        out = []
        for c in cmd:
            out.append(f'"{c}"' if " " in c else c)
        return out

    def _set_inputs_state(self, state: str) -> None:
        for w in (self.e_wallet,):
            try:
                w.config(state=state)
            except Exception:
                pass

    # ── output reader (background thread) ──────────────────────────────────────

    def _reader(self) -> None:
        p = self.proc
        if p is None or p.stdout is None:
            return
        try:
            for line in p.stdout:
                self.log_queue.put(line)
                if self.proc is None:
                    break
        except Exception as e:
            self.log_queue.put(f"[reader error: {e}]\n")
        finally:
            rc = None
            try:
                rc = p.wait(timeout=2)
            except Exception:
                pass
            self.log_queue.put(f"\n[miner exited{'' if rc is None else f' (code {rc})'}]\n")
            self.log_queue.put("__MINER_DONE__")

    # ── periodic Tk callbacks ──────────────────────────────────────────────────

    def _drain_log(self) -> None:
        try:
            while True:
                line = self.log_queue.get_nowait()
                if line == "__MINER_DONE__":
                    self._on_miner_done()
                    continue
                self._parse_stats(line)
                self._append(line, self._tag_for(line))
        except queue.Empty:
            pass
        self.root.after(120, self._drain_log)

    def _on_miner_done(self) -> None:
        if self.proc is not None:   # unexpected exit (crash) while we thought we were running
            self.proc = None
            self.btn_start.config(state="normal")
            self.btn_stop.config(state="disabled")
            self.lbl_state.config(text="● Stopped", fg=RED)
            self._set_inputs_state("normal")

    @staticmethod
    def _tag_for(line: str) -> str:
        low = line.lower()
        if "share ok" in low or "accepted" in low or "block found" in low:
            return "ok"
        if "reject" in low or "error" in low or "fail" in low:
            return "bad"
        if "block" in low:
            return "blk"
        return ""

    _re_totals = re.compile(r"accepted=(\d+)\s+rejected=(\d+)\s+blocks=(\d+)")
    _re_hash = re.compile(r"([\d.]+)\s*(KN/s|MN/s|N/s|nps|H/s|kH/s|MH/s|GH/s)", re.I)
    _re_arb = re.compile(r"a/r/b=(\d+)/(\d+)/(\d+)")           # "share OK ... (a/r/b=N/M/K)"
    _re_ar = re.compile(r"a/r=(\d+)/(\d+)")                     # "share REJECTED ... (a/r=N/M)"
    _re_diff = re.compile(r"difficulty set to ([\d.]+)", re.I)

    def _parse_stats(self, line: str) -> None:
        # The miner logs authoritative running totals on every share:
        #   "share OK job=… nonce=… (a/r/b=1/0/0)"
        #   "share REJECTED job=… nonce=… (a/r=0/1)"
        m = self._re_arb.search(line)
        if m:
            self.accepted, self.rejected, self.blocks = int(m.group(1)), int(m.group(2)), int(m.group(3))
        else:
            mt = self._re_totals.search(line)          # "totals: accepted=… rejected=… blocks=…"
            if mt:
                self.accepted, self.rejected, self.blocks = int(mt.group(1)), int(mt.group(2)), int(mt.group(3))
            else:
                mr = self._re_ar.search(line)
                if mr:
                    self.accepted, self.rejected = int(mr.group(1)), int(mr.group(2))
        d = self._re_diff.search(line)                 # live pool vardiff
        if d:
            val = float(d.group(1))
            self.difficulty = f"{int(val):,}" if val >= 1 else str(val)
        h = self._re_hash.search(line)
        if h:
            self.hashrate = f"{h.group(1)} {h.group(2)}"

    def _tick(self) -> None:
        # update stats bar
        self.stat_vals["difficulty"].config(text=self.difficulty)
        self.stat_vals["accepted"].config(text=str(self.accepted))
        self.stat_vals["rejected"].config(text=str(self.rejected))
        self.stat_vals["blocks"].config(text=str(self.blocks))
        if self.start_time and self.proc is not None:
            s = int(time.time() - self.start_time)
            self.stat_vals["uptime"].config(text=f"{s // 3600:02d}:{(s % 3600) // 60:02d}:{s % 60:02d}")
            # The pool ramps a fresh worker's difficulty over the first ~5 min;
            # shares are sparse until it settles. Show that instead of looking dead.
            if self.accepted == 0 and s < 420:
                self.lbl_state.config(text="● Mining · warming up (first shares ~5 min)…", fg=ACCENT)
            else:
                self.lbl_state.config(text="● Mining", fg=GREEN)
        self.root.after(1000, self._tick)

    # ── log helpers ────────────────────────────────────────────────────────────

    def _append(self, text: str, tag: str = "") -> None:
        self.log.config(state="normal")
        self.log.insert("end", text, tag)
        # cap log to ~1200 lines
        if int(self.log.index("end-1c").split(".")[0]) > 1200:
            self.log.delete("1.0", "200.0")
        self.log.see("end")
        self.log.config(state="disabled")

    # ── shutdown ───────────────────────────────────────────────────────────────

    def _on_close(self) -> None:
        if self.proc is not None:
            if not messagebox.askyesno("Quit", "Mining is running. Stop and quit?"):
                return
            self.stop()
        self._save_config()
        self.root.destroy()


def main() -> int:
    root = tk.Tk()
    MinerGUI(root)
    root.mainloop()
    return 0


if __name__ == "__main__":
    sys.exit(main())
