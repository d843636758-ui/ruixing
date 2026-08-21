# Luckin Coffee → ChatGPT MCP Bridge

A tiny authenticated bridge for connecting Luckin Coffee’s official remote MCP to ChatGPT when ChatGPT’s custom MCP UI only offers OAuth / No Auth / Mixed, while Luckin requires a static Bearer token\.

## What it does

- ChatGPT → this bridge: OAuth \(GitHub sign\-in\)
- this bridge → Luckin: `Authorization: Bearer <LUCKIN_MCP_TOKEN>`
- Mirrors the official Luckin MCP tools, including order preview, order creation, order lookup, and cancellation\.
- Restricts all tools to one GitHub username via `ALLOWED_GITHUB_LOGIN`\.
- Keeps the Luckin token only in Zeabur environment secrets, not in ChatGPT or source code\.

## Deploy on Zeabur

1. Create a service from this repository/folder and let Zeabur build the Dockerfile\.
2. Generate a public HTTPS domain for the service\. Call it `BASE_URL`, for example:
   `https://luckin-bridge-xxxx.zeabur.app`
3. In GitHub → Settings → Developer settings → OAuth Apps → New OAuth App, create an app:
  - Homepage URL: your `BASE_URL`
  - Authorization callback URL: `BASE_URL/auth/callback`
4. In Zeabur → Variables/Secrets, add:
  - `LUCKIN_MCP_TOKEN` = your Luckin AI Open Platform token
  - `BASE_URL` = your public Zeabur URL, without trailing `/`
  - `GITHUB_CLIENT_ID` = GitHub OAuth App client ID
  - `GITHUB_CLIENT_SECRET` = GitHub OAuth App client secret
  - `ALLOWED_GITHUB_LOGIN` = the exact GitHub username allowed to use your coffee account
5. Redeploy/restart the service\.

## Connect it in ChatGPT

Create a custom MCP/app in ChatGPT:

- Server URL: `BASE_URL/mcp`
- Authentication: **OAuth**
- Leave Advanced OAuth settings on discovery/default first\.
- Scan tools\.
- When the browser opens GitHub, sign in with the username configured in `ALLOWED_GITHUB_LOGIN` and authorize\.

If authentication succeeds, the scanned tools should include the official Luckin capabilities plus `bridge_status`\.

## Ordering flow

Recommended conversational flow:

1. Find/select store\.
2. Search/select drink and options\.
3. Preview order and show price/discounts\.
4. User explicitly confirms the store, product/options and payable amount\.
5. Call the upstream order\-creation tool\.
6. Luckin returns its payment step \(typically a payment link/QR\); the user completes payment\.
7. Query order status / pickup information as needed\.

This bridge intentionally does **not** hide the official write tools; it lets ChatGPT create a real Luckin order\. ChatGPT may separately ask for confirmation before a write action depending on account/workspace permissions and rollout\.

## Security notes

- Never paste `LUCKIN_MCP_TOKEN` into chat, screenshots, GitHub, or source code\.
- Do not remove `ALLOWED_GITHUB_LOGIN`; otherwise any GitHub user who can authorize the bridge could potentially operate the same Luckin account\.
- Keep the repository private if you later add any local configuration\. The provided code itself contains no secrets\.
- Luckin tokens can expire; replace only the Zeabur secret when that happens\.
- This lightweight first version uses FastMCP’s default Linux OAuth storage; after a Zeabur restart ChatGPT may need to re\-authorize\. Once the bridge is proven working, add Redis\-backed encrypted OAuth storage for restart\-proof sessions\.

## Troubleshooting

- **ChatGPT OAuth timeout before GitHub opens**: verify `BASE_URL` is exact HTTPS public URL and `/mcp` is reachable; make sure GitHub callback is exactly `BASE_URL/auth/callback`\.
- **GitHub authorizes but tools are hidden/forbidden**: `ALLOWED_GITHUB_LOGIN` must exactly match the GitHub login, case\-insensitive\.
- **Tools scan but Luckin calls return 401**: refresh the Luckin token and update `LUCKIN_MCP_TOKEN` in Zeabur\.
- **Only read tools work in ChatGPT**: this can be a ChatGPT plan/workspace rollout limitation rather than a bridge issue; the proxy itself mirrors write tools too\.
