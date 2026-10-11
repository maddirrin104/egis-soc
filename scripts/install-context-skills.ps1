# Run from a PowerShell terminal opened at the EGIS-SOC repository root.
# Review third-party skills before using them. No downloaded code is executed.
param([switch]$Force)
$ErrorActionPreference = 'Stop'
$root = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$target = Join-Path $root '.agents/skills'
$repo = 'https://github.com/muratcankoylan/Agent-Skills-for-Context-Engineering.git'
$selected = @('filesystem-context','memory-systems','context-compression',
              'context-optimization','multi-agent-patterns','harness-engineering',
              'evaluation','project-development')
$tmp = Join-Path ([System.IO.Path]::GetTempPath()) ('egis-context-skills-' + [Guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Path $tmp -Force | Out-Null
try {
  git clone --quiet --depth 1 $repo $tmp
  if ($LASTEXITCODE -ne 0) { throw 'Git clone failed' }
  $rev = (git -C $tmp rev-parse HEAD).Trim()
  New-Item -ItemType Directory -Path $target -Force | Out-Null
  foreach ($name in $selected) {
    $src = Join-Path $tmp "skills/$name"
    $dest = Join-Path $target $name
    if (!(Test-Path (Join-Path $src 'SKILL.md'))) { throw "Missing skill $name" }
    if (Test-Path $dest) {
      if (!$Force) { Write-Host "SKIP existing skill: $name (use -Force only after diff review)"; continue }
      Remove-Item -Path $dest -Recurse -Force
    }
    Copy-Item -Path $src -Destination $dest -Recurse
    Write-Host "Copied skill: $name"
  }
  Copy-Item -Path (Join-Path $tmp 'LICENSE') -Destination (Join-Path $target 'CONTEXT_ENGINEERING_UPSTREAM_LICENSE.txt') -Force
  $prov = Join-Path $root 'docs/context/SKILL_PROVENANCE.md'
  $date = (Get-Date).ToUniversalTime().ToString('o')
  Add-Content -Path $prov -Value "`n- $date | $repo | commit $rev | selected: $($selected -join ', ') | inspect scripts before execution"
  Write-Host "Pinned upstream version: $rev"
  Write-Host 'No upstream skill code was executed. Inspect copied SKILL.md files before enabling.'
}
finally { if (Test-Path $tmp) { Remove-Item -Path $tmp -Recurse -Force } }
