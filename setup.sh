#!/usr/bin/env bash
# 產生 .env：自動填好資料庫密碼、JWT 金鑰、示範帳號密碼，只問模型設定。
# 非互動用法：LLM_PROVIDER=anthropic LLM_API_KEY=sk-... ./setup.sh
set -euo pipefail
cd "$(dirname "$0")"

if [[ -f .env && "${1:-}" != "--force" ]]; then
  echo ".env 已存在，不覆寫（要重新產生請加 --force）。"
  exit 0
fi

rand() { openssl rand -hex "$1" 2>/dev/null || python3 -c "import secrets; print(secrets.token_hex($1))"; }

set_kv() {  # set_kv KEY VALUE：取代 .env 中 KEY= 那一行（被註解掉的「# KEY=」也算）
  local key="$1" value="$2" tmp
  tmp="$(mktemp)"
  awk -v k="$key" -v v="$value" 'BEGIN{FS=OFS="="} $1==k || $1=="# " k {print k "=" v; next} {print}' .env > "$tmp"
  mv "$tmp" .env
}

ask() {  # ask 變數名 提示 預設值：已有環境變數就直接用；非互動環境用預設值
  local name="$1" prompt="$2" default="${3:-}" value="${!1:-}"
  if [[ -z "$value" && -t 0 ]]; then
    read -r -p "$prompt${default:+ [$default]}: " value
  fi
  printf -v "$name" '%s' "${value:-$default}"
}

ask_secret() {  # 同 ask，但輸入不顯示在畫面上，避免旁人或螢幕錄影看到金鑰
  local name="$1" prompt="$2" value="${!1:-}"
  if [[ -z "$value" && -t 0 ]]; then
    read -r -s -p "$prompt（輸入時不會顯示）: " value
    echo
  fi
  printf -v "$name" '%s' "$value"
}

cp .env.example .env
PG="$(rand 16)"
set_kv POSTGRES_PASSWORD "$PG"
set_kv JWT_SECRET "$(rand 32)"
DEMO="$(rand 6)"
set_kv SEED_DEMO_PASSWORD "$DEMO"
set_kv DATABASE_URL "postgresql+psycopg://aftershock:${PG}@localhost:5437/aftershock"

echo "解析供應商回信要用哪一種模型？ 1) Claude 官方 API  2) OpenAI 相容端點（Azure OpenAI、vLLM、Ollama…）  3) 先不設定"
ask CHOICE "請選擇" "3"
case "$CHOICE" in
  1|anthropic)
    set_kv LLM_PROVIDER anthropic
    ask_secret LLM_API_KEY "Anthropic API key"
    set_kv LLM_API_KEY "$LLM_API_KEY" ;;
  2|openai_compatible)
    set_kv LLM_PROVIDER openai_compatible
    ask LLM_BASE_URL "端點（例如 https://<resource>.openai.azure.com/openai/v1/ 或 http://host.docker.internal:11434/v1）" ""
    ask_secret LLM_API_KEY "API key（本機模型可留空）"
    ask LLM_MODEL "模型名稱" ""
    for k in LLM_BASE_URL LLM_API_KEY LLM_MODEL; do set_kv "$k" "${!k}"; done ;;
  *) echo "先不設定模型：系統照常啟動，供應商回信改由人判讀。之後編輯 .env 的 LLM_* 再重啟即可。" ;;
esac

cat <<EOF

完成。接下來：
  docker compose up -d --build
  開啟 http://localhost:3400 ，示範帳號例如 scm.manager（供應鏈主管）、amy.chou（採購）
  寄出的信都在本機假信箱 http://localhost:8026
  示範帳號密碼：$DEMO（也記在 .env 的 SEED_DEMO_PASSWORD）
EOF
