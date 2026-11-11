#!/bin/sh
# NeonCore 5G packet tracer.
# Captures N2 (SCTP/NGAP), N4 (PFCP), N3 (GTP-U), SBI (HTTP/2) and ICMP (UE connection tests)
# traffic seen on this node, rotating and retaining PCAP files on a persistent volume.
set -eu

mkdir -p "$PCAP_DIR"

# Housekeeping loop (every 60 s): compress rotated captures, then drop old ones.
# tcpdump cannot do this itself: with -z the Ubuntu AppArmor profile "tcpdump" only allows
# exec of /{usr/,}bin/gzip, and in this image gzip is a busybox symlink, so every exec is denied.
# The file list is taken once; its newest entry is the capture tcpdump has open and is never
# compressed, renamed or deleted. Compression goes to a hidden temp name, then rename.
(
  while true; do
    files=$(ls -t "$PCAP_DIR"/neoncore-*.pcap* 2>/dev/null | grep -v -e '\.gz$' -e '\.tmp$' || true)
    cur=$(printf '%s\n' "$files" | head -n 1)
    for f in $(printf '%s\n' "$files" | tail -n +2); do
      tmp="$(dirname "$f")/.$(basename "$f").gz.tmp"
      if gzip -c "$f" >"$tmp" 2>/dev/null; then
        touch -r "$f" "$tmp" 2>/dev/null || true
        mv -f "$tmp" "$f.gz" && rm -f "$f"
      else
        rm -f "$tmp"
      fi
    done
    find "$PCAP_DIR" -name '*.pcap*' ! -path "${cur:-/nonexistent}" -mmin "+${RETENTION_MINUTES}" -delete 2>/dev/null || true
    sleep 60
  done
) &

exec tcpdump -i any -n \
  -w "${PCAP_DIR}/neoncore-%Y%m%d-%H%M%S.pcap" \
  -G "$ROTATE_SECONDS" -C "$MAX_FILE_MB" \
  '(sctp) or (udp port 8805) or (udp port 2152) or (tcp port 7777) or icmp'
