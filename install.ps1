param(
    [ValidateSet('Auto', 'CUDA', 'Vulkan', 'CPU')]
    [string]$Backend = 'Auto',
    [string]$PythonPath = '',
    [switch]$DependenciesOnly
)
$ErrorActionPreference = 'Stop'
$projectRoot = $PSScriptRoot
$venvPython = Join-Path $projectRoot '.venv\Scripts\python.exe'

function Assert-Python312([string]$Executable, [string[]]$PrefixArgs = @()) {
    try {
        & $Executable @PrefixArgs -c 'import sys,struct; sys.exit(not(sys.version_info[:2]==(3,12) and struct.calcsize(chr(80))==8))' 2>$null
        return ($LASTEXITCODE -eq 0)
    } catch {
        return $false
    }
}

try {
    if ([Environment]::OSVersion.Platform -ne 'Win32NT' -or -not [Environment]::Is64BitOperatingSystem) {
        throw 'Windows 10/11 x64 is required.'
    }
    if (-not (Test-Path -LiteralPath $venvPython)) {
        $selectedPython = $null
        $prefixArgs = @()
        if ($PythonPath) {
            if (-not (Assert-Python312 $PythonPath)) { throw '-PythonPath must point to Python 3.12 x64.' }
            $selectedPython = $PythonPath
        } else {
            $launcher = Get-Command py.exe -ErrorAction SilentlyContinue
            if ($launcher -and (Assert-Python312 $launcher.Source @('-3.12'))) {
                $selectedPython = $launcher.Source
                $prefixArgs = @('-3.12')
            } else {
                $candidate = Get-Command python.exe -ErrorAction SilentlyContinue
                if ($candidate -and $candidate.Source -notlike '*\WindowsApps\*' -and (Assert-Python312 $candidate.Source)) {
                    $selectedPython = $candidate.Source
                }
            }
        }
        if (-not $selectedPython) {
            throw 'Install Python 3.12 x64 from https://www.python.org/downloads/windows/ then retry. Or use: .\install.ps1 -PythonPath "C:\path\to\python.exe"'
        }
        Write-Host 'Creating a local Python environment...'
        & $selectedPython @prefixArgs -m venv (Join-Path $projectRoot '.venv')
        if ($LASTEXITCODE -ne 0) { throw 'Could not create .venv.' }
    }
    if (-not (Assert-Python312 $venvPython)) {
        throw 'Existing .venv is incompatible or was moved from another computer. Rename .venv and run setup again.'
    }
    $env:PIP_DISABLE_PIP_VERSION_CHECK = '1'
    $env:HF_HUB_DISABLE_IMPLICIT_TOKEN = '1'
    Write-Host 'Installing pinned dependencies into .venv...'
    & $venvPython -m pip install --only-binary=:all: -r (Join-Path $projectRoot 'requirements-lock.txt')
    if ($LASTEXITCODE -ne 0) { throw 'Dependency installation failed. Check your network, then run setup again.' }
    & $venvPython -c 'import tkinter, numpy, scipy, pyaudiowpatch, faster_whisper'
    if ($LASTEXITCODE -ne 0) { throw 'Dependency import check failed.' }
    Write-Host 'Python dependencies ready.'
    New-Item -ItemType Directory -Force -Path (Join-Path $projectRoot 'work') | Out-Null
    if ($DependenciesOnly) {
        Write-Host 'Dependencies ready. Run setup without -DependenciesOnly to download the models.'
        exit 0
    }
    $selectedBackend = $Backend
    if ($selectedBackend -eq 'Auto') {
        $adapters = @(Get-CimInstance Win32_VideoController -ErrorAction SilentlyContinue)
        $selectedBackend = 'Vulkan'
        if ($adapters.Name -match 'NVIDIA') { $selectedBackend = 'CUDA' }
    }
    Write-Host "Preparing models and runtime ($selectedBackend)... Initial download is about 6-7 GB."
    & $venvPython -u (Join-Path $projectRoot 'setup_runtime.py')
    if ($LASTEXITCODE -ne 0) { throw 'Model/runtime download incomplete. Run setup again to resume.' }
    if ($selectedBackend -eq 'CUDA') {
        & $venvPython -u (Join-Path $projectRoot 'setup_latency_runtime.py')
        if ($LASTEXITCODE -ne 0) { throw 'CUDA runtime download incomplete. Run setup again to resume, or choose -Backend Vulkan.' }
    }
    # Existing user settings are preserved, including edits to the glossary.
    & $venvPython (Join-Path $projectRoot 'release_setup.py') --backend $selectedBackend
    if ($LASTEXITCODE -ne 0) { throw 'Could not initialize settings.' }
    Write-Host 'ASMR Local Subtitles v1.0.0 is ready. Open the launcher EXE in this folder.' -ForegroundColor Green
} catch {
    Write-Host $_.Exception.Message -ForegroundColor Red
    exit 1
}
