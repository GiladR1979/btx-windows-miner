<#
.SYNOPSIS
    Run the BTX native Windows miner from the command line (GUI-free).

.EXAMPLE
    ./run-miner.ps1 -Address btx1zYOURADDRESS -Worker my-rig

.NOTES
    Requires an NVIDIA driver and Python 3.10+. The CUDA + MSVC runtime DLLs are
    bundled in bin/ next to the solver, so no CUDA toolkit install is needed.
#>
param(
    [Parameter(Mandatory = $true)]
    [string]$Address,
    [string]$Worker = $env:COMPUTERNAME,
    [string]$Pool = "pool.minebtx.com:3333",
    [string]$Solver = "$PSScriptRoot\bin\btx-gbt-solve.exe",
    [int]$Threads = 8,
    [int]$PrepareWorkers = 16,
    [int]$BatchSize = 128,
    [int]$GpuInputs = 1
)

$ErrorActionPreference = "Stop"

if (-not (Test-Path $Solver)) {
    throw "Solver not found at $Solver. Build it (solver/build-windows.ps1) or pass -Solver <path>."
}

# Make the vendored stratum client importable without a pip install.
$env:PYTHONPATH = "$PSScriptRoot\miner;$env:PYTHONPATH"
# Bundled bin/ holds cudart + MSVC runtime next to the solver (found automatically),
# adding it to PATH too is harmless belt-and-suspenders.
$env:PATH = "$PSScriptRoot\bin;$env:PATH"
$env:PYTHONUNBUFFERED = "1"
# We ship our own native solver — never let the wrapper phone home to replace it
# or pip-upgrade itself (those update paths target Linux only).
$env:DEXBTX_NO_SOLVER_AUTOUPDATE = "1"
$env:DEXBTX_NO_WRAPPER_AUTOUPDATE = "1"
$env:DEXBTX_NO_SOLVER_RECHECK = "1"

Write-Host "Mining to $Address (worker '$Worker') via $Pool" -ForegroundColor Green
python -m dexbtx_miner `
    --pool $Pool `
    --address $Address `
    --worker $Worker `
    --gbt-solve $Solver `
    --threads $Threads `
    --prepare-workers $PrepareWorkers `
    --batch-size $BatchSize `
    --gpu-inputs $GpuInputs `
    --log-level INFO
