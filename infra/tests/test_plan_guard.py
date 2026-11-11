"""Tests for infra/lib/plan_guard.py (run: python3 -I infra/tests/test_plan_guard.py)."""
import io
import json
import os
import subprocess
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
GUARD = os.path.join(HERE, "..", "lib", "plan_guard.py")
sys.path.insert(0, os.path.join(HERE, "..", "lib"))
import plan_guard  # noqa: E402

PROV = "registry.terraform.io/bpg/proxmox"


def rc(address="proxmox_virtual_environment_vm.lab", actions=("create",), pool="p1",
       mode="managed", type_="proxmox_virtual_environment_vm", provider=PROV):
    after = {"pool_id": pool, "vm_id": 100, "node_name": "n1"} if "delete" not in actions or len(actions) > 1 else None
    before = {"pool_id": pool, "vm_id": 100, "node_name": "n1"}
    return {"address": address, "mode": mode, "type": type_, "provider_name": provider,
            "change": {"actions": list(actions), "before": before, "after": after}}


def plan(*changes, **extra):
    d = {"format_version": "1.2", "resource_changes": list(changes)}
    d.update(extra)
    return d


class Tmp(unittest.TestCase):
    def run_guard(self, data, env=None, raw=None, args=()):
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "plan.json")
            if raw is not None:
                with open(p, "w") as fh:
                    fh.write(raw)
            elif data is not None:
                with open(p, "w") as fh:
                    json.dump(data, fh)
            e = {k: v for k, v in os.environ.items() if k not in ("CLAUDECODE", "CLAUDE_CODE_ENTRYPOINT", "NEONCORE_ALLOW_REPLACE")}
            e["TF_VAR_pool_id"] = "p1"
            e["TF_VAR_vm_id"] = "100"
            e["TF_VAR_node_name"] = "n1"
            e.update(env or {})
            return subprocess.run([sys.executable, "-I", GUARD, *args, p], env=e,
                                  capture_output=True, text=True, stdin=subprocess.DEVNULL)


class Guard(Tmp):
    def test_create_only_passes(self):
        r = self.run_guard(plan(rc()))
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("1 create", r.stdout)

    def test_noop_and_update_pass(self):
        self.assertEqual(self.run_guard(plan(rc(actions=("no-op",)), rc("proxmox_virtual_environment_vm.b", ("update",)))).returncode, 0)

    def test_no_changes_without_diff_passes(self):
        r = self.run_guard({"format_version": "1.2", "planned_values": {"root_module": {}}})
        self.assertEqual(r.returncode, 0)
        self.assertIn("no changes", r.stdout)

    def test_parse_error_fails_closed(self):
        self.assertEqual(self.run_guard(None, raw="{not json").returncode, 1)

    def test_empty_file_fails_closed(self):
        self.assertEqual(self.run_guard(None, raw="").returncode, 1)

    def test_missing_file_fails_closed(self):
        r = subprocess.run([sys.executable, "-I", GUARD, "/nonexistent/plan.json"],
                           capture_output=True, text=True, env={"TF_VAR_pool_id": "p1"})
        self.assertEqual(r.returncode, 1)

    def test_not_an_object_fails_closed(self):
        self.assertEqual(self.run_guard([1, 2]).returncode, 1)

    def test_empty_resource_changes_with_diff_fails(self):
        d = {"resource_changes": [], "planned_values": {"root_module": {"resources": [{"address": "x"}]}}}
        self.assertEqual(self.run_guard(d).returncode, 1)

    def test_empty_resource_changes_with_output_diff_fails(self):
        self.assertEqual(self.run_guard({"resource_changes": [], "output_changes": {"o": {}}}).returncode, 1)

    def test_missing_resource_changes_with_diff_fails(self):
        d = {"planned_values": {"root_module": {"child_modules": [{"resources": [{"address": "x"}]}]}}}
        self.assertEqual(self.run_guard(d).returncode, 1)

    def test_resource_changes_wrong_type_fails(self):
        self.assertEqual(self.run_guard({"resource_changes": {}}).returncode, 1)

    def test_unknown_action_fails(self):
        self.assertEqual(self.run_guard(plan(rc(actions=("create", "explode")))).returncode, 1)

    def test_missing_actions_fails(self):
        d = plan(rc())
        del d["resource_changes"][0]["change"]["actions"]
        self.assertEqual(self.run_guard(d).returncode, 1)

    def test_empty_actions_fails(self):
        self.assertEqual(self.run_guard(plan(rc(actions=()))).returncode, 1)

    def test_delete_variants_need_confirmation(self):
        for acts in (("delete",), ("delete", "create"), ("create", "delete")):
            r = self.run_guard(plan(rc(actions=acts)))
            self.assertEqual(r.returncode, 10, acts)
            self.assertIn("needs confirmation", r.stderr)

    def test_delete_with_other_resource_still_flags(self):
        r = self.run_guard(plan(rc(), rc("proxmox_virtual_environment_vm.old", ("delete",))))
        self.assertEqual(r.returncode, 10)
        self.assertIn("proxmox_virtual_environment_vm.old", r.stderr)

    def test_foreign_resource_type_fails(self):
        self.assertEqual(self.run_guard(plan(rc(type_="proxmox_virtual_environment_pool"))).returncode, 1)

    def test_foreign_provider_fails(self):
        self.assertEqual(self.run_guard(plan(rc(provider="registry.terraform.io/evil/proxmox"))).returncode, 1)

    def test_wrong_pool_fails(self):
        self.assertEqual(self.run_guard(plan(rc(pool="other"))).returncode, 1)

    def test_update_with_ignored_pool_passes(self):
        d = plan(rc(actions=("update",), pool=None))
        self.assertEqual(self.run_guard(d).returncode, 0)

    def test_create_with_non_dict_after_fails(self):
        for after in (None, "x", [], 5):
            d = plan(rc())
            d["resource_changes"][0]["change"]["after"] = after
            self.assertEqual(self.run_guard(d).returncode, 1, after)

    def test_create_without_after_key_fails(self):
        d = plan(rc())
        del d["resource_changes"][0]["change"]["after"]
        self.assertEqual(self.run_guard(d).returncode, 1)

    def _upd(self, side, key, val):
        d = plan(rc(actions=("update",)))
        d["resource_changes"][0]["change"][side][key] = val
        return d

    def test_update_vm_id_changed_fails(self):
        self.assertEqual(self.run_guard(self._upd("after", "vm_id", 101)).returncode, 1)
        self.assertEqual(self.run_guard(self._upd("before", "vm_id", 101)).returncode, 1)

    def test_update_node_changed_fails(self):
        self.assertEqual(self.run_guard(self._upd("after", "node_name", "other")).returncode, 1)
        self.assertEqual(self.run_guard(self._upd("before", "node_name", "other")).returncode, 1)

    def test_update_identity_must_match_env(self):
        d = plan(rc(actions=("update",)))
        self.assertEqual(self.run_guard(d, env={"TF_VAR_vm_id": "7"}).returncode, 1)
        self.assertEqual(self.run_guard(d, env={"TF_VAR_node_name": "zz"}).returncode, 1)

    def test_update_env_unset_fails_closed(self):
        d = plan(rc(actions=("update",)))
        self.assertEqual(self.run_guard(d, env={"TF_VAR_vm_id": ""}).returncode, 1)

    def test_update_missing_before_fails(self):
        d = plan(rc(actions=("update",)))
        del d["resource_changes"][0]["change"]["before"]
        self.assertEqual(self.run_guard(d).returncode, 1)

    def test_update_vm_id_string_form_ok(self):
        self.assertEqual(self.run_guard(self._upd("after", "vm_id", "100")).returncode, 0)

    def test_replace_with_wrong_pool_fails(self):
        self.assertEqual(self.run_guard(plan(rc(actions=("delete", "create"), pool="other"))).returncode, 1)

    def test_pool_not_set_fails_closed(self):
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "p.json")
            with open(p, "w") as fh:
                json.dump(plan(rc()), fh)
            r = subprocess.run([sys.executable, "-I", GUARD, p], capture_output=True, text=True, env={})
            self.assertEqual(r.returncode, 1)

    def test_data_source_read_passes(self):
        d = plan(rc(), {"address": "data.x", "mode": "data", "change": {"actions": ["read"]}})
        self.assertEqual(self.run_guard(d).returncode, 0)

    def test_unknown_mode_fails(self):
        d = plan({"address": "x", "mode": "weird", "change": {"actions": ["create"]}})
        self.assertEqual(self.run_guard(d).returncode, 1)

    def test_no_attribute_values_printed(self):
        d = plan(rc())
        d["resource_changes"][0]["change"]["after"]["secret"] = "TOPSECRETVALUE"
        r = self.run_guard(d)
        self.assertNotIn("TOPSECRETVALUE", r.stdout + r.stderr)


