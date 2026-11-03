from mcp.server.mcpserver import MCPServer

mcp = MCPServer("tollgate-buyer")

# Phase 4:
#   get_budget()
#   browse_catalog(query)
#   buy_article(id, max_price)
#   get_receipts()


@mcp.tool()
def ping() -> str:
    """Health check."""
    return "pong"


if __name__ == "__main__":
    mcp.run()
