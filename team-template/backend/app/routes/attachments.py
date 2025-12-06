"""File attachments routes"""

from fastapi import APIRouter, HTTPException, UploadFile, File
from fastapi.responses import FileResponse
from ..services.database import Database, Q
from pathlib import Path
import os
import mimetypes

router = APIRouter()

DATA_DIR = Path(os.getenv("DATA_DIR", "/app/data"))
UPLOADS_DIR = DATA_DIR / "uploads" / "cards"
MAX_FILE_SIZE = 10 * 1024 * 1024  # 10MB
ALLOWED_EXTENSIONS = {
    '.jpg', '.jpeg', '.png', '.gif', '.webp',  # Images
    '.pdf',  # Documents
    '.doc', '.docx', '.xls', '.xlsx', '.ppt', '.pptx',  # Office
    '.txt', '.md', '.csv', '.json', '.xml',  # Text
    '.zip', '.tar', '.gz'  # Archives
}

db = Database(DATA_DIR / "db" / "team.json")


def get_file_extension(filename: str) -> str:
    """Get file extension from filename"""
    return Path(filename).suffix.lower()


def is_allowed_file(filename: str) -> bool:
    """Check if file extension is allowed"""
    return get_file_extension(filename) in ALLOWED_EXTENSIONS


@router.post("/cards/{card_id}/attachments")
async def upload_attachment(card_id: str, file: UploadFile = File(...)):
    """Upload a file attachment to a card"""
    db.initialize()

    # Verify card exists
    card = db.cards.get(Q.id == card_id)
    if not card:
        raise HTTPException(status_code=404, detail="Card not found")

    # Validate file
    if not file.filename:
        raise HTTPException(status_code=400, detail="No filename provided")

    if not is_allowed_file(file.filename):
        raise HTTPException(
            status_code=400,
            detail=f"File type not allowed. Allowed: {', '.join(ALLOWED_EXTENSIONS)}"
        )

    # Read file content
    content = await file.read()
    if len(content) > MAX_FILE_SIZE:
        raise HTTPException(
            status_code=400,
            detail=f"File too large. Maximum size: {MAX_FILE_SIZE // (1024*1024)}MB"
        )

    # Generate attachment ID and path
    attachment_id = db.generate_id()
    extension = get_file_extension(file.filename)
    stored_filename = f"{attachment_id}{extension}"

    # Create upload directory
    card_uploads_dir = UPLOADS_DIR / card_id
    card_uploads_dir.mkdir(parents=True, exist_ok=True)

    # Save file
    file_path = card_uploads_dir / stored_filename
    with open(file_path, "wb") as f:
        f.write(content)

    # Get content type
    content_type = file.content_type or mimetypes.guess_type(file.filename)[0] or "application/octet-stream"

    # Store metadata in database
    attachment = {
        "id": attachment_id,
        "card_id": card_id,
        "filename": stored_filename,
        "original_filename": file.filename,
        "size": len(content),
        "content_type": content_type,
        "uploaded_at": db.timestamp()
    }
    db.attachments.insert(attachment)

    return attachment


@router.get("/cards/{card_id}/attachments")
async def list_attachments(card_id: str):
    """List all attachments for a card"""
    db.initialize()

    # Verify card exists
    card = db.cards.get(Q.id == card_id)
    if not card:
        raise HTTPException(status_code=404, detail="Card not found")

    attachments = db.attachments.search(Q.card_id == card_id)
    return sorted(attachments, key=lambda x: x.get("uploaded_at", ""), reverse=True)


@router.get("/cards/{card_id}/attachments/{attachment_id}")
async def download_attachment(card_id: str, attachment_id: str):
    """Download an attachment"""
    db.initialize()

    attachment = db.attachments.get((Q.id == attachment_id) & (Q.card_id == card_id))
    if not attachment:
        raise HTTPException(status_code=404, detail="Attachment not found")

    file_path = UPLOADS_DIR / card_id / attachment["filename"]
    if not file_path.exists():
        raise HTTPException(status_code=404, detail="File not found on disk")

    return FileResponse(
        path=str(file_path),
        filename=attachment["original_filename"],
        media_type=attachment["content_type"]
    )


@router.delete("/cards/{card_id}/attachments/{attachment_id}")
async def delete_attachment(card_id: str, attachment_id: str):
    """Delete an attachment"""
    db.initialize()

    attachment = db.attachments.get((Q.id == attachment_id) & (Q.card_id == card_id))
    if not attachment:
        raise HTTPException(status_code=404, detail="Attachment not found")

    # Delete file from disk
    file_path = UPLOADS_DIR / card_id / attachment["filename"]
    if file_path.exists():
        file_path.unlink()

    # Remove from database
    db.attachments.remove((Q.id == attachment_id) & (Q.card_id == card_id))

    return {"deleted": True}
