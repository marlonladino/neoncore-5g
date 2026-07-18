"""Headless smoke test for the NeonCore 5G TUI using Textual's Pilot API.

Not a full test suite -- just verifies the app mounts, the pod table populates from
a live cluster, and the key bindings dispatch without raising.
"""
import asyncio
from neoncore_cli.app import NeonCoreApp
from textual.widgets import DataTable


async def main() -> None:
    app = NeonCoreApp()
    async with app.run_test() as pilot:
        await pilot.pause(3.0)
        table = app.query_one("#pod-table", DataTable)
        print(f"pod-table rows after mount: {table.row_count}")
        assert table.row_count > 0, "expected at least one pod row"

        await pilot.press("r")
        await pilot.pause(1.0)
        print(f"pod-table rows after refresh: {table.row_count}")

        from textual.widgets import RichLog
        log = app.query_one("#log", RichLog)

        await pilot.press("p")
        await pilot.pause(6.0)  # ping -c 4 takes a few seconds
        ping_lines = [str(s) for s in log.lines[-8:]]
        print("--- ping test output (tail) ---")
        print("\n".join(ping_lines))

        await pilot.press("l")
        await pilot.pause(4.0)
        trace_lines = [str(s) for s in log.lines[-10:]]
        print("--- traces output (tail) ---")
        print("\n".join(trace_lines))

        await pilot.press("d")
        await pilot.pause(0.3)
        print("deploy confirm-dialog binding dispatched OK")
        await pilot.press("escape")

        print("SMOKE TEST PASSED")


if __name__ == "__main__":
    asyncio.run(main())
