#!/usr/bin/env bash
# Compile a certiqs extension (optional) and restart the running certiqs IDE
# extension host — Developer: Restart Extension Host.
#
# Usage:
#   ./scripts/refresh-extensions.sh
#   ./scripts/refresh-extensions.sh hq
#   ./scripts/refresh-extensions.sh sim
#   ./scripts/refresh-extensions.sh all
#   npm run refresh-extensions -- hq

set -euo pipefail

if [[ "$OSTYPE" == "darwin"* ]]; then
	realpath() { [[ $1 = /* ]] && echo "$1" || echo "$PWD/${1#./}"; }
	ROOT="$(dirname "$(dirname "$(realpath "$0")")")"
else
	ROOT="$(dirname "$(dirname "$(readlink -f "$0")")")"
fi

STATE="$ROOT/.build/run-debug"
TRIGGER="$STATE/restart-extension-host"
TARGET="${1:-}"

compile_one() {
	local id="$1"
	local dir="$ROOT/extensions/certiqs-$id"
	if [[ ! -f "$dir/package.json" ]]; then
		echo "unknown extension: certiqs-$id" >&2
		exit 1
	fi
	echo "compiling certiqs-$id"
	npm --prefix "$dir" run compile
}

case "$TARGET" in
	"" | none | restart )
		;;
	hq | sim | assurance | qdb )
		compile_one "$TARGET"
		;;
	all )
		for id in hq sim assurance qdb; do
			if [[ -f "$ROOT/extensions/certiqs-$id/package.json" ]]; then
				compile_one "$id"
			fi
		done
		;;
	* )
		echo "usage: $0 [hq|sim|assurance|qdb|all]" >&2
		exit 1
		;;
esac

mkdir -p "$STATE"
date +%s >"$TRIGGER"
echo "triggered Developer: Restart Extension Host ($TRIGGER)"
echo "if the running window does not refresh, focus it and run that command from the Command Palette"
