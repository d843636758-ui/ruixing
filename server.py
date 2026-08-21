import os
from typing import Any

from fastmcp import Client, FastMCP
from fastmcp.client.transports import StreamableHttpTransport
from fastmcp.server.auth import AuthContext
from fastmcp.server.auth.providers.github import GitHubProvider
from fastmcp.server.middleware import AuthMiddleware
from pydantic import BaseModel


LUCKIN_MCP_URL = os.getenv(
    "LUCKIN_MCP_URL",
    "https://gwmcp.lkcoffee.com/order/user/mcp",
).strip()

LUCKIN_MCP_TOKEN = os.environ["LUCKIN_MCP_TOKEN"].strip()
BASE_URL = os.environ["BASE_URL"].rstrip("/")
GITHUB_CLIENT_ID = os.environ["GITHUB_CLIENT_ID"].strip()
GITHUB_CLIENT_SECRET = os.environ["GITHUB_CLIENT_SECRET"].strip()
ALLOWED_GITHUB_LOGIN = (
    os.environ["ALLOWED_GITHUB_LOGIN"]
    .strip()
    .lower()
)

PORT = int(os.getenv("PORT", "8000"))


# ============================================================
# Models
# ============================================================

class ProductItem(BaseModel):
    productId: int
    skuCode: str
    amount: int


class SubAttr(BaseModel):
    attributeId: int
    operation: int


class AttrOperationParam(BaseModel):
    attributeId: int
    subAttr: SubAttr


# ============================================================
# Auth
# ============================================================

