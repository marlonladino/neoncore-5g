"""NeonCore 5G Control Center -- a cyberpunk Textual TUI for the NeonCore 5G testbed.

Deploy/teardown the Kubernetes infrastructure, watch pod health live, trigger UE
connection tests, and pull the latest packet-trace summaries -- all from one terminal.
"""

import os

from textual.app import App, ComposeResult
from textual.containers import Horizontal, Vertical
from textual.screen import ModalScreen
from textual.widgets import Button, DataTable, Footer, Input, Label, RichLog, Static

from . import k8s

PHASE_COLORS = {
    "Running": "#39ff14",
    "Completed": "#00fff9",
    "Succeeded": "#00fff9",
    "Pending": "#ffd400",
    "ContainerCreating": "#ffd400",
}
DEFAULT_COLOR = "#ff2fd6"  # anything unexpected (CrashLoopBackOff, Error, ImagePullBackOff...)


class ConfirmScreen(ModalScreen[bool]):
    """A neon Yes/No confirmation dialog, used before destructive actions."""

    def __init__(self, question: str, danger: bool = True) -> None:
        super().__init__()
        self.question = question
        self.danger = danger

    def compose(self) -> ComposeResult:
        with Vertical(id="confirm-dialog"):
            yield Label(self.question, id="confirm-question")
            with Horizontal(id="confirm-buttons"):
                yield Button(
                    "Confirm", id="yes",
                    classes="-danger" if self.danger else "-safe",
                )
                yield Button("Cancel", id="no")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        self.dismiss(event.button.id == "yes")


class ScenarioScreen(ModalScreen[dict | None]):
    """Parameter-input form for running a phase6 5G signaling scenario.

    Dismisses with a params dict (slug + msisdn + policy overrides) on one of the
    three scenario buttons, or None on Cancel.
    """

    def compose(self) -> ComposeResult:
        with Vertical(id="scenario-dialog"):
            yield Label("Run 5G Scenario", id="scenario-title")
            yield Label("UE MSISDN (10 digits, required)")
            yield Input(placeholder="0000000100", id="scenario-msisdn")
            yield Label("5QI / QoS index")
            yield Input(value="9", id="scenario-qos-index")
            yield Label("ARP priority level (1-15)")
            yield Input(value="8", id="scenario-arp-priority")
            yield Label("AMBR downlink / uplink (bps)")
            with Horizontal():
                yield Input(value="1000000000", id="scenario-ambr-down")
                yield Input(value="1000000000", id="scenario-ambr-up")
            with Horizontal(id="scenario-buttons"):
                yield Button("Initial Reg", id="initial-registration")
                yield Button("Reg Reject", id="registration-reject")
                yield Button("Deregister", id="deregistration")
            yield Button("Cancel", id="cancel", classes="-danger")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "cancel":
            self.dismiss(None)
            return
        msisdn_input = self.query_one("#scenario-msisdn", Input)
        msisdn = msisdn_input.value.strip()
        if not (msisdn.isdigit() and len(msisdn) == 10):
            msisdn_input.placeholder = "must be exactly 10 digits!"
            return
        params = {
            "slug": event.button.id,
            "msisdn": msisdn,
            "qos_index": self.query_one("#scenario-qos-index", Input).value.strip() or "9",
            "arp_priority": self.query_one("#scenario-arp-priority", Input).value.strip() or "8",
            "ambr_downlink_bps": self.query_one("#scenario-ambr-down", Input).value.strip()
            or "1000000000",
            "ambr_uplink_bps": self.query_one("#scenario-ambr-up", Input).value.strip()
            or "1000000000",
        }
        self.dismiss(params)


