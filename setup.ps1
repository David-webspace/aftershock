# Windows 版：產生 .env（自動填好密碼與金鑰，只問模型設定）。
# 一般直接雙擊 start.cmd 即可；單獨執行：powershell -ExecutionPolicy Bypass -File .\setup.ps1 [-Force]
param([switch]$Force)
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

if ((Test-Path .env) -and -not $Force) { Write-Host ".env 已存在，不覆寫（要重新產生請加 -Force）。"; exit 0 }

function Rand([int]$bytes) {
  $b = New-Object byte[] $bytes
  [System.Security.Cryptography.RandomNumberGenerator]::Create().GetBytes($b)
  -join ($b | ForEach-Object { $_.ToString("x2") })
}

$lines = Get-Content .env.example -Encoding UTF8
# 金鑰輸入不顯示在畫面上（顯示成 *），避免旁人或螢幕錄影看到
function ReadSecret([string]$prompt) {
  $secure = Read-Host $prompt -AsSecureString
  $ptr = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($secure)
  try { [Runtime.InteropServices.Marshal]::PtrToStringBSTR($ptr) } finally { [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($ptr) }
}

function SetKv([string]$key, [string]$value) {
  # 被註解掉的「# KEY=」也算，取代成啟用的設定
  $script:lines = $script:lines | ForEach-Object { if ($_ -like "$key=*" -or $_ -like "# $key=*") { "$key=$value" } else { $_ } }
}

$pg = Rand 16; $demo = Rand 6
SetKv POSTGRES_PASSWORD $pg
SetKv JWT_SECRET (Rand 32)
SetKv SEED_DEMO_PASSWORD $demo
SetKv DATABASE_URL "postgresql+psycopg://aftershock:$pg@localhost:5437/aftershock"

Write-Host "解析供應商回信要用哪一種模型？ 1) Claude 官方 API  2) OpenAI 相容端點（Azure OpenAI、vLLM、Ollama…）  3) 先不設定"
$choice = Read-Host "請選擇 [3]"
switch ($choice) {
  "1" { SetKv LLM_PROVIDER anthropic; SetKv LLM_API_KEY (ReadSecret "Anthropic API key（輸入時不會顯示）") }
  "2" {
    SetKv LLM_PROVIDER openai_compatible
    SetKv LLM_BASE_URL (Read-Host "端點 URL（本機 Ollama：http://host.docker.internal:11434/v1）")
    SetKv LLM_API_KEY (ReadSecret "API key（輸入時不會顯示；本機模型可留空）")
    SetKv LLM_MODEL (Read-Host "模型名稱")
  }
  default { Write-Host "先不設定模型：系統照常啟動，供應商回信改由人判讀。" }
}

# 不用 Set-Content -Encoding UTF8：Windows PowerShell 5.1 會加 BOM，Docker Compose 讀 .env 會出錯
[System.IO.File]::WriteAllLines((Join-Path $PSScriptRoot ".env"), [string[]]$lines, (New-Object System.Text.UTF8Encoding $false))
Write-Host "`n完成。接下來：docker compose up -d --build，開啟 http://localhost:3400"
Write-Host "示範帳號密碼：$demo（也記在 .env 的 SEED_DEMO_PASSWORD）"