class Confirm(Tmp):
    def tty(self, text):
        class T(io.StringIO):
            def isatty(self):
                return True
        return T(text), io.StringIO()

    def test_typed_address_confirms(self):
        i, o = self.tty("a.b\nc.d\n")
        self.assertIsNone(plan_guard.confirm_on_tty(["a.b", "c.d"], i, o, env={}))

    def test_wrong_text_refused(self):
        i, o = self.tty("yes\n")
        self.assertIsNotNone(plan_guard.confirm_on_tty(["a.b"], i, o, env={}))

    def test_empty_answer_refused(self):
        i, o = self.tty("")
        self.assertIsNotNone(plan_guard.confirm_on_tty(["a.b"], i, o, env={}))

    def test_not_a_tty_refused(self):
        self.assertIsNotNone(plan_guard.confirm_on_tty(["a.b"], io.StringIO("a.b\n"), io.StringIO(), env={}))

    def test_claudecode_refused_even_with_correct_input(self):
        i, o = self.tty("a.b\n")
        self.assertIsNotNone(plan_guard.confirm_on_tty(["a.b"], i, o, env={"CLAUDECODE": "1"}))

    def test_entrypoint_refused_even_with_correct_input(self):
        i, o = self.tty("a.b\n")
        self.assertIsNotNone(plan_guard.confirm_on_tty(["a.b"], i, o, env={"CLAUDE_CODE_ENTRYPOINT": "cli"}))

    def test_override_variable_refused_even_if_empty(self):
        i, o = self.tty("a.b\n")
        self.assertIsNotNone(plan_guard.confirm_on_tty(["a.b"], i, o, env={"NEONCORE_ALLOW_REPLACE": ""}))

    def test_cli_confirm_without_tty_refuses(self):
        # stdin is not a TTY; in CI there is also usually no /dev/tty. CLAUDECODE makes it deterministic.
        r = self.run_guard(plan(rc(actions=("delete", "create"))), env={"CLAUDECODE": "1"}, args=("--confirm",))
        self.assertEqual(r.returncode, 1)

    def test_cli_override_env_refuses(self):
        r = self.run_guard(plan(rc(actions=("delete",))), env={"NEONCORE_ALLOW_REPLACE": "1"}, args=("--confirm",))
        self.assertEqual(r.returncode, 1)


if __name__ == "__main__":
    unittest.main()
