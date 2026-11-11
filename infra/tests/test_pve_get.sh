#!/usr/bin/env bash
# Tests for infra/lib/pve_get.sh against a local self-signed HTTPS server (fake token).
set -uo pipefail
here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
script="$here/../lib/pve_get.sh"
t="$(mktemp -d)"; srvpid=""
trap '[ -z "$srvpid" ] || kill "$srvpid" 2>/dev/null; rm -rf "$t"' EXIT
fail=0
ok()  { echo "ok   $1"; }
bad() { echo "FAIL $1"; fail=1; }

# static checks
grep -v '^ *#' "$script" | grep -Eq '(^|[^a-z])set -[a-z]*x' && bad "no set -x" || ok "no set -x"
grep -Eq 'curl[^|]*(-X|--request|-d |--data)' "$script" && bad "GET only" || ok "GET only"
grep -n 'PVE_API_TOKEN' "$script" | grep -Eq 'curl .*PVE_API_TOKEN' && bad "token not in argv" || ok "token not in argv"

openssl req -x509 -newkey rsa:2048 -nodes -keyout "$t/k.pem" -out "$t/c.pem" -days 1 \
    -subj /CN=localhost -addext "subjectAltName=DNS:localhost,IP:127.0.0.1" 2>/dev/null
fp="$(openssl x509 -in "$t/c.pem" -noout -fingerprint -sha256 | sed 's/^[^=]*=//')"
# port 0 + ready file: no port collision, no startup sleep
cat >"$t/srv.py" <<PY
import http.server, ssl, json, sys
class H(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        ok = self.headers.get("Authorization","") == "PVEAPIToken=fake@pve!t=secret"
        self.send_response(200 if ok else 401); self.end_headers()
        self.wfile.write(json.dumps({"data":{"path":self.path,"auth":ok}}).encode())
    def do_POST(self): self.send_response(405); self.end_headers()
    def log_message(self,*a): pass
s = http.server.ThreadingHTTPServer(("127.0.0.1", 0), H)
c = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER); c.load_cert_chain("$t/c.pem","$t/k.pem")
s.socket = c.wrap_socket(s.socket, server_side=True)
open("$t/port.tmp","w").write(str(s.server_address[1])); __import__("os").rename("$t/port.tmp","$t/port")
s.serve_forever()
PY
python3 -I "$t/srv.py" & srvpid=$!
for _ in $(seq 100); do [ -s "$t/port" ] && break; sleep 0.1; done
port="$(cat "$t/port" 2>/dev/null)"; [ -n "$port" ] || { echo "FAIL server did not start"; exit 1; }

run() { env PVE_ENDPOINT="https://127.0.0.1:$port" PVE_API_TOKEN='fake@pve!t=secret' \
        PVE_TLS_FINGERPRINT="$1" NEONCORE_STATE_DIR="$t/state" "$script" "$2"; }

out="$(run "$fp" /version 2>&1)"; rc=$?
[ $rc -eq 0 ] && echo "$out" | grep -q '"auth": *true' && ok "pinned GET works, token sent" || bad "pinned GET works ($rc)"
lower="$(echo "$fp" | tr -d ':' | tr 'A-F' 'a-f')"
run "$lower" /version >/dev/null 2>&1 && ok "fingerprint normalized (lowercase, no colons)" || bad "normalization"
badfp="${fp/#?/0}"; [ "$badfp" = "$fp" ] && badfp="${fp/#?/1}"
out="$(run "$badfp" /version 2>&1)"; rc=$?
[ $rc -ne 0 ] && echo "$out" | grep -qi mismatch && ok "wrong fingerprint aborts" || bad "wrong fingerprint aborts"
echo "$out" | grep -qF "$fp" && bad "fingerprint not printed" || ok "fingerprint not printed"
echo "$out" | grep -q 'secret' && bad "token not printed" || ok "token not printed"
run "$fp" --san >/dev/null 2>&1 && ok "SAN check covers 127.0.0.1" || bad "SAN check"
run "$fp" 'version' >/dev/null 2>&1 && bad "relative path rejected" || ok "relative path rejected"
run "$fp" '/a"b' >/dev/null 2>&1 && bad "quote rejected" || ok "quote rejected"
for ok_p in /version /cluster/resources '/cluster/resources?type=vm' /pools /pools/p1 /access/permissions /storage /storage/s1 \
    /nodes/n1/status /nodes/n1/qemu/100/status/current /nodes/n1/qemu/100/snapshot \
    /nodes/n1/tasks/UPID:n1:0001:0002:0003:qmstart:100:u@pve!t:/status \
    '/nodes/n1/qemu/100/agent/file-read?file=%2Fetc%2Fssh%2Fssh_host_ed25519_key.pub'; do
    run "$fp" "$ok_p" >/dev/null 2>&1 && ok "allowed: $ok_p" || bad "allowed: $ok_p"
done
for no_p in /etc/shadow / /nodes /nodes/n1/qemu/100/config /nodes/n1/qemu/100/agent/exec /nodes/n1/qemu/100/agent/get-fsinfo \
    '/nodes/n1/qemu/100/agent/file-read?file=%2Fetc%2Fshadow' \
    '/nodes/n1/qemu/100/agent/file-read?file=/etc/shadow' \
    '/nodes/n1/qemu/100/agent/file-read?file=%2Fetc%2Fssh%2Fssh_host_ed25519_key.pub&x=1' \
    '/nodes/n1/qemu/100/agent/file-read?file=%2Fetc%2Fssh%2Fssh_host_ed25519_key.pub%2F..%2Fshadow' \
    '/nodes/n1/qemu/100/agent/file-read?file=%2Fetc%2Fssh%2Fssh_host_ed25519_key' \
    '/version/../access/users' /storage/../nodes /version/x /versions /pools/p1/x /access/users /access/ticket \
    '/version?a=b;c' '/version?a=%2e' /nodes/n1/qemu/100/vncproxy /nodes/n1/execute /nodes/n1/tasks /storage/s1/content//x; do
    run "$fp" "$no_p" >/dev/null 2>&1 && bad "refused: $no_p" || ok "refused: $no_p"
done
out="$(run "$fp" /etc/shadow 2>&1)"; echo "$out" | grep -q 'allowlist' && ok "refusal names the allowlist" || bad "refusal names the allowlist"
ls "$t/state" 2>/dev/null | grep -q pve_get && bad "run dir cleaned" || ok "run dir cleaned"
exit $fail
