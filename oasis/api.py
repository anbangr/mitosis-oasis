"""Metosis-OASIS FastAPI HTTP server.

Wraps the existing Platform + Channel with REST endpoints so that external
agents (ZeroClaw) can interact with the simulation via HTTP instead of being
embedded CAMEL agents.
"""
from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager
from typing import Any, Optional

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from oasis.governance.endpoints import init_governance_db, router as governance_router
from oasis.execution.endpoints import init_execution_db, router as execution_router
from oasis.social_platform.channel import Channel
from oasis.social_platform.platform import Platform
from oasis.social_platform.typing import ActionType

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Global state (populated during startup)
# ---------------------------------------------------------------------------

channel: Channel | None = None
platform: Platform | None = None
_platform_task: asyncio.Task | None = None


# ---------------------------------------------------------------------------
# Lifespan: spin up Platform on startup, shut it down gracefully
# ---------------------------------------------------------------------------


@asynccontextmanager
async def lifespan(app: FastAPI):
    global channel, platform, _platform_task

    channel = Channel()
    # Platform needs at least a db_path and a channel.
    # Use an in-memory SQLite database so the server can start without config.
    platform = Platform(
        db_path=":memory:",
        channel=channel,
    )
    _platform_task = asyncio.create_task(platform.running())

    # Initialise governance database (in-memory, colocated with platform DB)
    import tempfile, os
    _gov_db = os.path.join(tempfile.gettempdir(), f"oasis_gov_{os.getpid()}.db")
    init_governance_db(_gov_db)

    logger.info("Metosis-OASIS platform started")

    yield  # Server is now running

    # Graceful shutdown: send EXIT action
    if channel is not None:
        try:
            await channel.write_to_receive_queue((0, None, ActionType.EXIT.value))
            if _platform_task is not None:
                await asyncio.wait_for(_platform_task, timeout=5.0)
        except (asyncio.TimeoutError, Exception) as exc:
            logger.warning("Platform shutdown issue: %s", exc)
            if _platform_task is not None:
                _platform_task.cancel()
    logger.info("Metosis-OASIS platform stopped")


# ---------------------------------------------------------------------------
# FastAPI application
# ---------------------------------------------------------------------------

app = FastAPI(
    title="Metosis-OASIS API",
    description="REST API for OASIS social simulation platform",
    version="0.3.0",
    lifespan=lifespan,
)

# Include governance API router (P8)
app.include_router(governance_router)

# Include execution API router (P13)
app.include_router(execution_router)


# ---------------------------------------------------------------------------
# Internal dispatch helper
# ---------------------------------------------------------------------------


async def _dispatch(action_type: ActionType, agent_id: int,
                    message: Any = None) -> Any:
    """Send an action through the channel and await the platform response."""
    if channel is None:
        raise HTTPException(status_code=503, detail="Platform not running")
    msg_id = await channel.write_to_receive_queue(
        (agent_id, message, action_type.value))
    _, _, result = await channel.read_from_send_queue(msg_id)
    return result


# ---------------------------------------------------------------------------
# Pydantic request models
# ---------------------------------------------------------------------------


class SignUpBody(BaseModel):
    agent_id: int
    user_name: str
    name: str
    bio: str = ""


class CreatePostBody(BaseModel):
    agent_id: int
    content: str


class AgentIdBody(BaseModel):
    agent_id: int


class AgentIdWithContentBody(BaseModel):
    agent_id: int
    content: str


class FollowBody(BaseModel):
    agent_id: int
    target_user_id: int


class CreateCommentBody(BaseModel):
    agent_id: int
    content: str


class QuotePostBody(BaseModel):
    agent_id: int
    content: str


class ReportPostBody(BaseModel):
    agent_id: int
    reason: str = ""


class SendToGroupBody(BaseModel):
    agent_id: int
    content: str


class CreateGroupBody(BaseModel):
    agent_id: int
    group_name: str


class PurchaseProductBody(BaseModel):
    agent_id: int
    quantity: int = 1


# ---------------------------------------------------------------------------
# Health check
# ---------------------------------------------------------------------------


@app.get("/api/health", tags=["Meta"])
async def health():
    """Health check endpoint."""
    return {"status": "ok", "platform_running": platform is not None}


# ---------------------------------------------------------------------------
# Auth / Identity
# ---------------------------------------------------------------------------


