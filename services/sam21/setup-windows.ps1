$ErrorActionPreference = "Stop"

$ServiceRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$VenvPath = Join-Path $ServiceRoot ".venv"
$ModelPath = Join-Path $ServiceRoot "models\sam2.1_hiera_tiny.pt"

$BootstrapPython = $env:SAM21_PYTHON
if (-not $BootstrapPython) {
    $PythonCommand = Get-Command python.exe -ErrorAction SilentlyContinue
    if ($PythonCommand) {
        $BootstrapPython = $PythonCommand.Source
    }
}

if (-not $BootstrapPython -or -not (Test-Path $BootstrapPython)) {
    throw "Chua tim thay Python. Hay cai Python 3.11 roi chay lai."
}

if (-not (Get-Command ffmpeg -ErrorAction SilentlyContinue)) {
    throw "Chua tim thay FFmpeg trong PATH. Cai FFmpeg roi chay lai."
}

if (-not (Test-Path $VenvPath)) {
    & $BootstrapPython -m venv $VenvPath
}

$Python = Join-Path $VenvPath "Scripts\python.exe"
& $Python -m pip install --upgrade pip
& $Python -m pip install torch==2.7.1 torchvision==0.22.1 --index-url https://download.pytorch.org/whl/cpu
& $Python -m pip install -r (Join-Path $ServiceRoot "requirements.txt")
& $Python -m pip install "git+https://github.com/facebookresearch/sam2.git"

New-Item -ItemType Directory -Force -Path (Split-Path -Parent $ModelPath) | Out-Null
if (-not (Test-Path $ModelPath)) {
    Invoke-WebRequest `
        -Uri "https://dl.fbaipublicfiles.com/segment_anything_2/092824/sam2.1_hiera_tiny.pt" `
        -OutFile $ModelPath
}

Write-Host "Da cai xong SAM 2.1 Tiny. Chay .\start-windows.ps1 de khoi dong."
