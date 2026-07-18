#!/bin/sh
# NeonCore 5G packet tracer.
# Captures N2 (SCTP/NGAP), N4 (PFCP), N3 (GTP-U), SBI (HTTP/2) and ICMP (UE connection tests)
# traffic seen on this node, rotating and retaining PCAP files on a persistent volume.
set -eu

mkdir -p "$PCAP_DIR"

# Retention loop: drop rotated captures older than RETENTION_MINUTES.
(
  while true; do
    find "$PCAP_DIR" -name '*.pcap*' -mmin "+${RETENTION_MINUTES}" -delete 2>/dev/null || true
    sleep 60
  done
) &

exec tcpdump -i any -n \
  -w "${PCAP_DIR}/neoncore-%Y%m%d-%H%M%S.pcap" \
  -G "$ROTATE_SECONDS" -C "$MAX_FILE_MB" -z gzip \
  '(sctp) or (udp port 8805) or (udp port 2152) or (tcp port 7777) or icmp'
