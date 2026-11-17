param(
    [Parameter(Mandatory = $true)][string]$Bundle,
    [Parameter(Mandatory = $true)][ValidatePattern('^[a-fA-F0-9]{64}$')][string]$ExpectedSha256,
    [string]$Distribution = 'Ubuntu-24.04',
    [string]$LinuxDestination = '',
    [ValidateRange(1024, 65535)][int]$Port = 38731,
    [switch]$InstallDependencies,
    [switch]$Activate
)
$ErrorActionPreference = 'Stop'
$bundlePath = (Resolve-Path -LiteralPath $Bundle).Path
if ((Get-FileHash -LiteralPath $bundlePath -Algorithm SHA256).Hash -ne $ExpectedSha256) { throw 'Bundle SHA256 does not match the sender receipt' }
$distributions = @(& wsl.exe --list --quiet | ForEach-Object { ("$_" -replace "`0", '').Trim() })
if ($LASTEXITCODE -ne 0 -or $distributions -notcontains $Distribution) { throw 'The named WSL distribution is not installed; see docs/WINDOWS.md' }
if ($InstallDependencies) {
    & wsl.exe --distribution $Distribution --user root --exec apt-get update
    if ($LASTEXITCODE -ne 0) { throw 'apt update failed' }
    & wsl.exe --distribution $Distribution --user root --exec env DEBIAN_FRONTEND=noninteractive apt-get install -y python3-venv python3-pip ffmpeg fonts-dejavu-core fonts-noto-cjk
    if ($LASTEXITCODE -ne 0) { throw 'System dependency installation failed' }
}
$installer = Join-Path $PSScriptRoot 'install_wsl.py'
$linuxBundle = (& wsl.exe --distribution $Distribution --exec wslpath -a -u $bundlePath | Out-String).Trim()
if ($LASTEXITCODE -ne 0 -or -not $linuxBundle) { throw 'Cannot resolve bundle path inside WSL' }
$linuxInstaller = (& wsl.exe --distribution $Distribution --exec wslpath -a -u $installer | Out-String).Trim()
if ($LASTEXITCODE -ne 0 -or -not $linuxInstaller) { throw 'Cannot resolve installer path inside WSL' }
$installArgs = @('--distribution', $Distribution, '--exec', 'python3', $linuxInstaller, '--bundle', $linuxBundle, '--port', "$Port")
if ($LinuxDestination) { $installArgs += @('--destination', $LinuxDestination) }
if ($Activate) { $installArgs += '--activate' }
& wsl.exe @installArgs
if ($LASTEXITCODE -ne 0) { throw 'Phone-lab deployment or isolated smoke test failed' }
