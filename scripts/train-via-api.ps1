# -*- coding: utf-8 -*-
# AI 字体训练 - API 路径（无需 UI）
# 等价于浏览器操作，但适合脚本/远程/集成测试
# 用法：在项目根目录 PowerShell 里运行
#   powershell -ExecutionPolicy Bypass -File scripts\train-via-api.ps1

$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$OutputEncoding = [System.Text.Encoding]::UTF8

# ====== 配置（按需改） ======
$BASE = 'http://localhost:7550'
$PROJECT = 'G:\Projects\projects_ai\gaudi-ai-font-tool'

$IMAGES_DIR = 'G:\Projects\projects_ai\gaudi-font-preprocess\data\sessions\f00b32702e636da1f6f464db4edbfa3c\scaled'
$SOURCE_FONT = Join-Path $PROJECT 'font\default.ttf'
$OUTPUT_DIR = Join-Path $PROJECT 'model\run'
$BASE_CHECKPOINT = Join-Path $PROJECT 'model\zi2zi-JiT-B-16.pth'

# 取字数量（None=全部；如 50 = 前 50 字；快速冒烟用 5/10）
$CHAR_COUNT = $null   # 设数字可限制

# 训练超参
$EPOCHS = 50
$BATCH_SIZE = 8
$LORA_R = 32
$LORA_ALPHA = 32
$CFG = 2.6
$NUM_FONTS = 1
$NUM_CHARS = 200000
$MAX_CHARS_PER_FONT = 10000
$NUM_WORKERS = 0

# ====== 函数 ======
function Invoke-Api($method, $path, $body) {
    $url = "$BASE$path"
    $headers = @{ 'Content-Type' = 'application/json' }
    if ($body) {
        $json = $body | ConvertTo-Json -Depth 10
        $bytes = [System.Text.Encoding]::UTF8.GetBytes($json)
        $req = [System.Net.HttpWebRequest]::Create($url)
        $req.Method = $method
        $req.ContentType = 'application/json'
        $req.Timeout = 600000
        $req.GetRequestStream().Write($bytes, 0, $bytes.Length)
        $req.GetRequestStream().Close()
    } else {
        $req = [System.Net.HttpWebRequest]::Create($url)
        $req.Method = $method
        $req.Timeout = 600000
    }
    try {
        $resp = $req.GetResponse()
        $reader = New-Object System.IO.StreamReader($resp.GetResponseStream())
        $text = $reader.ReadToEnd()
        $reader.Close()
        return @{ Status = [int]$resp.StatusCode; Body = $text }
    } catch [System.Net.WebException] {
        $reader = New-Object System.IO.StreamReader($_.Exception.Response.GetResponseStream())
        $text = $reader.ReadToEnd()
        $reader.Close()
        return @{ Status = [int]$_.Exception.Response.StatusCode; Body = $text }
    }
}

function Show-Step($msg) {
    Write-Host ''
    Write-Host ('=' * 60) -ForegroundColor Cyan
    Write-Host ("  $msg") -ForegroundColor Cyan
    Write-Host ('=' * 60) -ForegroundColor Cyan
}

# ====== Step 1: 准备数据（images_dir 模式） ======
Show-Step 'Step 1/3: 准备训练数据（images_dir 模式）'
$prepareBody = @{
    images_dir  = $IMAGES_DIR
    source_font = $SOURCE_FONT
    output_dir  = $OUTPUT_DIR
}
if ($CHAR_COUNT) { $prepareBody.char_count = [int]$CHAR_COUNT }
$resp = Invoke-Api 'POST' '/api/train/prepare' $prepareBody
Write-Host "HTTP $($resp.Status)"
$prepare = $resp.Body | ConvertFrom-Json
$prepare | ConvertTo-Json -Depth 5
if (-not $prepare.success) { throw "准备失败: $($prepare.error)" }
$DATA_DIR = $prepare.data_dir
$TEST_NPZ = $prepare.test_npz
Write-Host ("`n  char_count = $($prepare.char_count)") -ForegroundColor Green
Write-Host ("  data_dir   = $DATA_DIR") -ForegroundColor Green

# ====== Step 2: 启动训练 ======
Show-Step 'Step 2/3: 启动训练'
$startBody = @{
    output_dir    = $DATA_DIR
    data_path     = $DATA_DIR
    test_npz_path = $TEST_NPZ
    base_checkpoint = $BASE_CHECKPOINT
    source_font   = $SOURCE_FONT
    epochs        = $EPOCHS
    batch_size    = $BATCH_SIZE
    lora_r        = $LORA_R
    lora_alpha    = $LORA_ALPHA
    cfg           = $CFG
    num_fonts     = $NUM_FONTS
    num_chars     = $NUM_CHARS
    max_chars_per_font = $MAX_CHARS_PER_FONT
    num_workers   = $NUM_WORKERS
}
$resp = Invoke-Api 'POST' '/api/train/start' $startBody
Write-Host "HTTP $($resp.Status)"
$start = $resp.Body | ConvertFrom-Json
$start | ConvertTo-Json -Depth 5
if (-not $start.success) { throw "启动失败: $($start.error)" }

# ====== Step 3: 轮询状态 ======
Show-Step 'Step 3/3: 轮询训练状态（每 5 秒）'
while ($true) {
    Start-Sleep -Seconds 5
    $resp = Invoke-Api 'GET' '/api/train/status' $null
    $st = $resp.Body | ConvertFrom-Json
    $ts = Get-Date -Format 'HH:mm:ss'
    $line = "[$ts] status=$($st.status) epoch=$($st.current_epoch)/$($st.total_epochs) loss=$($st.current_loss) lr=$($st.current_lr)"
    Write-Host $line
    if ($st.status -in @('completed', 'error', 'idle') -and $st.current_epoch -ge $EPOCHS) {
        break
    }
    if ($st.status -eq 'error') {
        Write-Host "  error: $($st.error_message)" -ForegroundColor Red
        break
    }
}

Write-Host ''
Write-Host '训练完成。产物在:' -ForegroundColor Green
Write-Host "  $DATA_DIR\checkpoint-last.pth"
Write-Host "  $DATA_DIR\checkpoint-best.pth"
Write-Host "  日志: $(Split-Path $DATA_DIR -Parent)\logs\training.log"
