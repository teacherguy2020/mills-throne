#!/bin/sh
set -eu

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
PICO_IP=${PICO_IP:-10.0.0.7}
MAIN_FILE=${1:-"$SCRIPT_DIR/micropicoMills/main.py"}
SECRETS_FILE=${MILLS_SECRETS_FILE:-"$SCRIPT_DIR/micropicoMills/secrets.py"}
PICO_URL="http://$PICO_IP"

if [ ! -f "$MAIN_FILE" ]; then
    echo "ERROR: main.py not found: $MAIN_FILE" >&2
    exit 1
fi

if [ -n "${MILLS_OTA_TOKEN:-}" ]; then
    OTA_TOKEN=$MILLS_OTA_TOKEN
elif [ -f "$SECRETS_FILE" ]; then
    OTA_TOKEN=$(python3 - "$SECRETS_FILE" <<'PY'
import ast
import sys

path = sys.argv[1]
tree = ast.parse(open(path, "r").read(), filename=path)
for node in tree.body:
    targets = []
    if isinstance(node, ast.Assign):
        targets = node.targets
    elif isinstance(node, ast.AnnAssign):
        targets = [node.target]
    for target in targets:
        if isinstance(target, ast.Name) and target.id == "OTA_TOKEN":
            value = node.value
            if isinstance(value, ast.Constant) and isinstance(value.value, str):
                print(value.value)
                raise SystemExit(0)
raise SystemExit("OTA_TOKEN is missing from {}".format(path))
PY
    )
else
    echo "ERROR: set MILLS_OTA_TOKEN or create $SECRETS_FILE" >&2
    exit 1
fi

if [ -z "$OTA_TOKEN" ]; then
    echo "ERROR: OTA token is empty" >&2
    exit 1
fi

echo "Uploading $MAIN_FILE to Pico at $PICO_IP..."
response=$(curl --silent --show-error --max-time 30 --config - <<EOF
url = "$PICO_URL/ota"
request = POST
header = "Authorization: Bearer $OTA_TOKEN"
header = "Content-Type: application/octet-stream"
data-binary = "@$MAIN_FILE"
write-out = "\nHTTP_STATUS:%{http_code}\n"
EOF
)
printf '%s\n' "$response" | sed 's/HTTP_STATUS:/HTTP status: /'

case "$response" in
    *'"ok":true'*'HTTP_STATUS:200'*)
        ;;
    *)
        echo "ERROR: Pico rejected the OTA update" >&2
        exit 1
        ;;
esac

echo "Waiting for Pico reboot..."
sleep 2
attempt=1
while [ "$attempt" -le 30 ]; do
    if curl --silent --show-error --fail --max-time 2 "$PICO_URL/status" >/dev/null 2>&1; then
        echo "Pico is responding after OTA reboot."
        exit 0
    fi
    sleep 1
    attempt=$((attempt + 1))
done

echo "ERROR: OTA upload was accepted, but Pico did not respond after reboot." >&2
echo "Use USB/serial recovery and restore main.backup.py if necessary." >&2
exit 1