@app.post("/api/users", tags=["Auth"])
async def sign_up(body: SignUpBody):
    """Register a new agent as a user on the platform."""
    result = await _dispatch(
        ActionType.SIGNUP,
        body.agent_id,
        (body.user_name, body.name, body.bio),
    )
    return result


# ---------------------------------------------------------------------------
# Feed
# ---------------------------------------------------------------------------


@app.get("/api/feed", tags=["Feed"])
async def refresh(agent_id: int = Query(..., description="Agent ID")):
    """Fetch the recommended post feed for the agent."""
    result = await _dispatch(ActionType.REFRESH, agent_id)
    return result


@app.get("/api/trends", tags=["Feed"])
async def trend(agent_id: int = Query(..., description="Agent ID")):
    """Fetch trending topics/posts for the agent."""
    result = await _dispatch(ActionType.TREND, agent_id)
    return result


# ---------------------------------------------------------------------------
# Posts
# ---------------------------------------------------------------------------


@app.post("/api/posts", tags=["Posts"])
async def create_post(body: CreatePostBody):
    """Create a new post."""
    result = await _dispatch(ActionType.CREATE_POST, body.agent_id,
                              body.content)
    return result


@app.post("/api/posts/{post_id}/like", tags=["Posts"])
async def like_post(post_id: int, body: AgentIdBody):
    """Like a post."""
    result = await _dispatch(ActionType.LIKE_POST, body.agent_id, post_id)
    return result


@app.delete("/api/posts/{post_id}/like", tags=["Posts"])
async def unlike_post(post_id: int, body: AgentIdBody):
    """Remove a like from a post."""
    result = await _dispatch(ActionType.UNLIKE_POST, body.agent_id, post_id)
    return result


@app.post("/api/posts/{post_id}/dislike", tags=["Posts"])
async def dislike_post(post_id: int, body: AgentIdBody):
    """Dislike a post."""
    result = await _dispatch(ActionType.DISLIKE_POST, body.agent_id, post_id)
    return result


@app.delete("/api/posts/{post_id}/dislike", tags=["Posts"])
async def undo_dislike_post(post_id: int, body: AgentIdBody):
    """Remove a dislike from a post."""
    result = await _dispatch(ActionType.UNDO_DISLIKE_POST, body.agent_id,
                              post_id)
    return result


@app.post("/api/posts/{post_id}/repost", tags=["Posts"])
async def repost(post_id: int, body: AgentIdBody):
    """Repost an existing post."""
    result = await _dispatch(ActionType.REPOST, body.agent_id, post_id)
    return result


@app.post("/api/posts/{post_id}/report", tags=["Posts"])
async def report_post(post_id: int, body: ReportPostBody):
    """Report a post.

    The Platform's report_post expects ``report_message = (post_id, reason)``.
    """
    result = await _dispatch(ActionType.REPORT_POST, body.agent_id,
                              (post_id, body.reason))
    return result


@app.post("/api/posts/{post_id}/quote", tags=["Posts"])
async def quote_post(post_id: int, body: QuotePostBody):
    """Quote a post with added commentary.

    The Platform's quote_post expects ``quote_message = (post_id, content)``.
    """
    result = await _dispatch(ActionType.QUOTE_POST, body.agent_id,
                              (post_id, body.content))
    return result


# ---------------------------------------------------------------------------
# Comments
# ---------------------------------------------------------------------------


@app.post("/api/posts/{post_id}/comments", tags=["Comments"])
async def create_comment(post_id: int, body: CreateCommentBody):
    """Create a comment on a post.

    The Platform's create_comment expects ``comment_message = (post_id, content)``.
    """
    result = await _dispatch(ActionType.CREATE_COMMENT, body.agent_id,
                              (post_id, body.content))
    return result


@app.post("/api/comments/{comment_id}/like", tags=["Comments"])
async def like_comment(comment_id: int, body: AgentIdBody):
    """Like a comment."""
    result = await _dispatch(ActionType.LIKE_COMMENT, body.agent_id,
                              comment_id)
    return result


@app.delete("/api/comments/{comment_id}/like", tags=["Comments"])
async def unlike_comment(comment_id: int, body: AgentIdBody):
    """Remove a like from a comment."""
    result = await _dispatch(ActionType.UNLIKE_COMMENT, body.agent_id,
                              comment_id)
    return result


@app.post("/api/comments/{comment_id}/dislike", tags=["Comments"])
async def dislike_comment(comment_id: int, body: AgentIdBody):
    """Dislike a comment."""
    result = await _dispatch(ActionType.DISLIKE_COMMENT, body.agent_id,
                              comment_id)
    return result


