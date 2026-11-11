param([Parameter(Mandatory=$true)][string]$Path)
$ErrorActionPreference = 'Stop'
$target = (Resolve-Path -LiteralPath $Path).ProviderPath
if (-not (Test-Path -LiteralPath $target -PathType Container)) {
  throw 'Private test root must be an existing directory'
}
$sid = [System.Security.Principal.WindowsIdentity]::GetCurrent().User.Value
& icacls.exe $target '/inheritance:r' | Out-Null
if ($LASTEXITCODE -ne 0) { throw 'Windows ACL inheritance removal failed' }
& icacls.exe $target '/grant:r' "*${sid}:(OI)(CI)F" | Out-Null
if ($LASTEXITCODE -ne 0) { throw 'Windows owner-only ACL grant failed' }
Write-Output "Private Windows test root restricted to $sid"
