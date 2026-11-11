#!/usr/bin/env bash
# Tests that infra/lib/tf.sh only applies a saved plan after the approval check and the plan
# guard pass. Uses a fake `terraform` on PATH and a local HTTPS server for the pin. No lab needed.
set -uo pipefail
here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
lib="$here/../lib"
t="$(mktemp -d)"; srvpid=""
trap '[ -z "$srvpid" ] || kill "$srvpid" 2>/dev/null; rm -rf "$t"' EXIT
fail=0
ok()  { echo "ok   $1"; }
bad() { echo "FAIL $1"; fail=1; }

# fake repo tree (tf.sh derives the repo root from its own location)
r="$t/repo"; mkdir -p "$r/infra/lib" "$r/infra/terraform" "$r/project/plans" "$r/project/approvals" "$t/bin" "$t/state"
cp "$lib/tf.sh" "$lib/pin.sh" "$lib/approval_check.sh" "$lib/plan_guard.py" "$r/infra/lib/"
echo L0 >"$r/project/STAGE"; echo body >"$r/project/plans/L0.md"
approve() { printf '%s  x  y  z\n' "$(sha256sum "$r/project/plans/L0.md" | cut -d' ' -f1)" >"$r/project/approvals/L0.plan.sha256"; }
approve
echo "ssh-ed25519 AAAA fake" >"$t/key.pub"

cat >"$t/bin/terraform" <<'EOF'
#!/usr/bin/env bash
echo "$*" >>"$FAKE_LOG"
case " $* " in
  *" show "*) cat "$FAKE_SHOW" ;;
esac
exit 0
EOF
chmod 755 "$t/bin/terraform"

openssl req -x509 -newkey rsa:2048 -nodes -keyout "$t/k.pem" -out "$t/c.pem" -days 1 \
    -subj /CN=localhost -addext "subjectAltName=DNS:localhost,IP:127.0.0.1" 2>/dev/null
fp="$(openssl x509 -in "$t/c.pem" -noout -fingerprint -sha256 | sed 's/^[^=]*=//')"
cat >"$t/srv.py" <<PY
import http.server, ssl, os
class H(http.server.BaseHTTPRequestHandler):
    def log_message(self,*a): pass
s = http.server.ThreadingHTTPServer(("127.0.0.1", 0), H)
c = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER); c.load_cert_chain("$t/c.pem","$t/k.pem")
s.socket = c.wrap_socket(s.socket, server_side=True)
open("$t/port.tmp","w").write(str(s.server_address[1])); os.rename("$t/port.tmp","$t/port")
s.serve_forever()
PY
python3 -I "$t/srv.py" & srvpid=$!
for _ in $(seq 100); do [ -s "$t/port" ] && break; sleep 0.1; done
port="$(cat "$t/port" 2>/dev/null)"; [ -n "$port" ] || { echo "FAIL server did not start"; exit 1; }

good='{"resource_changes":[{"address":"proxmox_virtual_environment_vm.lab","mode":"managed","type":"proxmox_virtual_environment_vm","provider_name":"registry.terraform.io/bpg/proxmox","change":{"actions":["create"],"after":{"pool_id":"p1"}}}]}'
repl='{"resource_changes":[{"address":"proxmox_virtual_environment_vm.lab","mode":"managed","type":"proxmox_virtual_environment_vm","provider_name":"registry.terraform.io/bpg/proxmox","change":{"actions":["delete","create"],"after":{"pool_id":"p1"}}}]}'

# apply <show-json> [extra env...]; returns tf.sh's exit code; terraform calls are in $t/log
apply_with() {
    local show="$1"; shift
    printf '%s' "$show" >"$t/show.json"; : >"$t/log"; : >"$t/state/a.tfplan"
    env "$@" PATH="$t/bin:$PATH" FAKE_LOG="$t/log" FAKE_SHOW="$t/show.json" \
        PVE_ENDPOINT="https://127.0.0.1:$port" PVE_API_TOKEN='fake@pve!t=secret' PVE_TLS_FINGERPRINT="$fp" \
        TF_VAR_pool_id=p1 LAB_SSH_PUBKEY_FILE="$t/key.pub" NEONCORE_STATE_DIR="$t/state" \
        "$r/infra/lib/tf.sh" apply a.tfplan </dev/null >"$t/out" 2>&1
}
applied() { grep -q ' apply ' "$t/log"; }

