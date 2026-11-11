#!/usr/bin/env bash
# Tests for infra/lib/pin.sh and pin_check.sh against a local self-signed HTTPS server.
set -uo pipefail
here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
lib="$here/../lib"
t="$(mktemp -d)"; srvpid=""
trap '[ -z "$srvpid" ] || kill "$srvpid" 2>/dev/null; rm -rf "$t"' EXIT
fail=0
ok()  { echo "ok   $1"; }
bad() { echo "FAIL $1"; fail=1; }

grep -v '^ *#' "$lib/pin.sh" "$lib/pin_check.sh" | grep -Eq '(^|[^a-z])set -[a-z]*x' && bad "no set -x" || ok "no set -x"
grep -Eqi 'insecure|--no-check|-k ' <(grep -v '^ *#' "$lib/pin.sh" | grep -v 'PROXMOX_VE_INSECURE') && bad "no insecure option" || ok "no insecure option"

openssl req -x509 -newkey rsa:2048 -nodes -keyout "$t/k.pem" -out "$t/c.pem" -days 1 \
    -subj /CN=localhost -addext "subjectAltName=DNS:localhost,IP:127.0.0.1" 2>/dev/null
fp="$(openssl x509 -in "$t/c.pem" -noout -fingerprint -sha256 | sed 's/^[^=]*=//')"
# port 0 + ready file: no port collision, no startup sleep
cat >"$t/srv.py" <<PY
import http.server, ssl
class H(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        open("$t/requests","a").write(self.path+"\n")
        self.send_response(200); self.end_headers(); self.wfile.write(b"{}")
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

# run <fingerprint> <cmd...> with extra env from $XENV
run() { local f="$1"; shift
    env $XENV PVE_ENDPOINT="https://127.0.0.1:$port" PVE_API_TOKEN='fake@pve!t=secret' \
        PVE_TLS_FINGERPRINT="$f" NEONCORE_STATE_DIR="$t/state" "$@"; }
XENV=""

out="$(run "$fp" "$lib/pin_check.sh" 2>&1)"; [ $? -eq 0 ] && ok "good pin passes" || bad "good pin passes"
out="$(run "$fp" "$lib/pin_check.sh" --selftest-bad-pin 2>&1)"; rc=$?
[ $rc -ne 0 ] && echo "$out" | grep -qi mismatch && ok "--selftest-bad-pin always fails" || bad "--selftest-bad-pin always fails"
echo "$out" | grep -qF "$fp" && bad "selftest does not print fingerprint" || ok "selftest does not print fingerprint"
# the flip changes the first digit for every hex digit (unit test of the flip itself)
allflip=1
for d in 0 1 2 3 4 5 6 7 8 9 a b c d e f; do
    r="$(bash -c ". '$lib/pin.sh'; pin_flip_first ${d}abc")"
    [ "$r" != "${d}abc" ] && [ "${r:1}" = "abc" ] || allflip=0
done
[ $allflip = 1 ] && ok "bad-pin flip changes every first digit" || bad "bad-pin flip changes every first digit"
run "$fp" "$lib/pin_check.sh" --bogus >/dev/null 2>&1 && bad "unknown arg rejected" || ok "unknown arg rejected"

wrong="$(echo "$fp" | tr -d ':' | tr 'A-F' 'a-f')"; wrong="${wrong/#?/f}"; [ "$wrong" = "$(echo "$fp" | tr -d ':' | tr 'A-F' 'a-f')" ] && wrong="${wrong/#?/e}"
: >"$t/requests"
out="$(run "$wrong" "$lib/pve_get.sh" /version 2>&1)"; rc=$?
[ $rc -ne 0 ] && echo "$out" | grep -qi mismatch && ok "wrong leaf aborts" || bad "wrong leaf aborts"
[ ! -s "$t/requests" ] && ok "wrong leaf: no HTTP request reached the server" || bad "wrong leaf: no HTTP request"
echo "$out$(echo "$out")" | grep -qF "$wrong" && bad "no fingerprint in messages" || ok "no fingerprint in messages"
echo "$out" | grep -q secret && bad "no token in messages" || ok "no token in messages"

for e in PROXMOX_VE_INSECURE=true PROXMOX_VE_SSH_USERNAME=x TF_LOG=TRACE TF_LOG_PROVIDER=TRACE; do
    XENV="$e"; : >"$t/requests"
    run "$fp" "$lib/pin_check.sh" >/dev/null 2>&1 && bad "abort on ${e%%=*}" || ok "abort on ${e%%=*}"
done
XENV="PROXMOX_VE_INSECURE="; run "$fp" "$lib/pin_check.sh" >/dev/null 2>&1 && bad "abort on empty-but-set INSECURE" || ok "abort on empty-but-set INSECURE"
XENV=""

# pin_exec exports SSL_CERT_FILE (the leaf) and an empty SSL_CERT_DIR
res="$(run "$fp" bash -c ". '$lib/pin.sh'; pin_setup; pin_exec bash -c 'echo \$SSL_CERT_FILE; ls -A \"\$SSL_CERT_DIR\" | wc -l; stat -c %a \"\$SSL_CERT_DIR\"; grep -c BEGIN \"\$SSL_CERT_FILE\"'" 2>&1)"
[ "$(echo "$res" | sed -n 2p)" = 0 ] && [ "$(echo "$res" | sed -n 3p)" = 700 ] && [ "$(echo "$res" | sed -n 4p)" = 1 ] \
    && ok "SSL_CERT_FILE is a single leaf, SSL_CERT_DIR empty mode 700" || bad "SSL_CERT_* setup"
# leaf swapped after setup: pin_exec must refuse
res="$(run "$fp" bash -c ". '$lib/pin.sh'; pin_setup; cp /dev/null \"\$PIN_LEAF\"; echo x > \"\$PIN_LEAF\"; pin_exec echo RAN" 2>&1)"; rc=$?
[ $rc -ne 0 ] && ! echo "$res" | grep -q RAN && ok "re-hash before exec catches a swapped leaf" || bad "re-hash before exec"
ls "$t/state" 2>/dev/null | grep -q '^pin\.' && bad "run dir cleaned" || ok "run dir cleaned"
exit $fail
