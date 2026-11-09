param([string]$OutputDirectory = (Join-Path $PSScriptRoot 'dist'), [string]$BuildDirectory = (Join-Path $PSScriptRoot '.build_unified'))
$ErrorActionPreference = 'Stop'
$taskPython = Join-Path $PSScriptRoot '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $taskPython)) { throw '请先创建 Python 3.12 虚拟环境并安装 requirements-build.txt。' }
Push-Location $PSScriptRoot
try {
    & $taskPython -m PyInstaller --noconfirm --onedir --windowed --name 'PDFCompressor' --icon 'assets\app.ico' --version-file 'version_info.txt' --add-data 'assets\app.ico;.' --add-data 'assets\monochrome.json;.' --collect-binaries pymupdf --collect-all customtkinter --distpath $OutputDirectory --workpath $BuildDirectory --exclude-module numpy --exclude-module matplotlib --exclude-module pandas --exclude-module scipy --exclude-module torch --exclude-module pytest --exclude-module IPython --exclude-module setuptools --exclude-module pip app.py
    if ($LASTEXITCODE -ne 0) { throw '打包失败' }
} finally { Pop-Location }
