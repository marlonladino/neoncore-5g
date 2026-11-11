# Every site value arrives as TF_VAR_* from the lab env file (loaded by scripts/labenv).
# Nothing here is a real value.

variable "node_name" {
  type        = string
  description = "Proxmox node name"
}

variable "vm_id" {
  type        = number
  description = "VMID inside the NeonCore range"
}

variable "pool_id" {
  type        = string
  description = "Dedicated NeonCore pool"
}

variable "datastore_id" {
  type        = string
  description = "VM disk storage (must support snapshots)"
}

variable "image_datastore_id" {
  type        = string
  description = "Image storage (unused with a template clone; kept for the env contract)"
  default     = null
}

variable "template_vm_id" {
  type        = number
  description = "Owner-made cloud-init template to clone (D5b)"
}

variable "bridge" {
  type        = string
  description = "Bridge for the VM NIC"
}

variable "vlan_id" {
  type        = number
  description = "Optional VLAN tag"
  default     = null
}

variable "ipv4_cidr" {
  type        = string
  description = "Static address with prefix, e.g. 192.0.2.10/24"
}

variable "gateway" {
  type        = string
  description = "IPv4 gateway"
}

variable "dns_servers" {
  type        = string
  description = "DNS servers as text, comma separated; brackets and quotes are tolerated, e.g. 192.0.2.1,192.0.2.2"
}

variable "vm_user" {
  type        = string
  description = "Dedicated key-only user created by cloud-init"
}

variable "ssh_public_key" {
  type        = string
  description = "Public key text; infra/lib/tf.sh fills it from LAB_SSH_PUBKEY_FILE"
}
