from __future__ import annotations

from pathlib import Path
import shutil
from typing import Protocol
from uuid import uuid4

import boto3
from botocore.config import Config
from fastapi import Depends, FastAPI, File, HTTPException, UploadFile, status
from pydantic import BaseModel
from pydantic_settings import BaseSettings, SettingsConfigDict


MAX_IMAGE_SIZE = 5 * 1024 * 1024
IMAGE_TYPES = {
    "image/jpeg": (b"\xff\xd8\xff", ".jpg"),
    "image/png": (b"\x89PNG\r\n\x1a\n", ".png"),
    "image/webp": (b"RIFF", ".webp"),
}


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

    storage_backend: str = "local"
    local_storage_path: Path = Path("uploads")
    s3_endpoint_url: str | None = None
    s3_region: str = "us-east-1"
    s3_bucket: str = "cloudgallery"
    s3_access_key: str = ""
    s3_secret_key: str = ""


class Storage(Protocol):
    def save(self, upload: UploadFile, key: str) -> None: ...

    def delete(self, key: str) -> None: ...


class StoredFile(BaseModel):
    key: str
    content_type: str
    size: int


files: dict[str, StoredFile] = {}


class LocalStorage:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.root.mkdir(parents=True, exist_ok=True)

    def save(self, upload: UploadFile, key: str) -> None:
        with (self.root / key).open("wb") as destination:
            shutil.copyfileobj(upload.file, destination)

    def list(self) -> list[str]:
        return sorted(path.name for path in self.root.iterdir() if path.is_file())

    def delete(self, key: str) -> None:
        root = self.root.resolve()
        path = (root / key).resolve()
        if not path.is_relative_to(root) or not path.is_file():
            raise FileNotFoundError(key)
        path.unlink()


class S3Storage:
    def __init__(self, settings: Settings) -> None:
        if not settings.s3_access_key or not settings.s3_secret_key:
            raise ValueError("S3 credentials are required for S3 storage")

        self.bucket = settings.s3_bucket
        self.client = boto3.client(
            "s3",
            aws_access_key_id=settings.s3_access_key,
            aws_secret_access_key=settings.s3_secret_key,
            region_name=settings.s3_region,
            endpoint_url=settings.s3_endpoint_url,
            config=Config(signature_version="s3v4"),
        )

    def save(self, upload: UploadFile, key: str) -> None:
        self.client.upload_fileobj(
            upload.file,
            self.bucket,
            key,
            ExtraArgs={"ContentType": upload.content_type or "application/octet-stream"},
        )

    def list(self) -> list[str]:
        response = self.client.list_objects_v2(Bucket=self.bucket)
        return sorted(item["Key"] for item in response.get("Contents", []))

    def delete(self, key: str) -> None:
        self.client.delete_object(Bucket=self.bucket, Key=key)

    def url(self, key: str) -> str:
        return self.client.generate_presigned_url(
            "get_object",
            Params={"Bucket": self.bucket, "Key": key},
            ExpiresIn=3600,
        )


settings = Settings()


def get_storage() -> Storage:
    if settings.storage_backend == "s3":
        return S3Storage(settings)
    return LocalStorage(settings.local_storage_path)

app = FastAPI(title="CloudGallery API")


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "backend": settings.storage_backend}


def _image_extension(content_type: str, header: bytes) -> str | None:
    signature, extension = IMAGE_TYPES[content_type]
    if content_type == "image/webp":
        valid = len(header) >= 12 and header[:4] == signature and header[8:12] == b"WEBP"
    else:
        valid = header.startswith(signature)
    return extension if valid else None


@app.post("/images", status_code=status.HTTP_201_CREATED)
def upload_image(
    image: UploadFile = File(...), storage: Storage = Depends(get_storage)
) -> StoredFile:
    if image.content_type not in IMAGE_TYPES:
        raise HTTPException(status_code=415, detail="Unsupported image type")

    content = image.file.read(MAX_IMAGE_SIZE + 1)
    if len(content) > MAX_IMAGE_SIZE:
        raise HTTPException(status_code=413, detail="Image is too large")

    extension = _image_extension(image.content_type, content[:12])
    if extension is None:
        raise HTTPException(status_code=415, detail="Image signature does not match MIME type")

    key = f"{uuid4().hex}{extension}"
    image.file.seek(0)
    storage.save(image, key)
    stored_file = StoredFile(key=key, content_type=image.content_type, size=len(content))
    files[key] = stored_file
    return stored_file


@app.get("/images")
def list_images() -> list[StoredFile]:
    return list(files.values())


@app.delete("/images/{key}", status_code=status.HTTP_204_NO_CONTENT)
def delete_image(key: str, storage: Storage = Depends(get_storage)) -> None:
    if key not in files:
        raise HTTPException(status_code=404, detail="Image not found")

    try:
        storage.delete(key)
    except FileNotFoundError as error:
        raise HTTPException(status_code=404, detail="Image not found") from error
    files.pop(key)