class NeonCoreApp(App[None]):
    CSS_PATH = "neoncore.tcss"
    TITLE = "NEONCORE 5G"

    BINDINGS = [
        ("d", "deploy", "Deploy"),
        ("t", "teardown", "Teardown"),
        ("p", "ping_test", "UE Ping Test"),
        ("l", "traces", "Latest Traces"),
        ("s", "scenarios", "Run Scenario"),
        ("c", "toggle_capture", "Start/Stop Capture"),
        ("r", "refresh", "Refresh Now"),
        ("q", "quit", "Quit"),
    ]

    active_capture_name: str | None = None

    def compose(self) -> ComposeResult:
        yield Static(
            "▓▒░ N E O N C O R E   5 G ░▒▓",
            id="title",
        )
        yield Static(
            "Kubernetes 5G Core Control Center — press a key below to act",
            id="subtitle",
        )
        with Horizontal(id="body"):
            with Vertical(id="left-pane"):
                yield DataTable(id="pod-table")
            with Vertical(id="right-pane"):
                yield RichLog(id="log", wrap=True, markup=True, highlight=False)
        yield Static("", id="status-bar")
        yield Footer()

    def on_mount(self) -> None:
        table = self.query_one("#pod-table", DataTable)
        table.add_columns("NS", "POD", "STATUS", "READY", "RESTARTS", "AGE")
        table.cursor_type = "row"
        self.query_one("#left-pane", Vertical).border_title = "5G CORE // POD STATUS"
        self.query_one("#right-pane", Vertical).border_title = "ACTION LOG"
        log = self.query_one("#log", RichLog)
        log.write("[bold #00fff9]NeonCore 5G Control Center online.[/]")
        log.write("[#39ff14]d[/]=deploy  [#39ff14]t[/]=teardown  [#39ff14]p[/]=ping test  "
                   "[#39ff14]l[/]=traces  [#39ff14]s[/]=scenario  [#39ff14]c[/]=start/stop capture  "
                   "[#39ff14]r[/]=refresh  [#39ff14]q[/]=quit")
        self.set_interval(4.0, self.refresh_pods)
        self.run_worker(self.refresh_pods(), exclusive=False)

    def set_status(self, text: str) -> None:
        self.query_one("#status-bar", Static).update(text)

    async def refresh_pods(self) -> None:
        try:
            pods = await k8s.get_pods()
        except Exception as e:  # kubectl missing, cluster unreachable, etc.
            self.set_status(f"[#ff2fd6]pod refresh failed: {e}[/]")
            return
        table = self.query_one("#pod-table", DataTable)
        table.clear()
        for pod in sorted(pods, key=lambda p: (p.namespace, p.name)):
            color = PHASE_COLORS.get(pod.phase, DEFAULT_COLOR)
            table.add_row(
                pod.namespace,
                pod.name,
                f"[{color}]{pod.phase}[/]",
                pod.ready,
                str(pod.restarts) if pod.restarts == 0 else f"[#ffd400]{pod.restarts}[/]",
                k8s.format_age(pod.age_seconds),
            )
        running = sum(1 for p in pods if p.phase == "Running")
        self.set_status(f"{running}/{len(pods)} pods Running — last refresh just now")

    # -- actions -----------------------------------------------------------------

    def action_refresh(self) -> None:
        self.run_worker(self.refresh_pods(), exclusive=True)

    def action_deploy(self) -> None:
        def check(confirmed: bool | None) -> None:
            if confirmed:
                self.run_worker(self._deploy(), exclusive=True)
        self.push_screen(
            ConfirmScreen(
                "Deploy the full NeonCore 5G stack "
                "(5G core + monitoring + tracer)?",
                danger=False,
            ),
            check,
        )

    async def _deploy(self) -> None:
        log = self.query_one("#log", RichLog)
        log.write("\n[bold #00fff9]=== DEPLOY ===[/]")
        async for line in k8s.deploy():
            log.write(f"[#39ff14]{line}[/]")
        await self.refresh_pods()

    def action_teardown(self) -> None:
        def check(confirmed: bool | None) -> None:
            if confirmed:
                self.run_worker(self._teardown(), exclusive=True)
        self.push_screen(
            ConfirmScreen(
                "Tear down neoncore + monitoring namespaces? "
                "This deletes ALL pods AND the packet-trace PVC. Irreversible.",
                danger=True,
            ),
            check,
        )

    async def _teardown(self) -> None:
        log = self.query_one("#log", RichLog)
        log.write("\n[bold #ff2fd6]=== TEARDOWN ===[/]")
        async for line in k8s.teardown():
            log.write(f"[#ff2fd6]{line}[/]")
        await self.refresh_pods()

    def action_ping_test(self) -> None:
        self.run_worker(self._ping_test(), exclusive=True)

    async def _ping_test(self) -> None:
        log = self.query_one("#log", RichLog)
        log.write("\n[bold #00fff9]=== UE CONNECTION TEST ===[/]")
        async for line in k8s.ue_ping_test():
            log.write(f"[#39ff14]{line}[/]")

    def action_traces(self) -> None:
        self.run_worker(self._traces(), exclusive=True)

    async def _traces(self) -> None:
        log = self.query_one("#log", RichLog)
        log.write("\n[bold #00fff9]=== LATEST NETWORK TRACES ===[/]")
        async for line in k8s.latest_traces():
            log.write(f"[#39ff14]{line}[/]")

    def action_scenarios(self) -> None:
        def check(params: dict | None) -> None:
            if params:
                self.run_worker(self._run_scenario(params), exclusive=True)
        self.push_screen(ScenarioScreen(), check)

    async def _run_scenario(self, params: dict) -> None:
        log = self.query_one("#log", RichLog)
        slug = params.pop("slug")
        msisdn = params.pop("msisdn")
        log.write(f"\n[bold #00fff9]=== SCENARIO: {slug}  msisdn={msisdn} ===[/]")
        async for line in k8s.run_scenario(slug, msisdn, **params):
            # AMF/UE log lines are dense with literal '[...]' (e.g. '[imsi-...]') --
            # escape before interpolating into Rich markup or it breaks the parser.
            safe_line = line.replace("[", "\\[")
            color = "#ff2fd6" if "[error]" in line or "FAIL" in line else "#39ff14"
            log.write(f"[{color}]{safe_line}[/]")

    def action_toggle_capture(self) -> None:
        if self.active_capture_name is None:
            self.run_worker(self._start_capture(), exclusive=True)
        else:
            self.run_worker(self._stop_capture(), exclusive=True)

    async def _start_capture(self) -> None:
        log = self.query_one("#log", RichLog)
        log.write("\n[bold #00fff9]=== MANUAL CAPTURE: START ===[/]")
        handle = await k8s.start_manual_capture()
        color = "#39ff14" if handle.ok else "#ff2fd6"
        log.write(f"[{color}]{handle.message}[/]")
        if handle.ok:
            self.active_capture_name = handle.name
            self.set_status(f"[#ffd400]Capturing ({handle.name}.pcap) — press c to stop[/]")

    async def _stop_capture(self) -> None:
        log = self.query_one("#log", RichLog)
        name = self.active_capture_name
        log.write(f"\n[bold #ff2fd6]=== MANUAL CAPTURE: STOP ({name}) ===[/]")
        try:
            async for line in k8s.stop_manual_capture(name):
                log.write(f"[#39ff14]{line}[/]")
        finally:
            # Always clear, even if stop_manual_capture raised partway through --
            # otherwise a failed stop leaves the app stuck thinking a capture that
            # no longer exists is still running, and 'c' would never start a new one.
            self.active_capture_name = None


def main() -> None:
    os.environ.setdefault("KUBECONFIG", os.path.expanduser("~/.kube/config"))
    NeonCoreApp().run()


if __name__ == "__main__":
    main()
