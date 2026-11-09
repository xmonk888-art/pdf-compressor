# PDF 高清压缩 · PDF Compressor

面向 Windows 的离线 PDF 批量压缩工具。适合处理展册、产品资料和扫描件，支持三档压缩模式、任务队列和失败重试。

An offline Windows utility for batch PDF compression. It offers three presets, a file queue, and retry controls for brochures, product documents, and scans.

![PDF 高清压缩 v2.4.1 的实际主窗口 / PDF Compressor v2.4.1 running on Windows](assets/main-window.jpg)

## 下载与安装 · Download and install

- 下载 [v2.4.1 安装包](https://github.com/xmonk888-art/pdf-compressor/releases/download/v2.4.1/PDFCompressor-2.4.1-Setup.exe)。本包为 Windows x64 安装包，自带运行环境，可离线安装和使用。
- 首次安装可选目录。升级前先完成任务并退出旧版，再运行安装包，沿用原目录。
- Download the [v2.4.1 installer](https://github.com/xmonk888-art/pdf-compressor/releases/download/v2.4.1/PDFCompressor-2.4.1-Setup.exe). It includes its runtime for Windows x64 and works offline.
- Choose an install folder on first use. To upgrade, finish any running jobs, close the app, and keep the existing installation folder.

## 快速上手 · Quick start

拖入 PDF 或文件夹，选好压缩模式和保存位置，再点击「开始」。默认把压缩件放入原文件旁的「压缩输出」文件夹。文件队列里可查看结果、打开保存位置、重试失败项和导出处理记录。

Drop PDF files or a folder into the app, choose a preset and output location, then select Start. By default, compressed copies go into the `压缩输出` folder beside the source files. The queue shows results and provides controls to open the output folder, retry failures, and export processing records.

## 源码与许可 · Source and license

本软件以 GNU AGPL v3 发布。对应的应用源码、PyMuPDF 和 MuPDF 源码可从 [v2.4.1 Release](https://github.com/xmonk888-art/pdf-compressor/releases/tag/v2.4.1) 下载。构建步骤见 [BUILD.md](BUILD.md)，许可和第三方声明见 [LICENSE](LICENSE) 与 [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md)。

The application is released under GNU AGPL v3. The corresponding application, PyMuPDF, and MuPDF sources are available from the [v2.4.1 release](https://github.com/xmonk888-art/pdf-compressor/releases/tag/v2.4.1). See [BUILD.md](BUILD.md) for build instructions and [LICENSE](LICENSE) and [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md) for licensing details.
