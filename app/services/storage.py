import os
from minio import Minio
from typing import Optional

class StorageService:
    def __init__(self):
        self.minio_client = None
        self._init_minio()

    def _init_minio(self):
        endpoint = os.getenv("S3_ENDPOINT", "minio:9000").replace("http://", "")
        access_key = os.getenv("S3_ACCESS_KEY", "minio")
        secret_key = os.getenv("S3_SECRET_KEY", "minio123")
        try:
            self.minio_client = Minio(
                endpoint,
                access_key=access_key,
                secret_key=secret_key,
                secure=False
            )
        except Exception as e:
            print(f"Warning: Could not connect to MinIO: {e}")

    def download_file(self, bucket: str, key: str, destination: str):
        if not self.minio_client:
            raise Exception("MinIO client not initialized")
        self.minio_client.fget_object(bucket, key, destination)

    def upload_file(self, bucket: str, key: str, source: str):
        if not self.minio_client:
            raise Exception("MinIO client not initialized")
        self.minio_client.fput_object(bucket, key, source)
