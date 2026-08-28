<#
.SYNOPSIS
    Unattended ("AFK") runner for the deterministic-input-layer effort's 13 implementation tickets
    (.scratch/deterministic-input-layer/impl/01..13-*.md).

.DESCRIPTION
    Drives one `claude -p` invocation per ticket, in an order that respects every ticket's
    "Blocked by:" line (see DEPENDENCY ORDER below), on a dedicated git branch. Each ticket
    gets its own log file and its own commit(s); the script never pushes and never touches
    origin.

    Stops the ENTIRE run immediately if a ticket's log shows a usage/rate limit was hit
    (checked before ContinueOnError) — that ticket is left unmarked so re-running the script
    resumes it once the limit clears.

    Safe to leave running unattended for hours. Re-running the script SKIPS any ticket that
    already has a `.done` marker in the log directory, so a killed/interrupted run resumes
    where it left off (delete the marker, or pass -Tickets, to force a re-run of one ticket).

    Ticket 10 (Workload Identity Federation) touches live GCP IAM / GitHub environment secrets.
    Its prompt explicitly forbids executing real provisioning commands - it only produces
    config/docs and a MANUAL_STEPS note - so it is safe to leave in the default sequence.

.PARAMETER Tickets
    Comma-separated ticket numbers to run, e.g. "01,02,03". Default: the full 13-ticket
    dependency-respecting sequence.

.PARAMETER Branch
    Git branch to create/reuse for the run. Default: afk/deterministic-input-layer-<yyyyMMdd>.

.PARAMETER ContinueOnError
    Keep going to the next ticket if one fails/times out (a real usage-limit hit still stops
    the whole run regardless of this flag). Default: stop the run on any failure.

.PARAMETER TimeoutMinutes
    Hard wall-clock cap per ticket. Default: 180 (3h). A ticket that exceeds this is killed and
    marked TIMEOUT.

.PARAMETER Model
    Model passed to claude via --model. Default: claude-opus-4-8.

.PARAMETER Effort
    Reasoning effort passed to claude via --effort. Default: medium.

.PARAMETER SkipPermissions
    Pass the unattended-permissions flag through to claude so it doesn't stop and wait for an
    interactive approval prompt. Default: on (this script exists specifically for AFK use;
    pass -SkipPermissions:$false to fall back to claude's normal per-action prompting, which
    will stall an unattended run the first time it needs approval).

.PARAMETER DryRun
    Print the plan (order, branch, prompts) and exit without invoking claude or touching git.

.EXAMPLE
    powershell -File run_afk.ps1
    Runs all 13 tickets in dependency order, unattended, on Opus 4.8 / medium effort.

.EXAMPLE
    powershell -File run_afk.ps1 -Tickets "12,13" -ContinueOnError
    Re-runs just tickets 12 and 13, continuing past a failure instead of stopping the run.
#>
param(
    [string]$Tickets,
    [string]$Branch,
    [switch]$ContinueOnError,
    [int]$TimeoutMinutes = 180,
    [string]$Model = 'claude-opus-4-8',
    [string]$Effort = 'medium',
    [bool]$SkipPermissions = $true,
    [switch]$DryRun
)

$ErrorActionPreference = 'Stop'

$RepoRoot   = 'D:\AI_tutor\wini_tabletop'
$ImplDir    = Join-Path $RepoRoot '.scratch\deterministic-input-layer\impl'
$LogDir     = Join-Path $ImplDir 'afk_logs'
$RunLog     = Join-Path $LogDir 'run_summary.log'

# Patterns that mean "we hit a usage/rate limit" - checked in every ticket's log regardless
# of that ticket's own exit code. Case-insensitive.
$LimitPatterns = @('usage limit', 'rate limit', 'rate-limited', 'quota exceeded', '\b429\b', 'weekly limit', '5-hour limit')

