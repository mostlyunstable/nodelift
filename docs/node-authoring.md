# Writing a Nodecraft node

A node type is two things: a **definition** (metadata the UI shows) and an **implementation** (what runs).
Both live in [`backend/app/domain/nodes.py`](../backend/app/domain/nodes.py) as `NodeDefinition` and the `NodeImpl` protocol.

## The contract

```python
from typing import Any, ClassVar
from app.domain.nodes import NodeContext, NodeDefinition, NodeResult
from app.domain.ports import NodeError

class UpperNode:
    definition: ClassVar[NodeDefinition] = NodeDefinition(
        type="demo.upper",              # stable id, stored in saved workflows; never rename it
        title="Uppercase",
        category="Demo",
        description="Uppercases input['text'].",
        config_schema={"type": "object", "properties": {}},   # JSON Schema (documentation / forms)
        default_config={},                                     # config for a freshly added node
    )

    def validate_config(self, config: dict[str, Any]) -> list[str]:
        return []                        # static checks only: no network, no disk. Return problems.

    async def execute(self, ctx: NodeContext, input_data: Any, config: dict[str, Any]) -> NodeResult:
        if not isinstance(input_data, dict) or "text" not in input_data:
            return NodeResult(status="failed", duration_ms=0,
                              error=NodeError(type="invalid_config", message="input needs 'text'"))
        return NodeResult(status="succeeded", output={"text": input_data["text"].upper()}, duration_ms=0)

def register(registry):                  # called once at startup
    registry.register(UpperNode())
```

### Rules for `execute`
- **Return failures, don't raise.** Use `NodeResult(status="failed", error=NodeError(type=..., message=...))`.
  Unexpected exceptions are caught by the run and recorded as a crashed run.
- **Input and output must be JSON-compatible** (dict, list, str, int, float, bool, None). Results over 5 MB are rejected.
- **Honour `ctx.timeout_s` and `ctx.cancel`.** `cancel` is an `asyncio.Event` set when the user cancels the run; stop
  promptly. Never block the event loop (use `asyncio` APIs or `asyncio.to_thread`).
- **Report `duration_ms`.** Add `logs=[LogLine(stream="stdout", text=...)]` for anything worth showing in the debugger.
- **Never log secrets.** Logs and events are stored and shown in the UI. Don't log query strings, headers or tokens.
- **Be explicit about idempotency.** Nodes are retried only if the workflow author sets `idempotent: true` and
  `retry`. Errors the engine retries: `runtime_error`, `timeout`, `worker_crashed`, `network_error`, `http_error`.
  Use `invalid_config`, `blocked_request`, `transform_error` for failures that cannot succeed on a retry.

### Error types
`syntax_error`, `missing_main`, `runtime_error`, `invalid_output`, `output_too_large`, `timeout`, `cancelled`,
`worker_crashed`, `invalid_config`, `transform_error`, `blocked_request`, `network_error`, `http_error`,
`response_too_large`. Add new ones to `ErrorType` in `domain/ports.py` (and the UI will show them as-is).

## Registering

**Built in:** add the class under `backend/app/nodes/builtin/` and register it in `default_registry()`
(`backend/app/nodes/__init__.py`). Registration is explicit; a duplicate `type` raises at startup.

**As a plugin (no fork needed):** put a module with `register(registry)` on `PYTHONPATH` and list it:

```bash
NODECRAFT_NODE_PLUGINS=my_company.nodes,other.module   # comma-separated
```

> **Plugins run inside the server process with full privileges.** They are operator configuration, never user input.
> Only load code you wrote or have reviewed. A workflow author can only *use* registered node types.

Plugin nodes appear in `GET /api/v1/nodes/definitions` and in the editor's "Add node" menu. The UI shows a generic JSON
config editor for types it has no custom form for.

## Testing your node

```python
from app.domain.nodes import NodeContext
async def test_upper():
    res = await UpperNode().execute(NodeContext(timeout_s=5), {"text": "hi"}, {})
    assert res.output == {"text": "HI"}
```
Or through the API: `POST /api/v1/nodes/test {"type": "demo.upper", "config": {}, "input": {"text": "hi"}}`.
See `backend/tests/test_nodes.py` for examples, including a local HTTP server and the plugin loader.

## Built-in nodes

| Type | What it does | Notes |
|---|---|---|
| `code.python` | `main(input_data)` in a child process | Unsandboxed, see [security.md](security.md) |
| `transform.json` | Build an object from the input with `$.paths` and literals | No code runs; deterministic |
| `http.request` | Call a public HTTP(S) API | SSRF-guarded; no redirects; secrets not supported yet |

### `transform.json` paths
`$` is the whole input. Then `.key`, `["any key"]`, `[0]`, `[-1]`. Missing paths give `null`, or fail the node when
`strict` is true. Example: `{"mapping": {"name": "$.user.name", "first": "$.items[0]", "v": {"literal": 1}}}`.

### `http.request` network policy
- Only `http`/`https`. No credentials in the URL. `Host`, `Content-Length`, `Connection` and similar headers can't be set.
- The hostname is resolved by Nodecraft and **every** address must be public. Loopback, private, link-local
  (including cloud metadata `169.254.169.254`), CGNAT, multicast, reserved and IPv6 forms that embed them
  (`::ffff:127.0.0.1`, 6to4, NAT64, Teredo) are blocked. It then connects to the checked address, so DNS rebinding
  cannot swap it afterwards. TLS still verifies the original hostname.
- **Redirects are not followed**; a 3xx is returned as the response. Response size is capped (default 1 MB, max 5 MB),
  request body 1 MB, timeout default 10 s.
- `NODECRAFT_HTTP_ALLOW_PRIVATE=1` disables the address check for local development against your own services.
  Never set it on a shared or hosted deployment.
- Not covered yet: egress allow-lists, per-user quotas, a credential store, proxies. Before hosting, run these calls from
  an isolated worker with network policy enforced at the infrastructure level (the in-process guard is defence in depth).

## Output ports and branching
A node declares its output ports in its definition (default: one port, `out`). To fire only some of them, return
`NodeResult(output=..., activated_ports={"true"})`; leaving it unset fires all ports. Edges leaving a port that did
not fire are not taken, and a node whose incoming edges were all untaken is skipped with `skip_reason="branch_not_taken"`
(not a failure). See [ADR 0007](adr/0007-branching-semantics.md). Edge ports are validated against your definition.

## Credentials
`ctx.secrets` resolves `{{credential:NAME}}` references at execution time. Use it instead of reading config values
directly, never log a resolved value, and never put one in an error message you build yourself; the executor masks values
it knows about, but only exact matches (see [ADR 0008](adr/0008-secrets.md)).
