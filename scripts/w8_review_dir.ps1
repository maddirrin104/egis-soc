param(
    [switch]$Create,
    [switch]$Check,
    [ValidatePattern('^review-w8-01(?:-[A-Za-z0-9]+)?$')][string]$Name = 'review-w8-01',
    [string]$Path
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
if ($Create -eq $Check) { throw 'choose_create_or_check' }
$base = [System.IO.Path]::GetFullPath((Join-Path $env:LOCALAPPDATA 'EGIS-SOC'))
$target = if ($Create) { Join-Path $base $Name } else { $Path }
if ([string]::IsNullOrWhiteSpace($target)) { throw 'review_path_required' }
$target = [System.IO.Path]::GetFullPath($target)
if (-not $target.StartsWith($base + [System.IO.Path]::DirectorySeparatorChar,
        [System.StringComparison]::OrdinalIgnoreCase)) { throw 'review_path_outside_private_root' }

if ($Create) {
    if (Test-Path -LiteralPath $target) { throw 'review_directory_exists' }
    New-Item -ItemType Directory -Path $base -Force | Out-Null
    New-Item -ItemType Directory -Path $target | Out-Null
    $acl = Get-Acl -LiteralPath $target
    $acl.SetAccessRuleProtection($true, $false)
    $inherit = [System.Security.AccessControl.InheritanceFlags]'ContainerInherit, ObjectInherit'
    $propagate = [System.Security.AccessControl.PropagationFlags]::None
    $allow = [System.Security.AccessControl.AccessControlType]::Allow
    foreach ($sidValue in @(([System.Security.Principal.WindowsIdentity]::GetCurrent().User.Value),
            'S-1-5-18', 'S-1-5-32-544')) {
        $sid = New-Object System.Security.Principal.SecurityIdentifier($sidValue)
        $rule = New-Object System.Security.AccessControl.FileSystemAccessRule(
            $sid, [System.Security.AccessControl.FileSystemRights]::FullControl,
            $inherit, $propagate, $allow)
        $acl.AddAccessRule($rule)
    }
    Set-Acl -LiteralPath $target -AclObject $acl
}

$item = Get-Item -LiteralPath $target
if (-not $item.PSIsContainer -or
        (($item.Attributes -band [System.IO.FileAttributes]::ReparsePoint) -ne 0)) {
    throw 'review_directory_not_regular'
}
$acl = Get-Acl -LiteralPath $target
$allowed = @(([System.Security.Principal.WindowsIdentity]::GetCurrent().User.Value),
    'S-1-5-18', 'S-1-5-32-544')
$actual = @($acl.Access | Where-Object { $_.AccessControlType -eq 'Allow' } |
    ForEach-Object { $_.IdentityReference.Translate(
        [System.Security.Principal.SecurityIdentifier]).Value })
if (-not $acl.AreAccessRulesProtected -or $actual.Count -ne 3 -or
        @($actual | Where-Object { $_ -notin $allowed }).Count -gt 0) {
    throw 'review_directory_acl_not_owner_restricted'
}
Write-Output $target