def owner_only(ctx: AuthContext) -> bool:
    """Only the configured GitHub account may use Luckin tools."""
    if ctx.token is None:
        return False

    login = (
        str(ctx.token.claims.get("login", ""))
        .strip()
        .lower()
    )

    return (
        bool(login)
        and login == ALLOWED_GITHUB_LOGIN
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


# ============================================================
# Upstream client
# ============================================================

def make_luckin_transport() -> StreamableHttpTransport:
    return StreamableHttpTransport(
        url=LUCKIN_MCP_URL,
        headers={
            "Authorization":
                f"Bearer {LUCKIN_MCP_TOKEN}"
        },
    )


def scrub_secret(value: Any) -> str:
    """Never leak the Luckin token through diagnostic errors."""
    text = str(value)

    if LUCKIN_MCP_TOKEN:
        text = text.replace(
            LUCKIN_MCP_TOKEN,
            "<LUCKIN_TOKEN_REDACTED>",
        )

    return text[:6000]


def exception_details(exc: BaseException) -> dict:
    """
    Walk ExceptionGroup / HTTP exceptions and preserve any
    upstream response body that FastMCP/httpx exposes.
    """
    details = {
        "error_type": type(exc).__name__,
        "error": scrub_secret(exc),
    }

    stack = [exc]

    while stack:
        current = stack.pop()

        children = getattr(
            current,
            "exceptions",
            None,
        )

        if children:
            stack.extend(children)

        response = getattr(
            current,
            "response",
            None,
        )

        if response is None:
            continue

        status_code = getattr(
            response,
            "status_code",
            None,
        )

        if status_code is not None:
            details["http_status"] = status_code

        try:
            body = response.text
        except Exception:
            body = None

        if body:
            details["response_body"] = (
                scrub_secret(body)
            )

        headers = getattr(
            response,
            "headers",
            None,
        )

        if headers:
            safe_headers = {}

            for key in (
                "content-type",
                "server",
                "x-request-id",
                "trace-id",
            ):
                value = headers.get(key)

                if value:
                    safe_headers[key] = value

            if safe_headers:
                details["response_headers"] = (
                    safe_headers
                )

    return details


def result_payload(result: Any) -> Any:
    """Convert FastMCP CallToolResult into JSON-friendly output."""

    structured = getattr(
        result,
        "structured_content",
        None,
    )

    if structured is not None:
        return structured

    data = getattr(
        result,
        "data",
        None,
    )

    if data is not None:
        if hasattr(data, "model_dump"):
            return data.model_dump(
                mode="json"
            )

        if isinstance(
            data,
            (
                dict,
                list,
                str,
                int,
                float,
                bool,
            ),
        ):
            return data

    content = getattr(
        result,
        "content",
        [],
    )

    blocks = []

    for block in content:
        text = getattr(
            block,
            "text",
            None,
        )

        if text is not None:
            blocks.append(text)
        else:
            blocks.append(str(block))

    if len(blocks) == 1:
        return blocks[0]

    return blocks


async def call_luckin(
    tool_name: str,
    arguments: dict,
) -> dict:
    """
    Call Luckin directly using a fresh MCP client session.

    This intentionally avoids copied/mirrored proxy Tool objects.
    """
    try:
        async with Client(
            transport=make_luckin_transport()
        ) as client:

            result = await client.call_tool(
                tool_name,
                arguments,
                raise_on_error=False,
            )

        if getattr(
            result,
            "is_error",
            False,
        ):
            return {
                "ok": False,
                "upstream_tool": tool_name,
                "error_kind": "tool_error",
                "result": result_payload(result),
            }

        return {
            "ok": True,
            "upstream_tool": tool_name,
            "result": result_payload(result),
        }

    except BaseException as exc:
        return {
            "ok": False,
            "upstream_tool": tool_name,
            "error_kind": "transport_error",
            **exception_details(exc),
        }


# ============================================================
# Diagnostics
# ============================================================

@mcp.tool
def bridge_status() -> dict:
    """Check that the ChatGPT-to-Luckin bridge is running."""
    return {
        "ok": True,
        "upstream": LUCKIN_MCP_URL,
        "auth": "github-oauth-owner-only",
        "proxy_mode": "direct-call-wrappers",
        "note":
            "Luckin token is injected server-side.",
    }


@mcp.tool
async def bridge_upstream_tools() -> dict:
    """Read-only diagnostic: list official Luckin MCP tools."""
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

    except BaseException as exc:
        return {
            "ok": False,
            **exception_details(exc),
        }


# ============================================================
# Luckin tools
# ============================================================

@mcp.tool
async def queryShopList(
    longitude: float,
    latitude: float,
    deptName: str | None = None,
) -> dict:
    """
    瑞幸咖啡查询门店列表。

    longitude: 经度
    latitude: 纬度
    deptName: 可选门店名称
    """
    args = {
        "longitude": longitude,
        "latitude": latitude,
    }

    if deptName:
        args["deptName"] = deptName

    return await call_luckin(
        "queryShopList",
        args,
    )


@mcp.tool
async def searchProductForMcp(
    deptId: int,
    query: str,
) -> dict:
    """
    瑞幸咖啡根据自然语言查询匹配商品。

    此工具只搜索商品，不会创建订单。
    """
    return await call_luckin(
        "searchProductForMcp",
        {
            "deptId": deptId,
            "query": query,
        },
    )


@mcp.tool
async def queryProductDetailInfo(
    deptId: int,
    productId: int,
) -> dict:
    """瑞幸咖啡查询商品详情。"""
    return await call_luckin(
        "queryProductDetailInfo",
        {
            "deptId": deptId,
            "productId": productId,
        },
    )


@mcp.tool
async def switchProduct(
    deptId: int,
    productId: int,
    skuCode: str,
    attrOperationParam: AttrOperationParam,
    amount: int,
) -> dict:
    """
    瑞幸咖啡切换商品属性，例如冰热、甜度等。
    """
    return await call_luckin(
        "switchProduct",
        {
            "deptId": deptId,
            "productId": productId,
            "skuCode": skuCode,
            "attrOperationParam":
                attrOperationParam.model_dump(),
            "amount": amount,
        },
    )


@mcp.tool
async def previewOrder(
    deptId: int,
    productList: list[ProductItem],
) -> dict:
    """
    瑞幸咖啡订单预览。

    只计算商品、价格和优惠，不创建真实订单。
    """
    return await call_luckin(
        "previewOrder",
        {
            "deptId": deptId,
            "productList": [
                item.model_dump()
                for item in productList
            ],
        },
    )


@mcp.tool
async def createOrder(
    deptId: int,
    productList: list[ProductItem],
    longitude: float,
    latitude: float,
    couponCodeList: list[str] | None = None,
    remark: str | None = None,
) -> dict:
    """
    创建真实瑞幸订单。

    IMPORTANT:
    只有用户明确确认门店、商品规格和应付金额，
    并明确要求实际下单之后，才允许调用此工具。
    """
    args = {
        "deptId": deptId,
        "productList": [
            item.model_dump()
            for item in productList
        ],
        "longitude": longitude,
        "latitude": latitude,
    }

    if couponCodeList is not None:
        args["couponCodeList"] = (
            couponCodeList
        )

    if remark is not None:
        args["remark"] = remark

    return await call_luckin(
        "createOrder",
        args,
    )


@mcp.tool
async def queryOrderDetailInfo(
    orderId: str,
) -> dict:
    """查询瑞幸订单详情和取餐状态。"""
    return await call_luckin(
        "queryOrderDetailInfo",
        {
            "orderId": orderId,
        },
    )


@mcp.tool
async def cancelOrder(
    orderId: str,
) -> dict:
    """
    取消真实瑞幸订单。

    这是有外部副作用的操作。
    只有用户明确要求取消指定订单后才允许调用。
    """
    return await call_luckin(
        "cancelOrder",
        {
            "orderId": orderId,
        },
    )


# ============================================================
# Run
# ============================================================

if __name__ == "__main__":
    mcp.run(
        transport="http",
        host="0.0.0.0",
        port=PORT,
    )
