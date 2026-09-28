# IBM Bob ↔ EMAFIG on Windows

## Architecture

Use IBM Bob as the **MCP host** and EMAFIG as the **forensic tool server**.

```text
IBM Bob IDE
    |
    | MCP / stdio
    v
mcp_server.py
    |
    +--> Case Store
    +--> Deterministic forensic agents
    +--> Hash-chain audit ledger
    +--> Report compiler
    |
    v
JSON observations / evidence packages
```

This means you do **not** put a Bob API key into the normal local workflow.

IBM Bob officially supports project-scoped `.bob/mcp.json` files and local STDIO MCP servers. Bob launches the configured command as a subprocess and communicates over stdin/stdout.

## Install

From PowerShell in the project root:

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

Verify:

```powershell
python -c "from mcp.server import MCPServer; print('MCP OK')"
```

Expected:

```text
MCP OK
```

## Check the project configuration

Open:

```text
.bob\mcp.json
```

It must contain:

```json
{
  "mcpServers": {
    "emafg-forensics": {
      "command": "${workspaceFolder}/.venv/Scripts/python.exe",
      "args": ["${workspaceFolder}/mcp_server.py"],
      "cwd": "${workspaceFolder}",
      "env": {
        "PYTHONUNBUFFERED": "1",
        "PYTHONPATH": "${workspaceFolder}"
      },
      "disabled": false
    }
  }
}
```

## Enable it in Bob

1. Open this folder as the Bob workspace.
2. Open Bob's MCP settings.
3. Enable **Use MCP Servers**.
4. Confirm `emafg-forensics` appears.
5. Reload/restart the server if Bob asks.
6. Restart Bob if the server is not discovered.

## What Bob can call

```text
list_cases
get_case
get_agent_status
get_observations
get_hypotheses
get_contradictions
get_missing_evidence
verify_audit_ledger
start_investigation
review_observation
generate_report
get_visual_analysis
sign_off_case
```

## Demo prompts

Ask Bob:

```text
List the EMAFIG cases and show their status.
```

Then:

```text
For CASE-..., inspect every agent run and report which agents completed,
which had warnings, and which failed.
```

Then:

```text
Retrieve all observations for CASE-... and group them by forensic modality.
Do not infer a fake/real verdict. Preserve measurements and limitations.
```

Then:

```text
Show me all competing hypotheses for CASE-... and list which observations
support or contradict each one.
```

Then:

```text
Show every unresolved contradiction in CASE-... and propose the next
bounded forensic checks that could distinguish the explanations.
```

Then:

```text
Verify the audit ledger for CASE-...
```

Then:

```text
Generate the forensic report package for CASE-...
```

## Important

The current EMAFIG engine performs **intake + deterministic examination atomically** when a new file is uploaded through the GUI or `run.py`. The MCP layer is therefore primarily the Bob control/reasoning surface over the resulting case state.

For a new evidence file, first use the GUI:

```text
http://127.0.0.1:8000
```

Then Bob can operate on the created case.

## Why MCP instead of inventing a Bob REST endpoint

IBM Bob's current documented integration mechanism for external tools is MCP. Project-level MCP configuration lives in `.bob/mcp.json`, and local STDIO servers are launched by Bob as child processes. This keeps the local forensic evidence inside the controlled workspace.

The supplied project also retains `app/bob.py` as an optional HTTP reasoning boundary for environments where the hackathon provides a separate Bob inference gateway. That is secondary to the Bob IDE/MCP path documented here.

## Security

Keep MCP access bounded:
- Bob gets only the explicitly exposed forensic tools.
- Do not expose arbitrary shell execution.
- Do not expose evidence deletion.
- Do not allow Bob to overwrite the original evidence.
- Keep credentials out of `.bob/mcp.json`.
- Require human review before sign-off.