# ---- DEPENDENCY ORDER --------------------------------------------------------------------
# Computed from every ticket's "Blocked by:" line (checked 2026-08-27). Each entry appears
# after all of its blockers. 00 is the read-first map, not an implementable ticket - every
# per-ticket prompt below reads it for context, but it is never run on its own.
#   01 -> none                 02 -> 01        03 -> 01        04 -> 01
#   05 -> 01                   06 -> 01,05     07 -> 01,03     08 -> 01
#   09 -> 01                   10 -> none      11 -> 02,03,04,05,06,07
#   12 -> 05,09,10,11          13 -> 09,10,12
$Order = @(
    @{ Num = '01'; File = '01-contract-freeze-and-walking-skeleton.md';    Title = 'contract freeze + walking skeleton' }
    @{ Num = '10'; File = '10-workload-identity-federation.md';            Title = 'WIF for billed CI (config/docs only)'; Infra = $true }
    @{ Num = '02'; File = '02-legibility-and-normalization-fidelity.md';   Title = 'legibility + normalization fidelity' }
    @{ Num = '03'; File = '03-problem-detection.md';                      Title = 'problem detection' }
    @{ Num = '04'; File = '04-reference-and-drift-guard-removal.md';      Title = 'reference/anaphora + drift-guard removal' }
    @{ Num = '05'; File = '05-authorization-doubt-and-repair.md';         Title = 'authorization + doubt + repair' }
    @{ Num = '08'; File = '08-stt-capture-contract-doc.md';               Title = 'STT capture contract doc' }
    @{ Num = '09'; File = '09-blind-corpora.md';                         Title = 'blind corpora (safety + PII)' }
    @{ Num = '06'; File = '06-maths-grammar.md';                         Title = 'maths grammar' }
    @{ Num = '07'; File = '07-perception-schema-and-inline-rewire.md';    Title = 'perception schema + inline rewire' }
    @{ Num = '11'; File = '11-legacy-deletion-convergence.md';           Title = 'legacy deletion (convergence)' }
    @{ Num = '12'; File = '12-child-safety-stage-2.md';                  Title = 'child_safety/ Stage 2'; Billed = $true }
    @{ Num = '13'; File = '13-personal-data-stage-3.md';                 Title = 'personal_data/ Stage 3'; Billed = $true }
)

if ($Tickets) {
    $want = $Tickets -split ',' | ForEach-Object { $_.Trim().PadLeft(2, '0') }
    $Order = $Order | Where-Object { $want -contains $_.Num }
    if (-not $Order) { throw "No matching tickets for -Tickets '$Tickets'" }
}

if (-not $Branch) { $Branch = "afk/deterministic-input-layer-$(Get-Date -Format yyyyMMdd)" }

New-Item -ItemType Directory -Force -Path $LogDir | Out-Null

function Write-Log([string]$msg) {
    $line = "[$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')] $msg"
    Write-Host $line
    Add-Content -Path $RunLog -Value $line
}

function Test-LimitHit([string]$logFile) {
    if (-not (Test-Path $logFile)) { return $false }
    $text = Get-Content -Raw $logFile -ErrorAction SilentlyContinue
    if (-not $text) { return $false }
    foreach ($p in $LimitPatterns) {
        if ($text -imatch $p) { return $true }
    }
    return $false
}

function Build-Prompt($ticket) {
    $ticketPath = Join-Path $ImplDir $ticket.File
    return "/implement $ticketPath"
}

# ---- Plan / dry run -----------------------------------------------------------------------
Write-Host "Branch:  $Branch"
Write-Host "Tickets: $(($Order | ForEach-Object { $_.Num }) -join ', ')"
Write-Host "Logs:    $LogDir"
Write-Host "Model:   $Model (effort: $Effort)"
Write-Host "Timeout: $TimeoutMinutes min/ticket; ContinueOnError=$ContinueOnError; SkipPermissions=$SkipPermissions"

if ($DryRun) {
    foreach ($t in $Order) {
        Write-Host "`n===== ticket $($t.Num): $($t.Title) ====="
        Write-Host (Build-Prompt $t)
    }
    return
}

