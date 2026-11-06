param(
  [Parameter(Mandatory = $true)][string[]]$Messages,
  [string]$BaseUrl = "http://127.0.0.1:8001",
  [string]$Conversation = "smoke1"
)

$ErrorActionPreference = "Stop"
$headers = @{
  "X-Goog-Authenticated-User-Email" = "accounts.google.com:joe.luo@whiteswandata.com"
  "Content-Type"                    = "application/json"
}

function Send-Turn([string]$message) {
  $body = @{ message = $message; conversation_id = $Conversation } | ConvertTo-Json -Compress
  Write-Host ""
  Write-Host "--- user: $message" -ForegroundColor Cyan
  $sw = [Diagnostics.Stopwatch]::StartNew()
  $resp = Invoke-RestMethod -Method Post -Uri "$BaseUrl/chat" -Headers $headers -Body $body
  $sw.Stop()
  Write-Host ("reply ({0:N1}s, agent_available={1}):" -f $sw.Elapsed.TotalSeconds, $resp.agent_available)
  Write-Host $resp.reply_markdown
  if ($resp.reply_buttons) {
    Write-Host ("buttons: " + (($resp.reply_buttons | ForEach-Object { "$($_.label) -> $($_.send)" }) -join " | "))
  }
  if ($resp.ui_actions) {
    Write-Host ("ui_actions: " + (($resp.ui_actions | ForEach-Object { $_.type }) -join ", "))
  }
}

foreach ($m in $Messages) { Send-Turn $m }
