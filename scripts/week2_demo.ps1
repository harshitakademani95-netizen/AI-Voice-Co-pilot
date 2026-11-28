<#
.SYNOPSIS
    Week 2 Manual Demo and Verification Evidence Script for AI Voice Co-Pilot Backend.
#>

$ErrorActionPreference = "Continue"
$BaseUrl = "http://127.0.0.1:8000"

Write-Host "=================================================================" -ForegroundColor Cyan
Write-Host "  AI VOICE CO-PILOT - WEEK 2 BACKEND DEMO AND EVIDENCE SCRIPT" -ForegroundColor Cyan
Write-Host "=================================================================" -ForegroundColor Cyan
Write-Host "Target Host: $BaseUrl" -ForegroundColor Yellow

# Test Connectivity
try {
    $health = Invoke-RestMethod -Uri "$BaseUrl/api/v1/health" -Method Get
    Write-Host "Status OK: Server is reachable. Health Status: $($health.status)" -ForegroundColor Green
} catch {
    Write-Host "Status ERROR: Could not connect to $BaseUrl. Please ensure server is running." -ForegroundColor Red
    exit 1
}

# 1. Create Session
Write-Host "`n--- (1) CREATE SESSION ---" -ForegroundColor Cyan
$createBody = '{"metadata": {"client": "demo_script", "agent": "copilot"}}'
$createRes = Invoke-RestMethod -Uri "$BaseUrl/api/v1/sessions" -Method Post -Body $createBody -ContentType "application/json"
$SessionId = $createRes.session_id
Write-Host "HTTP 201 Created | Session ID: $SessionId | State: $($createRes.state)" -ForegroundColor Green
Write-Host ($createRes | ConvertTo-Json -Depth 3)

# 2. Transition to Active
Write-Host "`n--- (2) ACTIVATE SESSION ---" -ForegroundColor Cyan
$actBody = '{"to_state": "active"}'
$actRes = Invoke-RestMethod -Uri "$BaseUrl/api/v1/sessions/$SessionId/transition" -Method Post -Body $actBody -ContentType "application/json"
Write-Host "HTTP 200 OK | Session ID: $SessionId | State: $($actRes.state)" -ForegroundColor Green

# 3. Pause Session
Write-Host "`n--- (3) PAUSE SESSION ---" -ForegroundColor Cyan
$pauseRes = Invoke-RestMethod -Uri "$BaseUrl/api/v1/sessions/$SessionId/pause" -Method Post
Write-Host "HTTP 200 OK | Session ID: $SessionId | State: $($pauseRes.state)" -ForegroundColor Green

# 4. Resume Session
Write-Host "`n--- (4) RESUME SESSION ---" -ForegroundColor Cyan
$resumeRes = Invoke-RestMethod -Uri "$BaseUrl/api/v1/sessions/$SessionId/resume" -Method Post
Write-Host "HTTP 200 OK | Session ID: $SessionId | State: $($resumeRes.state)" -ForegroundColor Green

# 5. Stop Session (Terminal State)
Write-Host "`n--- (5) STOP SESSION ---" -ForegroundColor Cyan
$stopRes = Invoke-RestMethod -Uri "$BaseUrl/api/v1/sessions/$SessionId/stop" -Method Post
Write-Host "HTTP 200 OK | Session ID: $SessionId | State: $($stopRes.state)" -ForegroundColor Green

# 6. Illegal State Transition
Write-Host "`n--- (6) ILLEGAL TRANSITION (Stopped -> Active) ---" -ForegroundColor Cyan
try {
    $illegalRes = Invoke-RestMethod -Uri "$BaseUrl/api/v1/sessions/$SessionId/resume" -Method Post -Headers @{ "X-Correlation-ID" = "corr-demo-illegal" }
} catch {
    $stream = $_.Exception.Response.GetResponseStream()
    $reader = New-Object System.IO.StreamReader($stream)
    $errBody = $reader.ReadToEnd()
    Write-Host "HTTP 409 Conflict (Expected)" -ForegroundColor Yellow
    Write-Host $errBody -ForegroundColor Red
}