# ---- Git setup ------------------------------------------------------------------------------
Set-Location $RepoRoot
$dirty = git status --porcelain
if ($dirty) {
    Write-Log "WARNING: working tree is not clean before starting. Proceeding on branch '$Branch' anyway; review 'git status' if this run's diff looks wrong."
}

$existingBranch = git branch --list $Branch
if ($existingBranch) {
    Write-Log "Branch '$Branch' already exists - reusing it (resume mode)."
    git checkout $Branch | Out-Null
} else {
    Write-Log "Creating branch '$Branch' from current HEAD."
    git checkout -b $Branch | Out-Null
}

# ---- Main loop ------------------------------------------------------------------------------
$results = @()
$claudeArgs = @('-p', '--model', $Model, '--effort', $Effort)
if ($SkipPermissions) { $claudeArgs += '--dangerously-skip-permissions' }

foreach ($t in $Order) {
    $doneMarker = Join-Path $LogDir "$($t.Num).done"
    $logFile    = Join-Path $LogDir "$($t.Num).log"

    if (Test-Path $doneMarker) {
        Write-Log "Ticket $($t.Num) already marked done - skipping (delete $doneMarker to force a re-run)."
        $results += [pscustomobject]@{ Ticket = $t.Num; Status = 'SKIPPED (already done)' }
        continue
    }

    Write-Log "Starting ticket $($t.Num): $($t.Title)"
    $prompt = Build-Prompt $t

    $job = Start-Job -ScriptBlock {
        param($repoRoot, $prompt, $extraArgs, $logFile)
        Set-Location $repoRoot
        & claude @extraArgs $prompt *> $logFile
        exit $LASTEXITCODE
    } -ArgumentList $RepoRoot, $prompt, $claudeArgs, $logFile

    $finished = Wait-Job $job -Timeout ($TimeoutMinutes * 60)

    if (-not $finished) {
        Stop-Job $job | Out-Null
        Remove-Job $job -Force | Out-Null
        if (Test-LimitHit $logFile) {
            Write-Log "Ticket $($t.Num) hit a USAGE/RATE LIMIT (during timeout wait). Stopping the entire run. Log: $logFile"
            $results += [pscustomobject]@{ Ticket = $t.Num; Status = 'LIMIT HIT - run stopped' }
            break
        }
        Write-Log "Ticket $($t.Num) TIMED OUT after $TimeoutMinutes min. Log: $logFile"
        $results += [pscustomobject]@{ Ticket = $t.Num; Status = 'TIMEOUT' }
        if (-not $ContinueOnError) { break }
        continue
    }

    $exitCode = (Receive-Job $job -Wait)[-1]
    Remove-Job $job -Force | Out-Null

    if (Test-LimitHit $logFile) {
        Write-Log "Ticket $($t.Num) hit a USAGE/RATE LIMIT. Stopping the entire run (ticket left unmarked so it re-runs next time). Log: $logFile"
        $results += [pscustomobject]@{ Ticket = $t.Num; Status = 'LIMIT HIT - run stopped' }
        break
    }

    if ($exitCode -eq 0) {
        New-Item -ItemType File -Force -Path $doneMarker | Out-Null
        Write-Log "Ticket $($t.Num) DONE. Log: $logFile"
        $results += [pscustomobject]@{ Ticket = $t.Num; Status = 'DONE' }
    } else {
        Write-Log "Ticket $($t.Num) FAILED (exit $exitCode). Log: $logFile"
        $results += [pscustomobject]@{ Ticket = $t.Num; Status = "FAILED (exit $exitCode)" }
        if (-not $ContinueOnError) { break }
    }
}

# ---- Summary --------------------------------------------------------------------------------
Write-Log "===== RUN SUMMARY ====="
foreach ($r in $results) { Write-Log ("  ticket {0}: {1}" -f $r.Ticket, $r.Status) }
Write-Log "Branch left checked out: $Branch. Nothing was pushed. Review 'git log' and each ticket's *_MANUAL_STEPS.md before merging."

try { [console]::beep(880, 300) } catch {}

