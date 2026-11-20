# /// script
# requires-python = ">=3.10"
# dependencies = ["mcp==1.29.0"]
# ///
"""Private stdio tools for owner-authorized MCP clients on the Command Center host."""
from typing import Literal

from mcp.server.fastmcp import FastMCP
from personal_kanban import Board

server = FastMCP("Command Center tasks", instructions=(
    "Use this board for the owner's personal task requests, including transcribed voice messages. "
    "Create or update the task before confirming it. Preserve the request ID on retries, "
    "return its URL, and use the day view for today's plan."
))


@server.tool()
def create_task(title: str, source_key: str, project: str = "Личное",
                plan: str = "", due: str = "") -> dict:
    """Create one owner-requested task. Reuse the original message/request ID on retries.
    For 'на сегодня' use today's Paris date as plan. Only set due for an explicit deadline.
    Return the saved issue URL to the user.
    """
    return Board().apply("create_task", locals())


@server.tool()
def list_tasks(view: Literal["open", "day", "overdue", "all"] = "open") -> list[dict]:
    """Read current cards, with stable ID and revision for edits."""
    return Board().apply("list_tasks", {"view": view})


@server.tool()
def update_task(id: int, revision: str, status: Literal["todo", "doing", "done"] | None = None,
                plan: str | None = None, due: str | None = None) -> dict:
    """Update one existing card at its observed revision. Empty date clears it."""
    return Board().apply("update_task", {k: v for k, v in locals().items() if v is not None})


if __name__ == "__main__":
    server.run(transport="stdio")
