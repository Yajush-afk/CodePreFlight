#!/bin/sh
set -eu

project_root=$(CDPATH= cd -- "$(dirname -- "$0")/../.." && pwd)
demo_root=$(mktemp -d "${TMPDIR:-/tmp}/codepreflight-demo.XXXXXX")

cp "$project_root/evaluation/seeded/auth_validation/before.py" "$demo_root/auth.py"
cp "$project_root/evaluation/seeded/auth_validation/check_auth.py" "$demo_root/test_auth.py"
git -C "$demo_root" init -b main >/dev/null
git -C "$demo_root" config user.name "CodePreFlight Demo"
git -C "$demo_root" config user.email "demo@codepreflight.local"
git -C "$demo_root" add .
git -C "$demo_root" commit -m "Add validated session creation" >/dev/null
cp "$project_root/evaluation/seeded/auth_validation/after.py" "$demo_root/auth.py"
git -C "$demo_root" add auth.py

printf '%s\n' "$demo_root"
