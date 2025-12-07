"""
WebSocket API for Real-time Collaboration

Provides real-time updates for board changes, card movements, etc.
"""
from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from typing import Dict, Set, Optional
import json
import asyncio
from dataclasses import dataclass, field
from datetime import datetime

router = APIRouter()


@dataclass
class ConnectionManager:
    """Manages WebSocket connections per board."""
    # board_id -> set of websocket connections
    board_connections: Dict[str, Set[WebSocket]] = field(default_factory=dict)
    # websocket -> user info
    connection_info: Dict[WebSocket, dict] = field(default_factory=dict)

    async def connect(self, websocket: WebSocket, board_id: str, user_id: str, user_name: str = "Anonymous"):
        """Accept a new WebSocket connection for a board."""
        await websocket.accept()

        if board_id not in self.board_connections:
            self.board_connections[board_id] = set()

        self.board_connections[board_id].add(websocket)
        self.connection_info[websocket] = {
            "board_id": board_id,
            "user_id": user_id,
            "user_name": user_name,
            "connected_at": datetime.utcnow().isoformat()
        }

        # Notify others that someone joined
        await self.broadcast_to_board(board_id, {
            "type": "user_joined",
            "user_id": user_id,
            "user_name": user_name,
            "timestamp": datetime.utcnow().isoformat()
        }, exclude=websocket)

        # Send current users to the new connection
        users = self.get_board_users(board_id)
        await websocket.send_json({
            "type": "users_online",
            "users": users
        })

    def disconnect(self, websocket: WebSocket):
        """Remove a WebSocket connection."""
        info = self.connection_info.get(websocket)
        if info:
            board_id = info["board_id"]
            if board_id in self.board_connections:
                self.board_connections[board_id].discard(websocket)
                if not self.board_connections[board_id]:
                    del self.board_connections[board_id]
            del self.connection_info[websocket]
            return info
        return None

    def get_board_users(self, board_id: str) -> list:
        """Get list of users currently connected to a board."""
        users = []
        if board_id in self.board_connections:
            for ws in self.board_connections[board_id]:
                info = self.connection_info.get(ws)
                if info:
                    users.append({
                        "user_id": info["user_id"],
                        "user_name": info["user_name"]
                    })
        return users

    async def broadcast_to_board(self, board_id: str, message: dict, exclude: Optional[WebSocket] = None):
        """Broadcast a message to all connections on a board."""
        if board_id not in self.board_connections:
            return

        dead_connections = set()
        for connection in self.board_connections[board_id]:
            if connection == exclude:
                continue
            try:
                await connection.send_json(message)
            except Exception:
                dead_connections.add(connection)

        # Clean up dead connections
        for dead in dead_connections:
            self.disconnect(dead)

    async def send_to_user(self, board_id: str, user_id: str, message: dict):
        """Send a message to a specific user on a board."""
        if board_id not in self.board_connections:
            return

        for connection in self.board_connections[board_id]:
            info = self.connection_info.get(connection)
            if info and info["user_id"] == user_id:
                try:
                    await connection.send_json(message)
                except Exception:
                    pass


# Global connection manager
manager = ConnectionManager()


@router.websocket("/ws/{board_id}")
async def websocket_endpoint(websocket: WebSocket, board_id: str):
    """WebSocket endpoint for real-time board updates."""
    # Get user info from query params
    user_id = websocket.query_params.get("user_id", "anonymous")
    user_name = websocket.query_params.get("user_name", "Anonymous")

    await manager.connect(websocket, board_id, user_id, user_name)

    try:
        while True:
            # Receive message from client
            data = await websocket.receive_json()

            # Handle different message types
            message_type = data.get("type")

            if message_type == "ping":
                # Respond to ping with pong
                await websocket.send_json({"type": "pong"})

            elif message_type == "cursor_move":
                # Broadcast cursor position to others
                await manager.broadcast_to_board(board_id, {
                    "type": "cursor_move",
                    "user_id": user_id,
                    "user_name": user_name,
                    "x": data.get("x"),
                    "y": data.get("y"),
                    "card_id": data.get("card_id")
                }, exclude=websocket)

            elif message_type == "card_focus":
                # User is focusing on a card (editing)
                await manager.broadcast_to_board(board_id, {
                    "type": "card_focus",
                    "user_id": user_id,
                    "user_name": user_name,
                    "card_id": data.get("card_id")
                }, exclude=websocket)

            elif message_type == "card_blur":
                # User stopped focusing on a card
                await manager.broadcast_to_board(board_id, {
                    "type": "card_blur",
                    "user_id": user_id,
                    "user_name": user_name,
                    "card_id": data.get("card_id")
                }, exclude=websocket)

            elif message_type == "typing":
                # User is typing in a card
                await manager.broadcast_to_board(board_id, {
                    "type": "typing",
                    "user_id": user_id,
                    "user_name": user_name,
                    "card_id": data.get("card_id"),
                    "field": data.get("field")
                }, exclude=websocket)

            # Board/card change events (triggered after API calls)
            elif message_type in ["card_created", "card_updated", "card_moved", "card_deleted",
                                   "column_created", "column_updated", "column_deleted",
                                   "comment_added", "label_changed", "assignee_changed"]:
                # Broadcast the change to all other users
                await manager.broadcast_to_board(board_id, {
                    "type": message_type,
                    "user_id": user_id,
                    "user_name": user_name,
                    "data": data.get("data"),
                    "timestamp": datetime.utcnow().isoformat()
                }, exclude=websocket)

    except WebSocketDisconnect:
        info = manager.disconnect(websocket)
        if info:
            # Notify others that user left
            await manager.broadcast_to_board(board_id, {
                "type": "user_left",
                "user_id": info["user_id"],
                "user_name": info["user_name"],
                "timestamp": datetime.utcnow().isoformat()
            })
    except Exception as e:
        info = manager.disconnect(websocket)
        if info:
            await manager.broadcast_to_board(board_id, {
                "type": "user_left",
                "user_id": info["user_id"],
                "user_name": info["user_name"],
                "timestamp": datetime.utcnow().isoformat()
            })


# Helper function to broadcast from API routes
async def broadcast_board_event(board_id: str, event_type: str, data: dict, user_id: str = None, user_name: str = None):
    """Helper function to broadcast events from API routes."""
    await manager.broadcast_to_board(board_id, {
        "type": event_type,
        "user_id": user_id,
        "user_name": user_name,
        "data": data,
        "timestamp": datetime.utcnow().isoformat()
    })


@router.get("/ws/boards/{board_id}/users")
async def get_online_users(board_id: str):
    """Get list of users currently online on a board."""
    users = manager.get_board_users(board_id)
    return {
        "board_id": board_id,
        "users": users,
        "count": len(users)
    }
