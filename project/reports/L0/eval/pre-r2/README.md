# L0 pre-R2 informational (TB6 MTU), 2026-11-10

Evaluator, commit 3b89588. Informational only, with no threshold. This is not an R1 or R2 result.

- `mtu.txt`: pod-side MTUs from `kubectl -n neoncore exec deploy/<pod> -- ip -o link show`, read-only, captured 2026-11-10T14:23:49Z. Values: gnb eth0 1450, upf eth0 1450, upf ogstun 1500, ue eth0 1450, ue uesimtun0 1400.
- uesimtun0 is 1400, the same number as the SMF `mtu: 1400`. This does not show that the SMF value reached the UE. The PDU session establishment accept carries no IPv4 Link MTU ePCO container (telco build review R1, MTU point), so 1400 is presumably UERANSIM's own local setting (not verified).
- Not captured: the VM NIC, `flannel.1` and `cni0` need a shell on the VM. Lab-ops gets the command from `evals/l0/mtu_check.sh --print-node-commands`. The Proxmox bridge MTU and VLAN tag need the owner or lab-ops on the host.
- Not tested: `ping -M do -s 1372 -I uesimtun0 -c 3 -W 2 8.8.8.8`. It runs in R2 through `ping_check.sh --pmtu`, without a threshold. The evaluator was limited to read-only `kubectl get` and `exec` reads for this step.
- GTP-U overhead (36 or 44 bytes): not verified, because no GTP-U frame was captured in R1.
