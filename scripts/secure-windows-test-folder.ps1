param(
  [Parameter(Mandatory=$true)]
  [string] $Path
)
$ErrorActionPreference = 'Stop'
$target = (Resolve-Path -LiteralPath $Path).Path
if (-not (Test-Path -LiteralPath $target -PathType Container)) { throw 'Private test root must be an existing directory' }
$me = [System.Security.Principal.WindowsIdentity]::GetCurrent().User
$acl = New-Object System.Security.AccessControl.DirectorySecurity
$acl.SetAccessRuleProtection($true, $false)
$rule = New-Object System.Security.AccessControl.FileSystemAccessRule(
  $me,
  [System.Security.AccessControl.FileSystemRights]::FullControl,
  ([System.Security.AccessControl.InheritanceFlags]::ContainerInherit -bor [System.Security.AccessControl.InheritanceFlags]::ObjectInherit),
  [System.Security.AccessControl.PropagationFlags]::None,
  [System.Security.AccessControl.AccessControlType]::Allow
)
$acl.AddAccessRule($rule)
$acl.SetOwner($me)
Set-Acl -LiteralPath $target -AclObject $acl
Write-Output "Windows ACL restricted to current user on $target"
