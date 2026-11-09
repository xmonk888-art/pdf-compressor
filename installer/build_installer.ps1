param(
    [Parameter(Mandatory=$true)][string]$Compiler,
    [Parameter(Mandatory=$true)][string]$PayloadDirectory,
    [Parameter(Mandatory=$true)][string]$OutputDirectory
)
$ErrorActionPreference='Stop'
$taskPayload=(Resolve-Path -LiteralPath $PayloadDirectory).Path
New-Item -ItemType Directory -Force -Path $OutputDirectory | Out-Null
$taskOutput=(Resolve-Path -LiteralPath $OutputDirectory).Path
& $Compiler ('/DPayloadDir='+$taskPayload) ('/DDeliveryDir='+$taskOutput) (Join-Path $PSScriptRoot 'PDFCompressor.iss')
if($LASTEXITCODE -ne 0){throw '安装程序编译失败'}
