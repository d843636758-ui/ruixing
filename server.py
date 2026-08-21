import asyncio
import os

from fastmcp import Client, FastMCP
from fastmcp.client.transports import StreamableHttpTransport
from fastmcp.server import create_proxy
from fastmcp.server.auth import AuthContext
from fastmcp.server.auth.providers.github import GitHubProvider
from fastmcp.server.middleware import AuthMiddleware

LUCKIN_MCP_URL = os.getenv(
    "LUCKIN_MCP_URL",
    "https://gwmcp.lkcoffee.com/order/user/mcp",
).strip()
LUCKIN_MCP_TOKEN = os.environ["LUCKIN_MCP_TOKEN"].strip()
BASE_URL = os.environ["BASE_URL"].rstrip("/")
GITHUB_CLIENT_ID = os.environ["GITHUB_CLIENT_ID"].strip()
GITHUB_CLIENT_SECRET = os.environ["GITHUB_CLIENT_SECRET"].strip()
ALLOWED_GITHUB_LOGIN = os.environ["ALLOWED_GITHUB_LOGIN"].strip().lower()
PORT = int(os.getenv("PORT", "8000"))


def owner_only(ctx: AuthContext) -> bool:
    """Only the configured GitHub account may see or call Luckin tools."""
    if ctx.token is None:
        return False

    login = str(ctx.token.claims.get("login", "")).strip().lower()
    return bool(login) and login == ALLOWED_GITHUB_LOGIN


def make_luckin_transport() -> StreamableHttpTransport:
    """Create an authenticated transport to Luckin's official MCP."""
    return StreamableHttpTransport(
        url=LUCKIN_MCP_URL,
        headers={
            "Authorization": f"Bearer {LUCKIN_MCP_TOKEN}"
        },
    )


auth = GitHubProvider(
    client_id=GITHUB_CLIENT_ID,
    client_secret=GITHUB_CLIENT_SECRET,
    base_url=BASE_URL,
)

mcp = FastMCP(
    "Luckin Coffee for ChatGPT",
    auth=auth,
    middleware=[
        AuthMiddleware(auth=owner_only)
    ],
)

# Create a real FastMCP proxy for Luckin's official MCP.
luckin_proxy = create_proxy(
    make_luckin_transport(),
    name="Luckin upstream",
)


@mcp.tool
def bridge_status() -> dict:
    """Check that the ChatGPT-to-Luckin bridge is running and authenticated."""
    return {
        "ok": True,
        "upstream": LUCKIN_MCP_URL,
        "auth": "github-oauth-owner-only",
        "proxy_mode": "imported-local-tools",
        "note": "Luckin token is injected server-side.",
    }


@mcp.tool
async def bridge_upstream_tools() -> dict:
    """Read-only diagnostic: list tools exposed by Luckin's official MCP."""
    try:
        async with Client(
            transport=make_luckin_transport()
        ) as client:
            tools = await client.list_tools()

        return {
            "ok": True,
            "count": len(tools),
            "tools": [
                tool.name
                for tool in tools
            ],
        }

    except Exception as exc:
        return {
            "ok": False,
            "error_type": type(exc).__name__,
            "error": str(exc),
        }


async def import_upstream_tools() -> None:
    """
    Import Luckin's mirrored proxy tools into this server's local tool catalog.

    This makes ChatGPT see the upstream Luckin tools as concrete tools during
    its tools/list scan, rather than relying on dynamic provider discovery.
    """
    last_error = None

    for attempt in range(1, 4):
        try:
            tools = await luckin_proxy.list_tools()

            imported = 0

            for tool in tools:
                # Never overwrite our own diagnostic tools.
                if tool.name in {
                    "bridge_status",
                    "bridge_upstream_tools",
                }:
                    continue

                local_tool = tool.copy()
                mcp.add_tool(local_tool)
                imported += 1

            print(
                f"[luckin-bridge] imported "
                f"{imported} upstream tools: "
                + ", ".join(
                    tool.name
                    for tool in tools
                )
            )

            return

        except Exception as exc:
            last_error = exc

            print(
                f"[luckin-bridge] upstream import "
                f"attempt {attempt}/3 failed: "
                f"{type(exc).__name__}: {exc}"
            )

            if attempt < 3:
                await asyncio.sleep(
                    attempt * 2
                )

    raise RuntimeError(
        "Could not import Luckin upstream tools "
        "after 3 attempts"
    ) from last_error


if __name__ == "__main__":
    # Import the eight remote Luckin tools BEFORE starting the HTTP server.
    # This lets ChatGPT see them on its very first tools/list scan.
    asyncio.run(
        import_upstream_tools()
    )

    mcp.run(
        transport="http",
        host="0.0.0.0",
        port=PORT,
    )