@app.delete("/api/comments/{comment_id}/dislike", tags=["Comments"])
async def undo_dislike_comment(comment_id: int, body: AgentIdBody):
    """Remove a dislike from a comment."""
    result = await _dispatch(ActionType.UNDO_DISLIKE_COMMENT, body.agent_id,
                              comment_id)
    return result


# ---------------------------------------------------------------------------
# Social Graph
# ---------------------------------------------------------------------------


@app.post("/api/follow", tags=["Social Graph"])
async def follow(body: FollowBody):
    """Follow another user.

    The Platform's follow expects ``followee_id`` as the message.
    """
    result = await _dispatch(ActionType.FOLLOW, body.agent_id,
                              body.target_user_id)
    return result


@app.delete("/api/follow", tags=["Social Graph"])
async def unfollow(body: FollowBody):
    """Unfollow a user."""
    result = await _dispatch(ActionType.UNFOLLOW, body.agent_id,
                              body.target_user_id)
    return result


@app.post("/api/mute", tags=["Social Graph"])
async def mute(body: FollowBody):
    """Mute a user."""
    result = await _dispatch(ActionType.MUTE, body.agent_id,
                              body.target_user_id)
    return result


@app.delete("/api/mute", tags=["Social Graph"])
async def unmute(body: FollowBody):
    """Unmute a user."""
    result = await _dispatch(ActionType.UNMUTE, body.agent_id,
                              body.target_user_id)
    return result


# ---------------------------------------------------------------------------
# Search
# ---------------------------------------------------------------------------


@app.get("/api/search/users", tags=["Search"])
async def search_user(
    agent_id: int = Query(..., description="Agent performing the search"),
    query: str = Query(..., description="Search query string"),
):
    """Search for users by name or username."""
    result = await _dispatch(ActionType.SEARCH_USER, agent_id, query)
    return result


@app.get("/api/search/posts", tags=["Search"])
async def search_posts(
    agent_id: int = Query(..., description="Agent performing the search"),
    query: str = Query(..., description="Search query string"),
):
    """Search for posts by content."""
    result = await _dispatch(ActionType.SEARCH_POSTS, agent_id, query)
    return result


# ---------------------------------------------------------------------------
# Groups
# ---------------------------------------------------------------------------


@app.post("/api/groups", tags=["Groups"])
async def create_group(body: CreateGroupBody):
    """Create a new chat group."""
    result = await _dispatch(ActionType.CREATE_GROUP, body.agent_id,
                              body.group_name)
    return result


@app.post("/api/groups/{group_id}/join", tags=["Groups"])
async def join_group(group_id: int, body: AgentIdBody):
    """Join an existing group."""
    result = await _dispatch(ActionType.JOIN_GROUP, body.agent_id, group_id)
    return result


@app.post("/api/groups/{group_id}/leave", tags=["Groups"])
async def leave_group(group_id: int, body: AgentIdBody):
    """Leave a group."""
    result = await _dispatch(ActionType.LEAVE_GROUP, body.agent_id, group_id)
    return result


@app.post("/api/groups/{group_id}/messages", tags=["Groups"])
async def send_to_group(group_id: int, body: AgentIdWithContentBody):
    """Send a message to a group.

    The Platform's send_to_group expects ``message = (group_id, content)``.
    """
    result = await _dispatch(ActionType.SEND_TO_GROUP, body.agent_id,
                              (group_id, body.content))
    return result


@app.get("/api/groups/listen", tags=["Groups"])
async def listen_from_group(
    agent_id: int = Query(..., description="Agent ID"),
):
    """Listen for messages from all groups the agent belongs to."""
    result = await _dispatch(ActionType.LISTEN_FROM_GROUP, agent_id)
    return result


# ---------------------------------------------------------------------------
# Products
# ---------------------------------------------------------------------------


@app.post("/api/products/{product_name}/purchase", tags=["Products"])
async def purchase_product(product_name: str, body: PurchaseProductBody):
    """Purchase a product.

    The Platform's purchase_product expects
    ``purchase_message = (product_name, quantity)``.
    """
    result = await _dispatch(ActionType.PURCHASE_PRODUCT, body.agent_id,
                              (product_name, body.quantity))
    return result


# ---------------------------------------------------------------------------
# Governance endpoints are now served by oasis.governance.endpoints router
# (included via app.include_router above — replaces previous 501 stubs)
# ---------------------------------------------------------------------------
