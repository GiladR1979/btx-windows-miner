<#
.SYNOPSIS
    Build btx-gbt-solve.exe — the native Windows CUDA MatMul-PoW solver — from source.

.DESCRIPTION
    The BTX node is a Bitcoin Core fork; the solver is a CMake target inside it. This
    script reproduces the native-Windows build:

      1. clones btxchain/btx at the pinned tag
      2. drops in btx-gbt-solve.cpp (the solver, with Windows fixes) + applies windows-port.patch
      3. fetches a portable clang-cl (LLVM) and bootstraps vcpkg if needed
      4. configures with clang-cl (C/C++) + nvcc/cl (CUDA) and builds
      5. copies the .exe and its runtime DLLs into ..\bin

    clang-cl is REQUIRED: BTX's consensus code uses __int128, which MSVC cl.exe lacks.
    clang-cl is MSVC-ABI compatible, so it links the MSVC-built vcpkg deps fine, while
    nvcc keeps cl.exe as its CUDA host compiler.

.PREREQUISITES (install these yourself first)
    * Visual Studio 2022 Build Tools  — "Desktop development with C++" workload (MSVC + Windows SDK)
    * NVIDIA CUDA Toolkit 12.x         — provides nvcc (sets %CUDA_PATH%)
    * Git, and CMake >= 3.28 (the script can use a pip `cmake` if the system one is older)

.EXAMPLE
    ./build-windows.ps1
#>
param(
    [string]$BtxTag = "v0.32.12",                          # BTX node tag the solver source matches
    [string]$WorkDir = "$PSScriptRoot\.build",             # scratch clone/build root
    [int]$CudaArch = 86,                                   # 86 = Ampere (3090/30xx). 89=40xx, 90=Blackwell.
    [int]$Jobs = 12
)
$ErrorActionPreference = "Stop"
function Step($m) { Write-Host "`n=== $m ===" -ForegroundColor Cyan }

New-Item -ItemType Directory -Force $WorkDir | Out-Null
$src   = "$WorkDir\btx-src"
$build = "$WorkDir\build"
$llvm  = "$WorkDir\llvm"
$vcpkg = "$WorkDir\vcpkg"

# --- locate the VS Build Tools dev shell -----------------------------------------
Step "Locating Visual Studio Build Tools"
$vswhere = "${env:ProgramFiles(x86)}\Microsoft Visual Studio\Installer\vswhere.exe"
$vsPath = & $vswhere -latest -products * -requires Microsoft.VisualStudio.Component.VC.Tools.x86.x64 -property installationPath
if (-not $vsPath) { throw "VS 2022 Build Tools with the C++ workload not found." }
Write-Host "VS: $vsPath"
if (-not $env:CUDA_PATH) { throw "CUDA Toolkit not found (%CUDA_PATH% unset). Install CUDA 12.x." }
Write-Host "CUDA: $env:CUDA_PATH"

# --- portable clang-cl (LLVM) ----------------------------------------------------
Step "Ensuring clang-cl (LLVM)"
$clangcl = "$llvm\bin\clang-cl.exe"
if (-not (Test-Path $clangcl)) {
    $rel = Invoke-RestMethod "https://api.github.com/repos/llvm/llvm-project/releases/latest" -Headers @{'User-Agent'='ps'}
    $asset = $rel.assets | Where-Object { $_.name -match 'clang\+llvm-.*-x86_64-pc-windows-msvc\.tar\.xz$' } | Select-Object -First 1
    if (-not $asset) { throw "No portable LLVM windows-msvc archive in the latest release." }
    New-Item -ItemType Directory -Force $llvm | Out-Null
    Write-Host "Downloading $($asset.name) (~800 MB)..."
    curl.exe -L --fail -o "$WorkDir\llvm.tar.xz" $asset.browser_download_url
    tar -xf "$WorkDir\llvm.tar.xz" -C $llvm --strip-components=1
}
Write-Host "clang-cl: $(& $clangcl --version | Select-Object -First 1)"

# --- vcpkg -----------------------------------------------------------------------
Step "Ensuring vcpkg"
if (-not (Test-Path "$vcpkg\vcpkg.exe")) {
    git clone https://github.com/microsoft/vcpkg $vcpkg
    & "$vcpkg\bootstrap-vcpkg.bat" -disableMetrics
}

