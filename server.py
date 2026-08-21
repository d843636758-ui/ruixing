import os

from fastmcp import Client, FastMCP
from fastmcp.client.transports import StreamableHttpTransport
from fastmcp.server.auth import AuthContext
from fastmcp.server.auth.providers.github import GitHubProvider
from fastmcp.server.middleware import AuthMiddleware
from fastmcp.server.providers.proxy import ProxyClient, ProxyProvider

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
    """Create a fresh authenticated transport to Luckin's official MCP."""
    return StreamableHttpTransport(
        url=LUCKIN_MCP_URL,
        headers={"Authorization": f"Bearer {LUCKIN_MCP_TOKEN}"},
    )


def make_luckin_proxy_client() -> ProxyClient:
    """Create an isolated upstream client for one proxy session."""
    return ProxyClient(make_luckin_transport())


# ChatGPT authenticates to this bridge with GitHub-backed OAuth.
auth = GitHubProvider(
    client_id=GITHUB_CLIENT_ID,
    client_secret=GITHUB_CLIENT_SECRET,
    base_url=BASE_URL,
)

# Put Luckin's remote MCP directly into the parent provider chain.
# cache_ttl=0 deliberately forces a fresh upstream component list so ChatGPT
# does not get stuck with a cached empty/partial tool catalog during setup.
luckin_provider = ProxyProvider(
    make_luckin_proxy_client,
    cache_ttl=0,
)

mcp = FastMCP(
    "Luckin Coffee for ChatGPT",
    auth=auth,
    providers=[luckin_provider],
    middleware=[AuthMiddleware(auth=owner_only)],
)


@mcp.tool
def bridge_status() -> dict:
    """Check that the ChatGPT-to-Luckin bridge is running and authenticated."""
    return {
        "ok": True,
        "upstream": LUCKIN_MCP_URL,
        "auth": "github-oauth-owner-only",
        "proxy_mode": "direct-provider",
        "note": "Luckin token is injected server-side.",
    }


@mcp.tool
async def bridge_upstream_tools() -> dict:
    """Read-only diagnostic: list tool names exposed by Luckin's official MCP."""
    try:
        async with Client(transport=make_luckin_transport()) as client:
            tools = await client.list_tools()

        names = [tool.name for tool in tools]
        return {
            "ok": True,
            "count": len(names),
            "tools": names,
        }
    except Exception as exc:
        return {
            "ok": False,
            "error_type": type(exc).__name__,
            "error": str(exc),
        }


if __name__ == "__main__":
    mcp.run(
        transport="http",
        host="0.0.0.0",
        port=PORT,
    )
