<#
.SYNOPSIS
Opt-in PowerShell cd hook for GitHub CLI account drift.

.DESCRIPTION
Dot-source this file from a PowerShell profile to make `cd` call the
repo-local GitHub account context probe after changing directories. It switches
`gh` only when the current repository remote maps to an already authenticated
account and no GH_TOKEN/GITHUB_TOKEN override is present.

This file does not edit any profile by itself.
#>

param(
    [string]$ProjectsRoot = (Join-Path $HOME "Projects"),
    [string]$PythonCommand = "python"
)

Set-StrictMode -Version Latest

$script:GitHubAccountCdHookProjectsRoot = $ProjectsRoot
$script:GitHubAccountCdHookPythonCommand = $PythonCommand
$script:GitHubAccountCdHookLastRepo = $null

function Invoke-GitHubAccountDirectorySwitch {
    param(
        [string]$Path = (Get-Location).Path,
        [switch]$Quiet
    )

    $repoRoot = git -C $Path rev-parse --show-toplevel 2>$null
    if (-not $repoRoot) {
        return $null
    }

    $repoRoot = [string]$repoRoot
    if ($script:GitHubAccountCdHookLastRepo -eq $repoRoot) {
        return $null
    }
    $script:GitHubAccountCdHookLastRepo = $repoRoot

    $scriptPath = Join-Path $script:GitHubAccountCdHookProjectsRoot "shared\scripts\github_account_context.py"
    if (-not (Test-Path -LiteralPath $scriptPath)) {
        if (-not $Quiet) {
            Write-Warning "GitHub account hook script not found: $scriptPath"
        }
        return $null
    }

    $raw = & $script:GitHubAccountCdHookPythonCommand $scriptPath --repo $repoRoot --switch-if-needed --json 2>$null
    if (-not $raw) {
        return $null
    }

    $result = $raw | ConvertFrom-Json
    $attempt = $result.switch_attempt
    if (-not $attempt) {
        return $result
    }

    if (-not $Quiet) {
        if ($attempt.status -eq "switched") {
            Write-Host "[gh] active account switched to $($attempt.user) for $($result.remote_repo)"
        } elseif ($attempt.status -eq "blocked" -or $attempt.status -eq "error") {
            Write-Warning "[gh] account switch $($attempt.status): $($attempt.reason)"
        }
    }

    return $result
}

function Set-GitHubAccountLocation {
    [CmdletBinding(DefaultParameterSetName = "Path")]
    param(
        [Parameter(Position = 0, ParameterSetName = "Path", ValueFromPipeline = $true, ValueFromPipelineByPropertyName = $true)]
        [string]$Path,
        [Parameter(ParameterSetName = "LiteralPath", ValueFromPipelineByPropertyName = $true)]
        [string]$LiteralPath,
        [Parameter(ParameterSetName = "Stack")]
        [string]$StackName,
        [switch]$PassThru
    )

    if ($PSCmdlet.ParameterSetName -eq "LiteralPath") {
        Microsoft.PowerShell.Management\Set-Location -LiteralPath $LiteralPath -PassThru:$PassThru
    } elseif ($PSCmdlet.ParameterSetName -eq "Stack") {
        Microsoft.PowerShell.Management\Set-Location -StackName $StackName -PassThru:$PassThru
    } elseif ($PSBoundParameters.ContainsKey("Path")) {
        Microsoft.PowerShell.Management\Set-Location -Path $Path -PassThru:$PassThru
    } else {
        Microsoft.PowerShell.Management\Set-Location -PassThru:$PassThru
    }

    Invoke-GitHubAccountDirectorySwitch -Quiet | Out-Null
}

Set-Alias -Name cd -Value Set-GitHubAccountLocation -Option AllScope -Scope Global -Force
