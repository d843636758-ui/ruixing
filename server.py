import os

from fastmcp import FastMCP
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
    """Only the configured GitHub account may see or call any Luckin tool."""
    if ctx.token is None:
        return False
    login = str(ctx.token.claims.get("login", "")).strip().lower()
    return bool(login) and login == ALLOWED_GITHUB_LOGIN


# ChatGPT authenticates to this bridge with OAuth.
# GitHubProvider supplies the OAuth 2.1 / DCR compatibility expected by MCP clients.
auth = GitHubProvider(
    client_id=GITHUB_CLIENT_ID,
    client_secret=GITHUB_CLIENT_SECRET,
    base_url=BASE_URL,
)

# Parent auth + middleware also protects all tools mounted from the upstream proxy.
mcp = FastMCP(
    "Luckin Coffee for ChatGPT",
    auth=auth,
    middleware=[AuthMiddleware(auth=owner_only)],
)

# The bridge, not ChatGPT, stores and injects the static Luckin Bearer token.
# The token never needs to be pasted into ChatGPT.
luckin_transport = StreamableHttpTransport(
    url=LUCKIN_MCP_URL,
    headers={"Authorization": f"Bearer {LUCKIN_MCP_TOKEN}"},
)

# Mirror all official Luckin MCP capabilities, including preview/create/query/cancel order.
luckin_proxy = create_proxy(luckin_transport, name="Luckin upstream")
mcp.mount(luckin_proxy)


@mcp.tool
def bridge_status() -> dict:
    """Check that the ChatGPT-to-Luckin bridge is running and authenticated."""
    return {
        "ok": True,
        "upstream": LUCKIN_MCP_URL,
        "auth": "github-oauth-owner-only",
        "note": "Luckin token is injected server-side.",
    }


if __name__ == "__main__":
    mcp.run(transport="http", host="0.0.0.0", port=PORT)
