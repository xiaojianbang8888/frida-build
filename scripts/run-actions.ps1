[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [ValidatePattern('^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$')]
    [string]$Repository,
    [ValidateSet('all', 'windows', 'macos', 'android', 'ios', 'linux')]
    [string]$Platform = 'all',
    [ValidateSet('upstream', 'xjb')]
    [string]$Profile = 'upstream',
    [ValidateSet('all', 'macos-x86_64', 'macos-arm64', 'ios-arm64', 'ios-arm64e')]
    [string]$AppleTarget = 'all',
    [string]$Branch
)

$ErrorActionPreference = 'Stop'
$fridaRoot = Split-Path -Parent $PSScriptRoot
$fridaGhCommand = Get-Command gh -ErrorAction SilentlyContinue
$fridaGh = if ($fridaGhCommand) { $fridaGhCommand.Source } else {
    Join-Path $fridaRoot 'work\tools\gh\bin\gh.exe'
}
if (-not (Test-Path -LiteralPath $fridaGh)) {
    throw 'Install GitHub CLI before running this script: https://cli.github.com/'
}

function Invoke-FridaGh {
    param([string[]]$Arguments)
    $fridaResult = & $fridaGh @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw "GitHub CLI command failed (exit $LASTEXITCODE)."
    }
    return $fridaResult
}

Invoke-FridaGh -Arguments @('auth', 'status', '--hostname', 'github.com') | Out-Host
if (-not $Branch) {
    $Branch = (Invoke-FridaGh -Arguments @(
        'repo', 'view', $Repository, '--json', 'defaultBranchRef',
        '--jq', '.defaultBranchRef.name'
    ) | Out-String).Trim()
}
if (-not $Branch) {
    throw 'The repository has no default branch. Upload the build files first.'
}

Invoke-FridaGh -Arguments @(
    'workflow', 'view', 'build.yml', '--repo', $Repository
) | Out-Host
$fridaRequestId = [Guid]::NewGuid().ToString('N')
$fridaRunTitle = "Frida $Profile $Platform / $fridaRequestId"
Invoke-FridaGh -Arguments @(
    'workflow', 'run', 'build.yml', '--repo', $Repository,
    '--ref', $Branch, '-f', "platform=$Platform", '-f', "profile=$Profile", '-f', "apple_target=$AppleTarget",
    '-f', "request_id=$fridaRequestId"
) | Out-Host

$fridaRun = $null
for ($fridaAttempt = 0; $fridaAttempt -lt 12; $fridaAttempt++) {
    $fridaRunsJson = Invoke-FridaGh -Arguments @(
        'run', 'list', '--repo', $Repository, '--workflow', 'build.yml',
        '--branch', $Branch, '--event', 'workflow_dispatch',
        '--json', 'databaseId,url,displayTitle', '--limit', '20'
    ) | Out-String
    $fridaRun = @($fridaRunsJson | ConvertFrom-Json) |
        Where-Object { $_.displayTitle -eq $fridaRunTitle } |
        Select-Object -First 1
    if ($fridaRun) { break }
    Start-Sleep -Seconds 5
}
if (-not $fridaRun) {
    throw "Workflow dispatched, but its run ID was not found. Check https://github.com/$Repository/actions"
}

Write-Output "Workflow: $($fridaRun.url)"
& $fridaGh run watch $fridaRun.databaseId --repo $Repository --exit-status --interval 20
$fridaWatchExit = $LASTEXITCODE
$fridaOutput = Join-Path $fridaRoot "dist\actions\$($fridaRun.databaseId)"
New-Item -ItemType Directory -Path $fridaOutput -Force | Out-Null
& $fridaGh run download $fridaRun.databaseId --repo $Repository --dir $fridaOutput
$fridaDownloadExit = $LASTEXITCODE
if ($fridaWatchExit -ne 0) {
    & $fridaGh run view $fridaRun.databaseId --repo $Repository --log-failed
    throw "Build failed. Available artifacts/logs: $fridaOutput"
}
if ($fridaDownloadExit -ne 0) {
    throw "Build completed, but artifact download failed. Run: $($fridaRun.url)"
}
Write-Output "Build succeeded. Artifacts: $fridaOutput"
