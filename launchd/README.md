# launchd hourly sync

Install the local hourly Glitchslate runner:

```bash
./scripts/install_launchd.sh
```

The LaunchAgent runs `main.py` once when loaded and then every hour. It uses the repo directory as the working directory, so `.env`, `config.yaml`, `glitchslate.db`, and generated assets resolve the same way as a manual run.

Logs are written to:

```text
logs/launchd.out.log
logs/launchd.err.log
```

Unload and remove the LaunchAgent:

```bash
./scripts/uninstall_launchd.sh
```

Override the Python executable during install if needed:

```bash
PYTHON_BIN=/path/to/python3 ./scripts/install_launchd.sh
```