# --- BTX source + Windows port ---------------------------------------------------
Step "Cloning BTX source @ $BtxTag"
if (-not (Test-Path $src)) {
    git clone --depth 1 --branch $BtxTag https://github.com/btxchain/btx $src
}
Copy-Item "$PSScriptRoot\btx-gbt-solve.cpp" "$src\src\btx-gbt-solve.cpp" -Force
Step "Applying windows-port.patch"
Push-Location $src
git apply --reject --whitespace=nowarn "$PSScriptRoot\patches\windows-port.patch"
Pop-Location

# --- enter the MSVC dev environment ----------------------------------------------
Step "Entering VS dev shell"
& "$vsPath\Common7\Tools\Launch-VsDevShell.ps1" -Arch amd64 -HostArch amd64 -SkipAutomaticLocation *> $null
$env:VCPKG_ROOT = $vcpkg
$nvcc = ($env:CUDA_PATH + "\bin\nvcc.exe") -replace '\\','/'
$cl   = ((Get-Command cl.exe).Source) -replace '\\','/'
$cc   = $clangcl -replace '\\','/'

# pick a CMake >= 3.28 (older CMake mis-handles CUDA flags on Windows/Ninja)
$cmake = (Get-Command cmake -ErrorAction SilentlyContinue).Source
$ver = if ($cmake) { [version]((& $cmake --version | Select-Object -First 1) -replace '[^\d.]') } else { [version]"0.0" }
if ($ver -lt [version]"3.28") {
    Write-Host "System CMake $ver too old; installing a recent cmake via pip..."
    py -m pip install --user "cmake>=3.28,<4" | Out-Null
    $cmake = py -c "import cmake,os;print(os.path.join(os.path.dirname(cmake.__file__),'data','bin','cmake.exe'))"
}

# --- configure + build -----------------------------------------------------------
Step "Configuring (clang-cl C/C++, nvcc+cl CUDA)"
& $cmake -S ($src -replace '\\','/') -B ($build -replace '\\','/') -G Ninja `
    -DCMAKE_BUILD_TYPE=Release `
    -DCMAKE_C_COMPILER="$cc" -DCMAKE_CXX_COMPILER="$cc" `
    -DCMAKE_TOOLCHAIN_FILE="$($vcpkg -replace '\\','/')/scripts/buildsystems/vcpkg.cmake" `
    -DVCPKG_TARGET_TRIPLET=x64-windows -DVCPKG_MANIFEST_NO_DEFAULT_FEATURES=ON `
    -DBTX_ENABLE_CUDA_EXPERIMENTAL=ON -DBTX_CUDA_ARCHITECTURES=$CudaArch `
    -DCMAKE_CUDA_COMPILER="$nvcc" -DCMAKE_CUDA_HOST_COMPILER="$cl" `
    -DCMAKE_CUDA_FLAGS="-allow-unsupported-compiler" `
    -DBUILD_GUI=OFF -DBUILD_TESTS=OFF -DBUILD_BENCH=OFF -DBUILD_FUZZ_BINARY=OFF -DBUILD_UTIL=ON -DENABLE_WALLET=OFF
if ($LASTEXITCODE) { throw "configure failed" }

Step "Building btx-gbt-solve"
& $cmake --build ($build -replace '\\','/') --target btx-gbt-solve -j $Jobs
if ($LASTEXITCODE) { throw "build failed" }

# --- stage outputs ---------------------------------------------------------------
Step "Staging bin/"
$bin = "$PSScriptRoot\..\bin"
New-Item -ItemType Directory -Force $bin | Out-Null
Copy-Item "$build\bin\btx-gbt-solve.exe" $bin -Force
Copy-Item (Get-ChildItem "$env:CUDA_PATH\bin\cudart64_*.dll" | Select-Object -First 1).FullName $bin -Force
foreach ($d in "MSVCP140.dll","VCRUNTIME140.dll","VCRUNTIME140_1.dll") { Copy-Item "C:\Windows\System32\$d" $bin -Force }
Write-Host "`nDONE -> $bin\btx-gbt-solve.exe" -ForegroundColor Green
