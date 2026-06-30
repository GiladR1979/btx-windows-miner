# The native Windows solver (`btx-gbt-solve.exe`)

This is the GPU proof-of-work solver — a CUDA build of BTX's MatMul PoW. Upstream
([dexbtx/minebtx](https://github.com/dexbtx/minebtx)) only ships Linux/macOS solver binaries; this
directory is the **native Windows port**.

## Files

| File | What |
|---|---|
| `btx-gbt-solve.cpp` | The solver entry point, with the Windows-compatibility fixes (untracked in upstream; dropped into `src/` of the BTX node before building). |
| `patches/windows-port.patch` | The build-system + flag changes applied to the BTX node's `CMakeLists.txt` (root + `src/`). |
| `build-windows.ps1` | One-shot reproducible build (fetches clang-cl + vcpkg, clones the node, patches, configures, builds, stages `..\bin`). |

## Why a port was needed (3 problems, 3 fixes)

The BTX node is a Bitcoin Core fork and had **never been built on Windows**. Three things blocked it:

1. **`__int128` is not in MSVC.** BTX's consensus difficulty math (`pow.cpp`'s aserti3-2d) and the
   shielded code use `__int128`, a GCC/Clang extension MSVC `cl.exe` doesn't have. → **Build the
   C/C++ with `clang-cl`** (LLVM's MSVC-compatible driver), which has `__int128` and links the
   MSVC-built vcpkg deps fine. `nvcc` keeps `cl.exe` as its CUDA *host* compiler (the `.cu` device
   code doesn't touch `__int128`). The node's CMake already anticipates clang-cl (it links
   `clang_rt.builtins` for the 128-bit helper symbols).

2. **MSVC flags leak into `nvcc`.** The node attaches `/utf-8 /Zc:* /sdl /W3 /wd*` to a shared
   interface target, so they reach the CUDA compile too — and `nvcc` treats a bare `/utf-8` as an
   input file and aborts (*"a single input file is required…"*). → `windows-port.patch` gates those
   switches to `$<COMPILE_LANGUAGE:CXX>` and forwards the essential ones to the CUDA host via
   `-Xcompiler`.

3. **Windows-isms in the solver + headers.**
   - `windows.h` `#define`s `STRICT`, which collides with the `ReorgProtectionProfile::STRICT`
     enumerator → the patch defines `NO_STRICT`.
   - The solver registered a `SIGUSR1` tip-preempt handler — Windows has no `SIGUSR1`. It's now
     `#ifdef`-guarded out on Windows and the daemon advertises `"preempt":false`, so the Python
     wrapper never sends the signal (it gates on that flag). Slices just run to completion instead.
   - POSIX `setenv`/`unsetenv` are shimmed onto `_putenv_s`.

## Correctness

Both backends are verified against the project's reference vector (post-block-125000 V2 nonce-seeded
path, `block_height=130000`): nonce 0 must produce
`matmul_digest = 7db2e9351c8c947293cb12d086ff03435730156265b67e3bce9dab1956074b14`.

```
backend=cpu   nonce64=0  digest=7db2e935…074b14   PASS
backend=cuda  nonce64=0  digest=7db2e935…074b14   PASS
```

And, end-to-end, the pool **accepted** the shares it produced (`a/r/b = 1/0/0`).

## Build

```powershell
# prerequisites: VS 2022 Build Tools (C++), CUDA Toolkit 12.x, Git
./build-windows.ps1                 # -CudaArch 86 (3090) by default; 89=40xx, 90=Blackwell
```

The script downloads a portable clang-cl and vcpkg into `solver/.build/` automatically. Output:
`..\bin\btx-gbt-solve.exe` plus its bundled `cudart64_*.dll` + MSVC runtime DLLs.
