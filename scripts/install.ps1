#Requires -Version 5.1
<#
.SYNOPSIS
  Install the CodeAtlas skill for one or more coding agents.

.DESCRIPTION
  Copies SKILL.md, scripts/, references/, and the README to the skill
  directories scanned by OpenCode, Claude Code, Codex, Cursor, and the
  universal ~/.agents location.

.PARAMETER Targets
  Parent skill directories. Each receives a code-atlas/ folder.

.PARAMETER Force
  Replace an existing code-atlas/ installation. Required when updating.

.PARAMETER Link
  Copy once to the canonical location (~/.agents/skills/code-atlas) and create
  junctions for the other targets. Cursor Cloud and some SSH setups do not
  follow links; use copies there.

.PARAMETER Canonical
  Override the canonical location used by -Link.

.EXAMPLE
  .\scripts\install.ps1 -Force

.EXAMPLE
  .\scripts\install.ps1 -Targets "$HOME\.claude\skills" -Force

.EXAMPLE
  .\scripts\install.ps1 -Link -Force
#>
[CmdletBinding()]
param(
    [string[]]$Targets,
    [switch]$Force,
    [switch]$Link,
    [string]$Canonical
)

$ErrorActionPreference = "Stop"

$skillRoot = Split-Path -Parent $PSScriptRoot
if (-not (Test-Path -LiteralPath (Join-Path $skillRoot "SKILL.md"))) {
    throw "SKILL.md not found in $skillRoot. Run this script from <skill>/scripts/."
}

if (-not $Targets -or $Targets.Count -eq 0) {
    $Targets = @(
        (Join-Path $HOME ".config\opencode\skills"),
        (Join-Path $HOME ".claude\skills"),
        (Join-Path $HOME ".codex\skills"),
        (Join-Path $HOME ".cursor\skills"),
        (Join-Path $HOME ".agents\skills")
    )
}
if (-not $Canonical) {
    $Canonical = Join-Path $HOME ".agents\skills\code-atlas"
}

$payload = @("SKILL.md", "README.md", "LICENSE", "scripts", "references", "assets")
$sourceFull = [IO.Path]::GetFullPath($skillRoot).TrimEnd('\', '/')

function Test-SamePath([string]$a, [string]$b) {
    $fa = [IO.Path]::GetFullPath($a).TrimEnd('\', '/')
    $fb = [IO.Path]::GetFullPath($b).TrimEnd('\', '/')
    return $fa.Equals($fb, [StringComparison]::OrdinalIgnoreCase)
}

function Remove-Existing([string]$path) {
    $item = Get-Item -LiteralPath $path -Force
    $isLink = [bool]($item.Attributes -band [IO.FileAttributes]::ReparsePoint)
    if ($isLink) {
        # Do not recurse through a junction/symlink: remove the link itself.
        & cmd /c rmdir "`"$path`"" | Out-Null
        if ($LASTEXITCODE -ne 0) { throw "Could not remove link: $path" }
    } else {
        Remove-Item -LiteralPath $path -Recurse -Force
    }
}

function Install-Payload([string]$dest) {
    if (Test-Path -LiteralPath $dest) {
        if (-not $Force) {
            Write-Host "  skip  $dest (exists; use -Force to replace)" -ForegroundColor Yellow
            return $false
        }
        Remove-Existing $dest
    }
    New-Item -ItemType Directory -Force -Path $dest | Out-Null
    foreach ($item in $payload) {
        $src = Join-Path $skillRoot $item
        if (Test-Path -LiteralPath $src) {
            Copy-Item -LiteralPath $src -Destination $dest -Recurse -Force
        }
    }
    # Never ship caches or generated indexes inside the skill.
    Get-ChildItem -LiteralPath $dest -Recurse -Directory -Force |
        Where-Object { $_.Name -in @("__pycache__", ".code-atlas") } |
        ForEach-Object { Remove-Item -LiteralPath $_.FullName -Recurse -Force }
    if (-not (Test-Path -LiteralPath (Join-Path $dest "scripts\atlas.py"))) {
        throw "Install incomplete: $dest\scripts\atlas.py missing"
    }
    Write-Host "  copy  $dest" -ForegroundColor Green
    return $true
}

function Install-Link([string]$dest, [string]$target) {
    if (Test-SamePath $dest $target) { return }
    if (Test-Path -LiteralPath $dest) {
        if (-not $Force) {
            Write-Host "  skip  $dest (exists; use -Force to replace)" -ForegroundColor Yellow
            return
        }
        Remove-Existing $dest
    }
    New-Item -ItemType Directory -Force -Path (Split-Path -Parent $dest) | Out-Null
    New-Item -ItemType Junction -Path $dest -Target $target | Out-Null
    Write-Host "  link  $dest -> $target" -ForegroundColor Green
}

$pyVersion = "not found"
try {
    $pyVersion = ((& python --version) 2>&1 | Out-String).Trim()
} catch { }

Write-Host "CodeAtlas installer" -ForegroundColor Cyan
Write-Host "  source: $sourceFull"
Write-Host "  python: $pyVersion"
Write-Host ""

if ($Link) {
    if ((Test-SamePath $sourceFull $Canonical)) {
        Write-Host "  keep  $Canonical (already the source)" -ForegroundColor Green
    } else {
        Install-Payload $Canonical | Out-Null
    }
    foreach ($parent in $Targets) {
        $dest = Join-Path $parent "code-atlas"
        Install-Link $dest $Canonical
    }
} else {
    foreach ($parent in $Targets) {
        $dest = Join-Path $parent "code-atlas"
        if ((Test-SamePath $sourceFull $dest)) {
            Write-Host "  keep  $dest (already the source)" -ForegroundColor Green
            continue
        }
        Install-Payload $dest | Out-Null
    }
}

Write-Host ""
Write-Host "Done. Restart your agent (or reload the window) to pick up the skill." -ForegroundColor Cyan
Write-Host "Verify with: python <skills-dir>\code-atlas\scripts\atlas.py --version"
