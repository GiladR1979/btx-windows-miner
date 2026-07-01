# BTX Windows Miner ⛏️ — native CUDA, no WSL

A **native Windows** miner for **BTX (BitcoinTX)** — the Bitcoin fork with a MatMul GPU
proof-of-work. It runs the GPU solver **directly on Windows** (MSVC + CUDA), with **no WSL2
layer**, and ships a simple GUI where you paste your wallet address and press **Start**.

> **Why native?** BTX's official miner only ships Linux/macOS solver binaries, so on Windows
> people run it under WSL2. WSL2's GPU‑passthrough (GPU‑PV) adds per‑dispatch latency that caps
> an RTX 3090 at roughly **half** of what the same card does on bare metal. This project ports
> the solver to native Windows to remove that ceiling — the GPU is driven directly, the way the
> fleet‑best Linux rigs do it.

![status](https://img.shields.io/badge/build-passing-brightgreen) ![platform](https://img.shields.io/badge/platform-Windows%2010%2F11%20x64-blue) ![gpu](https://img.shields.io/badge/GPU-NVIDIA%20CUDA-76b900) ![license](https://img.shields.io/badge/license-MIT-green)

---

## What's in the box

| Path | What it is |
|---|---|
| `gui/btx_miner_gui.py` | The GUI — **wallet address** field, worker/pool, GPU tuning, Start/Stop, live hashrate + accepted/rejected shares + log. |
| `bin/btx-gbt-solve.exe` | The **native Windows CUDA solver** (prebuilt). Ships with its CUDA + MSVC runtime DLLs — works with just an NVIDIA driver installed. |
| `miner/dexbtx_miner/` | The stratum pool client (vendored from [dexbtx/minebtx](https://github.com/dexbtx/minebtx), MIT). Drives the solver and talks to the pool. |
| `solver/` | Solver source + the `windows-port.patch` and `build-windows.ps1` if you want to **build the `.exe` yourself**. |
| `run-miner.ps1` | Command‑line launcher (alternative to the GUI). |
| `start-gui.bat` | Double‑click to launch the GUI. |

---

## Quick start

**Requirements**
- Windows 10/11 (x64)
- An **NVIDIA GPU** + a recent **NVIDIA driver** (that's all — the CUDA runtime is bundled)
- **Python 3.10+** ([python.org](https://www.python.org/downloads/) — tick *“Add to PATH”*). Only the
  standard library is used; no `pip install` needed.

**Run it**
1. Download / clone this repo.
2. Double‑click **`start-gui.bat`** (or run `python gui/btx_miner_gui.py`). *Optional:* run `install-desktop-shortcut.ps1` once to drop a **Desktop shortcut** (with icon) that launches the GUI.
3. Paste your **BTX wallet address** (`btx1z…`) into the **Wallet address** box.
4. Press **▶ Start Mining**.

That's it. The GUI spawns the miner, which connects to the pool, loads the native CUDA solver,
and starts hashing. Accepted/rejected shares and your hashrate show up in the status bar; find
your rig on the pool dashboard at `https://pool.minebtx.com/dashboard`.

> **Don't have a BTX address?** Get one from the BTX wallet / `btx-cli getnewaddress`, or follow
> the wallet quickstart at <https://minebtx.com>. Your **payout address** is all the miner needs
> (never your private key).

### Command line (no GUI)

```powershell
# edit the address, then:
./run-miner.ps1 -Address btx1zYOUR_ADDRESS -Worker my-rig
```

---

## GPU tuning

The defaults are the canonical profile and are fine for most NVIDIA cards (Pascal → Blackwell):

| Setting | Default | Notes |
|---|---|---|
| Solver threads | `8` | CPU solver workers. Slow cards (5060/3060/laptop): try `16`. |
| Prepare workers | `16` | CPU input generators. |
| Batch size | `128` | **Keep at 128.** 256+ degrades utilization; 1024 crashes the GPU pool. |
| GPU inputs | `1` | **Must be 1** (GPU‑generated matmul inputs — mandatory post‑block‑125000). |

Multi‑GPU: set *GPU inputs* equal to your GPU count.

---

## How it works

```
┌─────────────────────┐     JSON jobs (stdin)      ┌──────────────────────┐
│   dexbtx_miner       │ ─────────────────────────► │  btx-gbt-solve.exe   │
│  (stratum client,    │ ◄───────────────────────── │  (native CUDA MatMul │
│   Python)            │     JSON results (stdout)   │   PoW solver)        │
└─────────┬───────────┘                             └──────────┬───────────┘
          │ stratum (TCP)                                       │ CUDA
          ▼                                                     ▼
   pool.minebtx.com:3333                                   NVIDIA GPU
```

The Python client gets work from the pool, hands each slice to the long‑running solver daemon
over stdio, and submits the shares it finds. The solver is a CUDA build of BTX's MatMul
proof‑of‑work — the same algorithm the network validates, so shares are accepted exactly as the
Linux/macOS solvers' are.

**Correctness is verified against the project's reference vector** — both the CPU and CUDA
backends reproduce the canonical `matmul_digest`
(`7db2e935…074b14`) bit‑for‑bit (see `solver/`).

---

## Build the solver yourself (optional)

The prebuilt `bin/btx-gbt-solve.exe` is ready to use. To build it from source — the BTX node is a
Bitcoin Core fork, and the solver is a CMake target inside it — see
**[`solver/build-windows.ps1`](solver/build-windows.ps1)** and
**[`solver/README.md`](solver/README.md)**. In short:

- **Toolchain:** Visual Studio 2022 Build Tools (MSVC), CUDA Toolkit 12.x, `vcpkg`, CMake ≥ 3.28,
  and **clang‑cl** (LLVM) — clang‑cl is required because the BTX consensus code uses `__int128`,
  which MSVC `cl.exe` doesn't support. CUDA `.cu` files still compile with `nvcc`+`cl` as host.
- **The Windows port** (`solver/patches/windows-port.patch`) does three things the upstream
  Linux/macOS build never needed:
  1. Gates the MSVC‑only compile flags (`/utf-8 /Zc:* /sdl /W3 …`) to **C++ TUs only** and
     forwards the essential ones to the CUDA host via `-Xcompiler` (otherwise `nvcc` treats a bare
     `/utf-8` as an input file and aborts).
  2. Defines `NO_STRICT` so `windows.h` doesn't `#define STRICT` over the
     `ReorgProtectionProfile::STRICT` enumerator.
  3. Makes the solver itself Windows‑clean: `#ifdef`‑guards the `SIGUSR1` tip‑preempt (no such
     signal on Windows → advertises `preempt:false`), and shims POSIX `setenv`/`unsetenv` onto
     `_putenv_s`.

---

## Credits & license

- This project (GUI, build tooling, Windows port): **MIT** — see [`LICENSE`](LICENSE).
- `miner/dexbtx_miner/` is vendored from **[dexbtx/minebtx](https://github.com/dexbtx/minebtx)** (MIT) — see [`miner/LICENSE.dexbtx`](miner/LICENSE.dexbtx).
- The solver is built from the **BTX node** ([btxchain/btx](https://github.com/btxchain/btx), a Bitcoin Core fork, MIT). The CUDA MatMul‑PoW kernels are theirs.

## Disclaimer

Mining software provided as‑is, for use on hardware you own. It connects to a third‑party mining
pool and pays out to the BTX address you provide. Verify your address before mining. Cryptocurrency
mining stresses your GPU and uses electricity — you are responsible for your hardware, power costs,
and any local regulations.
