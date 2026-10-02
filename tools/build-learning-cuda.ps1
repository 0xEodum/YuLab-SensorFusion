param([switch]$AllowUnsupportedCudaCompiler)
$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
$nvcc = (Get-Command nvcc -ErrorAction Stop).Source
$vswhere = Join-Path ${env:ProgramFiles(x86)} 'Microsoft Visual Studio/Installer/vswhere.exe'
$installation = & $vswhere -latest -products '*' -requires Microsoft.VisualStudio.Component.VC.Tools.x86.x64 -property installationPath
if (-not $installation) { throw 'MSVC x64 tools are required' }
$vcvars = Join-Path $installation 'VC/Auxiliary/Build/vcvars64.bat'
$output = Join-Path $root 'artifacts/sf11/cuda'
New-Item -ItemType Directory -Force -Path $output | Out-Null
$source = Join-Path $root 'backend/learning/cuda/matching.cu'
$dll = Join-Path $output 'learning_matching.dll'
$override = if ($AllowUnsupportedCudaCompiler) { '-allow-unsupported-compiler' } else { '' }
# Fixed workspace source/output; cmd is used only to activate the MSVC compiler.
$command = @"
@echo off
set "PATH=$(Split-Path -Parent $vswhere);%PATH%"
call "$vcvars"
if errorlevel 1 exit /b 1
"$nvcc" -shared -O3 -arch=sm_86 $override "$source" -o "$dll"
exit /b %errorlevel%
"@
$build = Join-Path $output 'build.cmd'
Set-Content -LiteralPath $build -Value $command -Encoding ascii
Push-Location $output
try {
    & cmd.exe /d /c $build
    if ($LASTEXITCODE -ne 0) { throw "CUDA matcher compilation failed ($LASTEXITCODE)" }
    Get-FileHash -LiteralPath $source,$dll -Algorithm SHA256
    @{
        source_sha256 = (Get-FileHash -LiteralPath $source -Algorithm SHA256).Hash.ToLowerInvariant()
        library_sha256 = (Get-FileHash -LiteralPath $dll -Algorithm SHA256).Hash.ToLowerInvariant()
        architecture = 'sm_86'
        nvcc_version = (& $nvcc --version | Out-String).Trim()
        compiler_override = [bool]$AllowUnsupportedCudaCompiler
    } | ConvertTo-Json | Set-Content -LiteralPath ([IO.Path]::ChangeExtension($dll, '.json')) -Encoding utf8
} finally { Pop-Location }