apply_with "$good" X=1; rc=$?
[ $rc -eq 0 ] && applied && grep -q 'apply.*a.tfplan' "$t/log" && ok "approved + clean plan: applies the saved plan file" || { bad "approved + clean plan applies"; cat "$t/out"; }
[ ! -e "$t/state/a.tfplan" ] && ok "plan file deleted after apply" || bad "plan file deleted after apply"

echo changed >>"$r/project/plans/L0.md"
apply_with "$good" X=1; rc=$?
[ $rc -ne 0 ] && ! applied && [ ! -s "$t/log" ] && ok "approval mismatch: no terraform call at all" || bad "approval mismatch blocks apply"
approve

for bad_json in '{bad' '{"resource_changes":[],"output_changes":{"o":{}}}' \
    '{"resource_changes":[{"address":"a","mode":"managed","type":"proxmox_virtual_environment_vm","provider_name":"registry.terraform.io/bpg/proxmox","change":{"actions":["create","wat"],"after":{"pool_id":"p1"}}}]}'; do
    apply_with "$bad_json" X=1; rc=$?
    [ $rc -ne 0 ] && ! applied && ok "guard refusal blocks apply (${bad_json:0:24})" || bad "guard refusal blocks apply (${bad_json:0:24})"
done

apply_with "$repl" CLAUDECODE=1; rc=$?
[ $rc -ne 0 ] && ! applied && ok "replace under CLAUDECODE: not applied" || bad "replace under CLAUDECODE not applied"
apply_with "$repl" NEONCORE_ALLOW_REPLACE=1; rc=$?
[ $rc -ne 0 ] && ! applied && ok "replace with override variable: not applied" || bad "replace with override variable"
apply_with "$repl" X=1; rc=$?
[ $rc -ne 0 ] && ! applied && ok "replace with no TTY: not applied" || bad "replace with no TTY"
[ -e "$t/state/a.tfplan" ] && ok "refused plan file is kept for inspection" || bad "refused plan file kept"

# wrong fingerprint: no terraform call after the approval check
: >"$t/log"; : >"$t/state/a.tfplan"; printf '%s' "$good" >"$t/show.json"
wrong="${fp//:/}"; wrong="${wrong/#?/0}"; [ "$wrong" = "${fp//:/}" ] && wrong="${wrong/#?/1}"
env PATH="$t/bin:$PATH" FAKE_LOG="$t/log" FAKE_SHOW="$t/show.json" PVE_ENDPOINT="https://127.0.0.1:$port" \
    PVE_API_TOKEN=x PVE_TLS_FINGERPRINT="$wrong" TF_VAR_pool_id=p1 LAB_SSH_PUBKEY_FILE="$t/key.pub" \
    NEONCORE_STATE_DIR="$t/state" "$r/infra/lib/tf.sh" apply a.tfplan </dev/null >"$t/out" 2>&1
[ $? -ne 0 ] && [ ! -s "$t/log" ] && ok "wrong pin: terraform never run" || bad "wrong pin: terraform never run"

# a new plan removes old plan files (stale plans hold variable values)
printf '%s' "$good" >"$t/show.json"; : >"$t/log"; : >"$t/state/old1.tfplan"; : >"$t/state/old2.tfplan"; : >"$t/state/keep.txt"
env PATH="$t/bin:$PATH" FAKE_LOG="$t/log" FAKE_SHOW="$t/show.json" \
    PVE_ENDPOINT="https://127.0.0.1:$port" PVE_API_TOKEN='fake@pve!t=secret' PVE_TLS_FINGERPRINT="$fp" \
    TF_VAR_pool_id=p1 LAB_SSH_PUBKEY_FILE="$t/key.pub" NEONCORE_STATE_DIR="$t/state" \
    "$r/infra/lib/tf.sh" plan </dev/null >"$t/out" 2>&1
[ ! -e "$t/state/old1.tfplan" ] && [ ! -e "$t/state/old2.tfplan" ] && [ -e "$t/state/keep.txt" ] && ok "new plan removes old .tfplan files only" || { bad "new plan removes old .tfplan files"; cat "$t/out"; }
# no destroy subcommand; path traversal rejected
env PVE_ENDPOINT=https://127.0.0.1:1 PVE_API_TOKEN=x PVE_TLS_FINGERPRINT=00 NEONCORE_STATE_DIR="$t/state" \
    "$r/infra/lib/tf.sh" destroy >/dev/null 2>&1 && bad "no destroy subcommand" || ok "no destroy subcommand"
env NEONCORE_STATE_DIR="$t/state" "$r/infra/lib/tf.sh" apply ../x.tfplan >/dev/null 2>&1 && bad "path traversal rejected" || ok "path traversal rejected"
exit $fail
