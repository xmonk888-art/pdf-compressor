# 构建 PDF 高清压缩 v2.4.1 · Build PDF Compressor v2.4.1

需要 Windows x64、Python 3.12 x64 和 Inno Setup 7。发行版使用 CPython 3.12.11、PyInstaller 6.22.3 和 Inno Setup 7.1.1 构建。安装用户可以直接使用发行安装包。

Use Windows x64, Python 3.12 x64, and Inno Setup 7. The release was built with CPython 3.12.11, PyInstaller 6.22.3, and Inno Setup 7.1.1. End users can run the release installer directly.

在仓库根目录运行以下 PowerShell 命令。将 `$compiler` 改成实际的 `ISCC.exe` 路径。

Run the following PowerShell commands from the repository root. Set `$compiler` to the path of your `ISCC.exe`.

```powershell
py -3.12 -m venv .venv
& .\.venv\Scripts\python.exe -m pip install -r requirements-build.txt -c constraints-build.txt
& .\.venv\Scripts\python.exe -m unittest test_engine test_drop
& .\.venv\Scripts\python.exe -m PyInstaller --noconfirm .\PDFCompressor.spec
Copy-Item -LiteralPath .\assets\app.ico -Destination '.\dist\折叠图标.ico'
$compiler = Read-Host 'Path to ISCC.exe'
& .\installer\build_installer.ps1 -Compiler $compiler -PayloadDirectory .\dist -OutputDirectory .\release
```

`dist/PDFCompressor` 是完整的运行目录。对外发行入口是 `release` 中的一键安装包。

`dist/PDFCompressor` is the full application directory. The distributable installer is in `release`.
