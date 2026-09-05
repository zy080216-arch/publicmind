#!/bin/zsh

set -u

project_dir=${0:A:h}
site_url="http://127.0.0.1:8000/"
health_url="http://127.0.0.1:8000/api/config"
uvicorn_bin="$project_dir/.venv/bin/uvicorn"

cd "$project_dir" || exit 1

open_site() {
  if [[ ${PUBLICMIND_SKIP_OPEN:-0} != "1" ]]; then
    open "$site_url"
  fi
}

if curl -fsS --max-time 1 "$health_url" >/dev/null 2>&1; then
  open_site
  exit 0
fi

if [[ ! -x "$uvicorn_bin" ]]; then
  echo "PublicMind 还没有完成本机安装。"
  echo "请先按照 README 的“首次安装”步骤建立 .venv。"
  echo
  read "?按回车关闭窗口。"
  exit 1
fi

open_when_ready() {
  local attempts=0
  while (( attempts < 60 )); do
    if curl -fsS --max-time 1 "$health_url" >/dev/null 2>&1; then
      open_site
      return 0
    fi
    sleep 0.25
    (( attempts += 1 ))
  done
  echo "网页未能自动打开，请查看上方错误信息。"
}

echo "正在启动 PublicMind…"
echo "网页打开后请保留这个窗口；关闭窗口或按 Control-C 即可停止服务。"
echo

open_when_ready &
exec "$uvicorn_bin" app.backend.api:create_app --factory --host 127.0.0.1 --port 8000
