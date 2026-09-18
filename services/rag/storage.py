import os
import logging
from abc import ABC, abstractmethod
from typing import Optional, Dict, Any
from apps.api.config import settings

logger = logging.getLogger("hospitality_agent_cloud.storage")

class BaseDocumentStorageProvider(ABC):
    @abstractmethod
    def save_file(self, filename: str, file_bytes: bytes, content_type: str = "application/pdf") -> Dict[str, Any]:
        pass

    @abstractmethod
    def delete_file(self, file_key: str) -> bool:
        pass

class LocalStorageProvider(BaseDocumentStorageProvider):
    def __init__(self, upload_dir: str = "storage/uploads"):
        self.upload_dir = upload_dir
        os.makedirs(self.upload_dir, exist_ok=True)

    def save_file(self, filename: str, file_bytes: bytes, content_type: str = "application/pdf") -> Dict[str, Any]:
        file_path = os.path.join(self.upload_dir, filename)
        with open(file_path, "wb") as f:
            f.write(file_bytes)
        return {
            "provider": "local",
            "file_key": filename,
            "url": f"/storage/uploads/{filename}",
            "size_bytes": len(file_bytes)
        }

    def delete_file(self, file_key: str) -> bool:
        file_path = os.path.join(self.upload_dir, file_key)
        if os.path.exists(file_path):
            os.remove(file_path)
            return True
        return False

class S3DocumentStorageProvider(BaseDocumentStorageProvider):
    def __init__(self):
        self.bucket_name = settings.AWS_S3_BUCKET
        self.region = settings.AWS_REGION
        self.access_key = settings.AWS_ACCESS_KEY_ID
        self.secret_key = settings.AWS_SECRET_ACCESS_KEY

    def save_file(self, filename: str, file_bytes: bytes, content_type: str = "application/pdf") -> Dict[str, Any]:
        if self.access_key and self.secret_key:
            try:
                import boto3
                s3_client = boto3.client(
                    "s3",
                    aws_access_key_id=self.access_key,
                    aws_secret_access_key=self.secret_key,
                    region_name=self.region
                )
                s3_client.put_object(
                    Bucket=self.bucket_name,
                    Key=filename,
                    Body=file_bytes,
                    ContentType=content_type
                )
                url = f"https://{self.bucket_name}.s3.{self.region}.amazonaws.com/{filename}"
                return {
                    "provider": "AWS_S3",
                    "file_key": filename,
                    "url": url,
                    "size_bytes": len(file_bytes)
                }
            except Exception as e:
                logger.warning(f"S3 Upload failed ({e}). Falling back to local storage provider.")
        
        fallback = LocalStorageProvider()
        return fallback.save_file(filename, file_bytes, content_type)

    def delete_file(self, file_key: str) -> bool:
        if self.access_key and self.secret_key:
            try:
                import boto3
                s3_client = boto3.client(
                    "s3",
                    aws_access_key_id=self.access_key,
                    aws_secret_access_key=self.secret_key,
                    region_name=self.region
                )
                s3_client.delete_object(Bucket=self.bucket_name, Key=file_key)
                return True
            except Exception as e:
                logger.warning(f"S3 Delete failed ({e}).")
        return False

def get_storage_provider() -> BaseDocumentStorageProvider:
    if settings.STORAGE_PROVIDER.lower() in ("s3", "aws_s3", "r2"):
        return S3DocumentStorageProvider()
    return LocalStorageProvider()