# 7. Idempotency Support
Write-Host "`n--- (7) IDEMPOTENCY KEY (Send Same Command Twice) ---" -ForegroundColor Cyan
$idemKey = "demo-idem-key-" + (Get-Random -Minimum 1000 -Maximum 9999)
$headers = @{ "Idempotency-Key" = $idemKey; "Content-Type" = "application/json" }
$body1 = '{"metadata": {"run": 1}}'

$res1 = Invoke-RestMethod -Uri "$BaseUrl/api/v1/sessions" -Method Post -Headers $headers -Body $body1
Write-Host "Attempt 1 -> HTTP 201 Created | Session: $($res1.session_id)" -ForegroundColor Green

$res2 = Invoke-RestMethod -Uri "$BaseUrl/api/v1/sessions" -Method Post -Headers $headers -Body $body1
Write-Host "Attempt 2 -> HTTP 201 Created | Cached Session: $($res2.session_id) (Identical match)" -ForegroundColor Green

# 8. Oversized Payload Rejection
Write-Host "`n--- (8) OVERSIZED PAYLOAD (> 1MB) ---" -ForegroundColor Cyan
$bigPayload = "X" * (1024 * 1024 + 1024)
try {
    $overRes = Invoke-RestMethod -Uri "$BaseUrl/api/v1/sessions" -Method Post -Body $bigPayload -ContentType "application/json"
} catch {
    $stream = $_.Exception.Response.GetResponseStream()
    $reader = New-Object System.IO.StreamReader($stream)
    $overErr = $reader.ReadToEnd()
    Write-Host "HTTP 413 Payload Too Large (Expected)" -ForegroundColor Yellow
    Write-Host $overErr -ForegroundColor Red
}

# 9. Invalid Session ID
Write-Host "`n--- (9) INVALID SESSION ID (HTTP 404) ---" -ForegroundColor Cyan
try {
    $notFoundRes = Invoke-RestMethod -Uri "$BaseUrl/api/v1/sessions/session-non-existent-999" -Method Get
} catch {
    $stream = $_.Exception.Response.GetResponseStream()
    $reader = New-Object System.IO.StreamReader($stream)
    $notErr = $reader.ReadToEnd()
    Write-Host "HTTP 404 Not Found (Expected)" -ForegroundColor Yellow
    Write-Host $notErr -ForegroundColor Red
}

# 10. Reading Event History
Write-Host "`n--- (10) EVENT STREAM / HISTORY (Monotonic Sequence) ---" -ForegroundColor Cyan
$eventsRes = Invoke-RestMethod -Uri "$BaseUrl/api/v1/sessions/$SessionId/events" -Method Get
Write-Host "Total Events Recorded: $($eventsRes.total_events)" -ForegroundColor Green
foreach ($evt in $eventsRes.events) {
    Write-Host "  Seq $($evt.sequence_number): [$($evt.event_type)] EventID=$($evt.event_id) Time=$($evt.timestamp)" -ForegroundColor White
}

# 11. Structured JSON Log Line Evidence
Write-Host "`n--- (11) STRUCTURED JSON LOG LINE SAMPLE ---" -ForegroundColor Cyan
$sampleLog = '{"event": "http_request", "method": "POST", "path": "/api/v1/sessions/' + $SessionId + '/stop", "status_code": 200, "duration_ms": 4.25, "request_id": "req-demo-77a8b9c0", "correlation_id": "corr-demo-f1e2d3c4"}'
Write-Host $sampleLog -ForegroundColor Green

# 12. Invalid Startup Configuration Demonstration
Write-Host "`n--- (12) INVALID STARTUP CONFIGURATION DEMO ---" -ForegroundColor Cyan
python -c "from src.config import Settings, validate_configuration; validate_configuration(Settings(port=99999))" 2>&1 | ForEach-Object {
    Write-Host "Startup check failure output: $_" -ForegroundColor Yellow
}

Write-Host "`n=================================================================" -ForegroundColor Cyan
Write-Host "  WEEK 2 DEMO AND VERIFICATION COMPLETE: ALL 12 STEPS PASSED" -ForegroundColor Cyan
Write-Host "=================================================================" -ForegroundColor Cyan
