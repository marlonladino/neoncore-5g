"""NeonCore 5G Control Center -- a cyberpunk Textual TUI for the NeonCore 5G testbed.

Deploy/teardown the Kubernetes infrastructure, watch pod health live, trigger UE
connection tests, and pull the latest packet-trace summaries -- all from one terminal.
"""

import os

from textual.app import App, ComposeResult
from textual.containers import Horizontal, Vertical
from textual.screen import ModalScreen
from textual.widgets import Button, DataTable, Footer, Label, RichLog, Static

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


class NeonCoreApp(App[None]):
    CSS_PATH = "neoncore.tcss"
    TITLE = "NEONCORE 5G"

    BINDINGS = [
        ("d", "deploy", "Deploy"),
        ("t", "teardown", "Teardown"),
        ("p", "ping_test", "UE Ping Test"),
        ("l", "traces", "Latest Traces"),
        ("r", "refresh", "Refresh Now"),
        ("q", "quit", "Quit"),
    ]

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
                   "[#39ff14]l[/]=traces  [#39ff14]r[/]=refresh  [#39ff14]q[/]=quit")
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


def main() -> None:
    os.environ.setdefault("KUBECONFIG", os.path.expanduser("~/.kube/config"))
    NeonCoreApp().run()


if __name__ == "__main__":
    main()
