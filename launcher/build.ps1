$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
$compiler = Join-Path $env:WINDIR 'Microsoft.NET\Framework64\v4.0.30319\csc.exe'
$source = Join-Path $PSScriptRoot 'Launcher.cs'
$bootstrap = Join-Path $PSScriptRoot 'IconBuilder.exe'
$icon = Join-Path $PSScriptRoot 'ASMR.ico'
$output = Join-Path $projectRoot 'ASMR本地字幕.exe'
$references = @('/reference:System.Windows.Forms.dll', '/reference:System.Drawing.dll')
& $compiler /nologo /target:winexe /optimize+ $references "/out:$bootstrap" $source
if ($LASTEXITCODE -ne 0) { throw 'Icon builder compilation failed.' }
$builder = Start-Process -FilePath $bootstrap -ArgumentList @('--make-icon', ('"' + $icon + '"')) -WindowStyle Hidden -PassThru -Wait
if ($builder.ExitCode -ne 0) { throw 'Icon creation failed.' }
& $compiler /nologo /target:winexe /optimize+ $references "/win32icon:$icon" "/out:$output" $source
if ($LASTEXITCODE -ne 0) { throw 'Launcher compilation failed.' }
Write-Output $output
