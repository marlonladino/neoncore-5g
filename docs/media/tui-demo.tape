# NeonCore 5G TUI demo. Run from the repo root: vhs docs/media/tui-demo.tape
# Needs phase5/.venv (python3 -m venv phase5/.venv && phase5/.venv/bin/pip install -r phase5/requirements.txt)
# and a running lab. Keys used: r, p, l (read-only) and one s (initial-registration).
Output docs/media/tui-demo.gif
Output docs/media/tui-demo.txt

Set Shell "bash"
Set FontSize 14
Set Width 1100
Set Height 620
Set Framerate 12
Set Padding 12
Set TypingSpeed 40ms
Set Theme "Dracula"

Hide
Type "export PS1='$ ' && clear"
Enter
Show

Type "PYTHONPATH=phase5 phase5/.venv/bin/python3 -m neoncore_cli"
Enter
Sleep 4s

Type "r"
Sleep 3s
Type "p"
Sleep 8s
Type "l"
Sleep 4s

Type "s"
Sleep 2s
Type "0000000100"
Sleep 1s
Tab 5
Sleep 1s
Enter
Sleep 18s

Type "q"
Sleep 1s
