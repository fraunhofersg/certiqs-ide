#!/usr/bin/env bash
# Start npm run watch (if needed) and launch certiqs IDE with debug ports.
# Default launch compound: certiqs IDE (Hot Reload)
# Attach from the existing launch.json configs:
#   Attach to Main Process        5875
#   Attach to Extension Host      5870
#   Attach to Shared Process      5879
#   Attach to Agent Host Process  5878
#
# Usage:
#   ./scripts/run-debug.sh
#   ./scripts/run-debug.sh --stop
#   npm run run-debug

set -euo pipefail

if [[ "$OSTYPE" == "darwin"* ]]; then
	realpath() { [[ $1 = /* ]] && echo "$1" || echo "$PWD/${1#./}"; }
	ROOT="$(dirname "$(dirname "$(realpath "$0")")")"
else
	ROOT="$(dirname "$(dirname "$(readlink -f "$0")")")"
fi

STATE="$ROOT/.build/run-debug"
WATCH_PID_FILE="$STATE/watch.pid"
WATCH_LOG="$STATE/watch.log"
CODE_PID_FILE="$STATE/code.pid"

mkdir -p "$STATE"

is_running() {
	local pid="${1:-}"
	[[ -n "$pid" ]] && kill -0 "$pid" 2>/dev/null
}

code_running() {
	pgrep -f "[.]build/electron/.*/Contents/MacOS/" >/dev/null 2>&1 \
		|| pgrep -f "[.]build/electron/certiqs-ide" >/dev/null 2>&1
}

stop_all() {
	if [[ -f "$WATCH_PID_FILE" ]]; then
		local watch_pid
		watch_pid="$(cat "$WATCH_PID_FILE" || true)"
		if is_running "$watch_pid"; then
			kill "$watch_pid" 2>/dev/null || true
			echo "stopped watch (pid $watch_pid)"
		fi
		rm -f "$WATCH_PID_FILE"
	fi
	if [[ -f "$CODE_PID_FILE" ]]; then
		local code_pid
		code_pid="$(cat "$CODE_PID_FILE" || true)"
		if is_running "$code_pid"; then
			kill "$code_pid" 2>/dev/null || true
			echo "stopped certiqs IDE (pid $code_pid)"
		fi
		rm -f "$CODE_PID_FILE"
	fi
}

if [[ "${1:-}" == "--stop" ]]; then
	stop_all
	exit 0
fi

existing_watch="$(pgrep -f "npm run watch" | head -n1 || true)"
if [[ -n "$existing_watch" ]] && is_running "$existing_watch"; then
	echo "watch already running (pid $existing_watch)"
elif [[ -f "$WATCH_PID_FILE" ]] && is_running "$(cat "$WATCH_PID_FILE")"; then
	echo "watch already running (pid $(cat "$WATCH_PID_FILE"))"
else
	echo "starting npm run watch → $WATCH_LOG"
	nohup npm --prefix "$ROOT" run watch >"$WATCH_LOG" 2>&1 &
	echo $! >"$WATCH_PID_FILE"
	echo "watch pid $(cat "$WATCH_PID_FILE")"
fi

if code_running; then
	echo "certiqs IDE is already running. Attach debug ports or run ./scripts/refresh-extensions.sh"
	echo "  main            5875"
	echo "  extension host  5870"
	echo "  shared process  5879"
	echo "  agent host      5878"
	exit 0
fi

MAIN_JS="$ROOT/out/main.js"

wait_for_main() {
	local waited=0
	local limit=180
	if [[ -f "$MAIN_JS" ]]; then
		return 0
	fi
	echo "waiting for $MAIN_JS (watch compile)…"
	while (( waited < limit )); do
		if [[ -f "$MAIN_JS" ]]; then
			echo "found $MAIN_JS after ${waited}s"
			return 0
		fi
		sleep 1
		waited=$((waited + 1))
	done
	return 1
}

if wait_for_main; then
	export VSCODE_SKIP_PRELAUNCH=1
else
	echo "out/main.js is missing — running preLaunch compile instead of skipping it"
	unset VSCODE_SKIP_PRELAUNCH
fi

export NODE_ENV=development
export VSCODE_DEV=1

echo "starting certiqs IDE with inspect ports"
echo "  main            5875"
echo "  extension host  5870"
echo "  shared process  5879"
echo "  agent host      5878"

cd "$ROOT"
# shellcheck disable=SC2094
./scripts/code.sh \
	--inspect=5875 \
	--inspect-extensions=5870 \
	--inspect-sharedprocess=5879 \
	--inspect-agenthost=5878 \
	"$@" &
echo $! >"$CODE_PID_FILE"
wait "$(cat "$CODE_PID_FILE")"
rm -f "$CODE_PID_FILE"
