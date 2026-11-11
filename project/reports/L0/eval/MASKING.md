# Masking note (push preparation)

After the E6(a) runs recorded here, the Windows user name inside the quoted `DEVLOG.md:41` line was
replaced with `<windows-user>` in the five `allowlist-hits.txt` files (close/wsl-final, close/wsl,
run-2c-fromzero/wsl, run-2b-fromzero/wsl, wsl). Only that string changed. The E6(a) scan was not
re-run on the masked files, so the pass/fail counts are those of the original runs.
