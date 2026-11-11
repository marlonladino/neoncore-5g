# Endpoint and API token come from PROXMOX_VE_ENDPOINT / PROXMOX_VE_API_TOKEN, which
# infra/lib/tf.sh maps from the lab env. TLS trust is the pinned leaf (SSL_CERT_FILE).
provider "proxmox" {
  insecure = false
}

locals {
  dns_servers = [
    for s in split(",", replace(replace(replace(var.dns_servers, "[", ""), "]", ""), "\"", "")) : trimspace(s)
    if trimspace(s) != ""
  ]
}

resource "proxmox_virtual_environment_vm" "lab" {
  name      = "neoncore-lab"
  node_name = var.node_name
  vm_id     = var.vm_id
  pool_id   = var.pool_id

  on_boot = false
  started = true

  agent {
    enabled = true
    # Without this the provider waits 15 min for agent data. Short on purpose; the agent
    # is installed by the base role.
    timeout = "30s"
  }

  # The API token deliberately lacks Pool.Audit, so the provider cannot read the VM's pool
  # membership and would plan an update on every run. The pool is set on create (and checked
  # by plan_guard.py); membership afterwards is owner-attested on the host.
  lifecycle {
    ignore_changes = [pool_id]
  }

  cpu {
    cores = 4
    type  = "x86-64-v3"
  }

  # No ballooning: floating = 0 disables it.
  memory {
    dedicated = 8192
    floating  = 0
  }

  clone {
    vm_id        = var.template_vm_id
    node_name    = var.node_name
    datastore_id = var.datastore_id
    full         = true
  }

  disk {
    datastore_id = var.datastore_id
    interface    = "scsi0"
    size         = 40
    discard      = "on"
  }

  network_device {
    bridge  = var.bridge
    vlan_id = var.vlan_id
  }

  # Cloud-init through the API only (no snippets, so no SSH to the Proxmox host).
  initialization {
    datastore_id = var.datastore_id

    user_account {
      username = var.vm_user
      keys     = [trimspace(var.ssh_public_key)]
    }

    ip_config {
      ipv4 {
        address = var.ipv4_cidr
        gateway = var.gateway
      }
    }

    dns {
      servers = local.dns_servers
    }
  }
}
