#!/usr/bin/env python3
"""Fail-closed Terraform plan guard (security review S-B2).

    plan_guard.py PLAN_JSON            # PLAN_JSON = output of `terraform show -json <planfile>`

Exit codes
  0   safe (updates must keep vm_id/node_name equal to TF_VAR_vm_id/TF_VAR_node_name): only create / update / read / no-op actions, inside the expected pool
  1   refused (fail closed): parse error, missing file, wrong shape, empty resource_changes
      with a non-empty diff, unknown action, foreign resource type, or wrong pool
  10  needs confirmation: "delete" appears in some resource's actions (replace or delete).
      Without --confirm this is just reported; with --confirm the typed confirmation below
      runs and the exit code is 0 only if it succeeds.

Confirmation (--confirm): every affected address must be typed on /dev/tty. It refuses with
no usable TTY, when CLAUDECODE or CLAUDE_CODE_ENTRYPOINT is set, or when NEONCORE_ALLOW_REPLACE exists at all. There
is no override variable.

Only addresses and actions are printed, never attribute values.
"""
import json
import os
import sys

KNOWN_ACTIONS = {"no-op", "create", "read", "update", "delete"}
ALLOWED_TYPES = {"proxmox_virtual_environment_vm"}


class Refused(Exception):
    pass


def load(path):
    try:
        with open(path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
    except FileNotFoundError:
        raise Refused("plan json is missing")
    except (OSError, ValueError):
        raise Refused("plan json could not be parsed")
    if not isinstance(data, dict):
        raise Refused("plan json has the wrong shape")
    return data


def _has_resources(module):
    if not isinstance(module, dict):
        return False
    if module.get("resources"):
        return True
    return any(_has_resources(m) for m in module.get("child_modules") or [])


def has_diff(data):
    """True when the plan describes something even though resource_changes is empty."""
    pv = data.get("planned_values")
    if isinstance(pv, dict):
        if _has_resources(pv.get("root_module")):
            return True
        if pv.get("outputs"):
            return True
    if data.get("output_changes"):
        return True
    return False


def evaluate(data, pool=None, vm_id=None, node=None):
    """Return (rows, needs_confirm). rows = [(address, actions)]. Raises Refused."""
    if "resource_changes" not in data:
        # terraform omits the key entirely when there are no changes at all
        if has_diff(data):
            raise Refused("resource_changes is absent but the plan has a diff")
        return [], []
    rc = data["resource_changes"]
    if not isinstance(rc, list):
        raise Refused("resource_changes has the wrong shape")
    if not rc:
        if has_diff(data):
            raise Refused("resource_changes is empty but the plan has a diff")
        return [], []
    rows, confirm = [], []
    for item in rc:
        if not isinstance(item, dict):
            raise Refused("resource_changes entry has the wrong shape")
        addr = item.get("address")
        change = item.get("change")
        if not isinstance(addr, str) or not addr or not isinstance(change, dict):
            raise Refused("resource_changes entry is incomplete")
        actions = change.get("actions")
        if not isinstance(actions, list) or not actions or not all(isinstance(a, str) for a in actions):
            raise Refused("actions missing or malformed for " + addr)
        unknown = [a for a in actions if a not in KNOWN_ACTIONS]
        if unknown:
            raise Refused("unknown action for " + addr)
        mode = item.get("mode")
        if mode == "managed":
            if item.get("type") not in ALLOWED_TYPES:
                raise Refused("resource type not allowed: " + str(item.get("type")))
            if item.get("provider_name") not in (
                "registry.terraform.io/bpg/proxmox",
            ):
                raise Refused("provider not allowed for " + addr)
            after = change.get("after")
            if not pool:
                raise Refused("expected pool is not set (TF_VAR_pool_id)")
            # The pool is checked on create (and replace); a non-dict "after" is refused (fail
            # closed). On update the VM resource ignores pool_id (the token cannot read pool
            # membership), so instead the identity must not move: vm_id and node_name unchanged
            # and equal to the expected TF_VAR values.
            if "create" in actions and (not isinstance(after, dict) or after.get("pool_id") != pool):
                raise Refused("pool mismatch or unreadable planned value for " + addr)
            if "update" in actions:
                if not vm_id or not node:
                    raise Refused("expected vm_id/node_name are not set (TF_VAR_vm_id, TF_VAR_node_name)")
                before = change.get("before")
                if not isinstance(before, dict) or not isinstance(after, dict):
                    raise Refused("update without readable before/after for " + addr)
                for side in (before, after):
                    if str(side.get("vm_id")) != str(vm_id) or side.get("node_name") != node:
                        raise Refused("update changes or misses vm_id/node_name for " + addr)
        elif mode != "data":
            raise Refused("unknown resource mode for " + addr)
        rows.append((addr, actions))
        if "delete" in actions:
            confirm.append(addr)
    return rows, confirm


def confirm_on_tty(addresses, tty_in=None, tty_out=None, env=None):
    """Typed confirmation. Returns None on success, or a refusal string."""
    env = os.environ if env is None else env
    if "NEONCORE_ALLOW_REPLACE" in env:
        return "NEONCORE_ALLOW_REPLACE is not an override and must not be set"
    if env.get("CLAUDECODE") or env.get("CLAUDE_CODE_ENTRYPOINT"):
        return "refusing to confirm a replace/delete from inside Claude Code"
    own = []
    try:
        if tty_in is None:
            tty_in = open("/dev/tty", "r")
            own.append(tty_in)
        if tty_out is None:
            tty_out = open("/dev/tty", "w")
            own.append(tty_out)
    except OSError:
        return "no TTY available to confirm a replace/delete"
    try:
        if not tty_in.isatty():
            return "no TTY available to confirm a replace/delete"
        tty_out.write("This plan deletes or replaces:\n")
        for a in addresses:
            tty_out.write("  " + a + "\n")
        for a in addresses:
            tty_out.write("Type the resource address to confirm: ")
            tty_out.flush()
            line = tty_in.readline()
            if line.strip() != a:
                return "confirmation did not match"
        return None
    finally:
        for f in own:
            f.close()


def main(argv):
    confirm = False
    args = []
    for a in argv[1:]:
        if a == "--confirm":
            confirm = True
        else:
            args.append(a)
    if len(args) != 1:
        print("usage: plan_guard.py [--confirm] PLAN_JSON", file=sys.stderr)
        return 1
    try:
        data = load(args[0])
        rows, need = evaluate(data, os.environ.get("TF_VAR_pool_id") or None,
                              os.environ.get("TF_VAR_vm_id") or None,
                              os.environ.get("TF_VAR_node_name") or None)
    except Refused as exc:
        print("plan_guard: REFUSED: " + str(exc), file=sys.stderr)
        return 1
    counts = {}
    for addr, actions in rows:
        print("%s %s" % (addr, "+".join(actions)))
        key = "+".join(actions)
        counts[key] = counts.get(key, 0) + 1
    print("summary: " + (", ".join("%d %s" % (v, k) for k, v in sorted(counts.items())) or "no changes"))
    if need:
        if not confirm:
            print("plan_guard: needs confirmation (delete/replace): " + ", ".join(need), file=sys.stderr)
            return 10
        err = confirm_on_tty(need)
        if err:
            print("plan_guard: REFUSED: " + err, file=sys.stderr)
            return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
