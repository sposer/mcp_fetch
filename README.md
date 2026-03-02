## Offline Deployment

If you need to run this server in an offline environment (where `playwright install` cannot access the internet), follow these steps:

1.  **On an online machine:**
    Run the provided helper script to download the necessary browser binaries (Chromium) to a local directory (`libs/browsers`).
    
    This script automatically detects the required Playwright revision and downloads binaries for **both Windows (win64) and Linux**.

    ```bash
    uv run scripts/download_browsers.py
    ```

    This will create a `libs/browsers` directory containing the browser binaries (e.g., `chromium-<revision>`).

2.  **Transfer files:**
    Copy the entire project (or the installed package) AND the `libs/browsers` directory to your offline machine.

3.  **Configure environment:**
    On the offline machine, set the `PLAYWRIGHT_BROWSERS_PATH` environment variable to point to the `libs/browsers` directory before running the server.

    **Windows (PowerShell):**
    ```powershell
    $env:PLAYWRIGHT_BROWSERS_PATH = "C:\path\to\mcp-fetch\libs\browsers"
    mcp-fetch
    ```

    **Linux/macOS:**
    ```bash
    export PLAYWRIGHT_BROWSERS_PATH=/path/to/mcp-fetch/libs/browsers
    mcp-fetch
    ```

    **MCP Client Config (e.g., Claude/Trae):**
    Add the environment variable to your MCP settings.

    ```json
    {
      "mcpServers": {
        "fetch": {
          "command": "mcp-fetch",
          "args": [],
          "env": {
            "PLAYWRIGHT_BROWSERS_PATH": "E:\\Private\\Mcp\\fetch\\libs\\browsers",
            "MCP_FETCH_AUTO_INSTALL_PLAYWRIGHT": "0"
          }
        }
      }
    }
    ```

    *Note: Setting `MCP_FETCH_AUTO_INSTALL_PLAYWRIGHT=0` prevents the server from attempting to download browsers if they are missing, which fails immediately in offline mode.*
