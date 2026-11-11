terraform {
  required_version = ">= 1.6"

  required_providers {
    proxmox = {
      source  = "bpg/proxmox"
      version = "0.121.0"
    }
  }

  # State is local and lives outside the repo; infra/lib/tf.sh passes
  # -backend-config=path=<state dir>/terraform.tfstate (dir mode 700).
  backend "local" {}
}
