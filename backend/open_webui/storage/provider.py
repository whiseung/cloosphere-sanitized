import json
import logging
import os
import shutil
import time
from abc import ABC, abstractmethod
from typing import BinaryIO, Optional, Tuple
from urllib.parse import unquote, urlparse

import boto3
from azure.core.exceptions import ResourceNotFoundError
from azure.identity import DefaultAzureCredential
from azure.storage.blob import BlobServiceClient
from botocore.config import Config
from botocore.exceptions import ClientError
from google.cloud import storage
from google.cloud.exceptions import GoogleCloudError, NotFound
from open_webui.config import (
    AZURE_STORAGE_CONTAINER_NAME,
    AZURE_STORAGE_ENDPOINT,
    AZURE_STORAGE_KEY,
    FILE_AZURE_STORAGE_CONTAINER_NAME,
    FILE_AZURE_STORAGE_ENDPOINT,
    FILE_AZURE_STORAGE_KEY,
    FILE_GCS_BUCKET_NAME,
    FILE_GCS_CREDENTIALS_JSON,
    FILE_S3_ACCESS_KEY_ID,
    FILE_S3_BUCKET_NAME,
    FILE_S3_ENDPOINT_URL,
    FILE_S3_KEY_PREFIX,
    FILE_S3_REGION_NAME,
    FILE_S3_SECRET_ACCESS_KEY,
    FILE_STORAGE_PROVIDER,
    GCS_BUCKET_NAME,
    GOOGLE_APPLICATION_CREDENTIALS_JSON,
    GOOGLE_CLOUD_SERVICE_ACCOUNT_KEY,
    S3_ACCESS_KEY_ID,
    S3_ADDRESSING_STYLE,
    S3_BUCKET_NAME,
    S3_ENDPOINT_URL,
    S3_KEY_PREFIX,
    S3_REGION_NAME,
    S3_SECRET_ACCESS_KEY,
    S3_USE_ACCELERATE_ENDPOINT,
    STORAGE_PROVIDER,
    UPLOAD_DIR,
)
from open_webui.constants import ERROR_MESSAGES
from open_webui.env import SRC_LOG_LEVELS

log = logging.getLogger(__name__)
log.setLevel(SRC_LOG_LEVELS["MAIN"])


# Helper function to get config value (supports both PersistentConfig and raw values)
def _get_config_value(config_value):
    """Extract value from PersistentConfig or return raw value."""
    if hasattr(config_value, "value"):
        return config_value.value
    return config_value


class StorageProvider(ABC):
    @abstractmethod
    def get_file(self, file_path: str) -> str:
        pass

    @abstractmethod
    def upload_file(self, file: BinaryIO, filename: str) -> Tuple[bytes, str]:
        pass

    @abstractmethod
    def delete_all_files(self) -> None:
        pass

    @abstractmethod
    def delete_file(self, file_path: str) -> None:
        pass

    def copy_file(self, src_path: str, dst_filename: str) -> str:
        """``src_path`` 의 파일을 ``dst_filename`` 으로 server-side 복제.

        구현체는 가능한 한 download/upload hop 없이 provider 내부 copy
        (S3 ``CopyObject``, Azure ``start_copy_from_url``, GCS ``copy_blob``,
        Local ``shutil.copy``) 를 사용해야 한다. 같은 bucket/container 가정.

        기본 fallback 은 download → upload hop — provider 가 미구현 시에도
        의미적으로는 동작.

        Args:
            src_path: provider 의 path 형식 (Local: absolute, S3: s3://...,
                Azure: https://*.blob.../..., GCS: gs://...)
            dst_filename: 새 파일명 (이름만, prefix/key 는 provider 가 결정)

        Returns:
            복제된 파일의 새 path (upload_file 과 동일 형식).
        """
        # Default fallback — get_file (다운로드) → upload_file (업로드).
        local_path = self.get_file(src_path)
        with open(local_path, "rb") as fh:
            _, new_path = self.upload_file(fh, dst_filename)
        return new_path


class LocalStorageProvider(StorageProvider):
    @staticmethod
    def upload_file(file: BinaryIO, filename: str) -> Tuple[bytes, str]:
        contents = file.read()
        if not contents:
            raise ValueError(ERROR_MESSAGES.EMPTY_CONTENT)
        file_path = f"{UPLOAD_DIR}/{filename}"
        # filename 이 "subdir/name.ext" 형태일 수 있어 중간 디렉토리 자동 생성.
        # 운영 Blob 프로바이더는 슬래시를 가상 폴더로 처리하므로 호출 측 키
        # 컨벤션이 일관됨. exist_ok=True 라 기존 호출자엔 무해.
        os.makedirs(os.path.dirname(file_path), exist_ok=True)
        with open(file_path, "wb") as f:
            f.write(contents)
        return contents, file_path

    @staticmethod
    def get_file(file_path: str) -> str:
        """Handles downloading of the file from local storage."""
        return file_path

    @staticmethod
    def delete_file(file_path: str) -> None:
        """Handles deletion of the file from local storage."""
        filename = file_path.split("/")[-1]
        file_path = f"{UPLOAD_DIR}/{filename}"
        if os.path.isfile(file_path):
            os.remove(file_path)
        else:
            log.warning(f"File {file_path} not found in local storage.")

    @staticmethod
    def copy_file(src_path: str, dst_filename: str) -> str:
        """OS 차원 file copy — read/write 1회로 끝, fs 내부 최적화 활용."""
        if not os.path.isfile(src_path):
            raise FileNotFoundError(f"Source file not found: {src_path}")
        dst_path = f"{UPLOAD_DIR}/{dst_filename}"
        shutil.copy2(src_path, dst_path)
        return dst_path

    @staticmethod
    def delete_all_files() -> None:
        """Handles deletion of all files from local storage."""
        if os.path.exists(UPLOAD_DIR):
            for filename in os.listdir(UPLOAD_DIR):
                file_path = os.path.join(UPLOAD_DIR, filename)
                try:
                    if os.path.isfile(file_path) or os.path.islink(file_path):
                        os.unlink(file_path)  # Remove the file or link
                    elif os.path.isdir(file_path):
                        shutil.rmtree(file_path)  # Remove the directory
                except Exception as e:
                    log.exception(f"Failed to delete {file_path}. Reason: {e}")
        else:
            log.warning(f"Directory {UPLOAD_DIR} not found in local storage.")


class S3StorageProvider(StorageProvider):
    def __init__(
        self,
        bucket_name: Optional[str] = None,
        region_name: Optional[str] = None,
        endpoint_url: Optional[str] = None,
        access_key_id: Optional[str] = None,
        secret_access_key: Optional[str] = None,
        key_prefix: Optional[str] = None,
    ):
        # Use provided values or fall back to config defaults
        _bucket_name = bucket_name or _get_config_value(S3_BUCKET_NAME)
        _region_name = region_name or _get_config_value(S3_REGION_NAME)
        _endpoint_url = endpoint_url or _get_config_value(S3_ENDPOINT_URL) or None
        _access_key_id = access_key_id or _get_config_value(S3_ACCESS_KEY_ID)
        _secret_access_key = secret_access_key or _get_config_value(
            S3_SECRET_ACCESS_KEY
        )
        _key_prefix = (
            key_prefix if key_prefix is not None else _get_config_value(S3_KEY_PREFIX)
        )

        config = Config(
            s3={
                "use_accelerate_endpoint": S3_USE_ACCELERATE_ENDPOINT,
                "addressing_style": S3_ADDRESSING_STYLE,
            },
        )

        # If access key and secret are provided, use them for authentication
        if _access_key_id and _secret_access_key:
            self.s3_client = boto3.client(
                "s3",
                region_name=_region_name,
                endpoint_url=_endpoint_url,
                aws_access_key_id=_access_key_id,
                aws_secret_access_key=_secret_access_key,
                config=config,
            )
        else:
            # If no explicit credentials are provided, fall back to default AWS credentials
            # This supports workload identity (IAM roles for EC2, EKS, etc.)
            self.s3_client = boto3.client(
                "s3",
                region_name=_region_name,
                endpoint_url=_endpoint_url,
                config=config,
            )

        self.bucket_name = _bucket_name
        self.key_prefix = _key_prefix if _key_prefix else ""

    def upload_file(self, file: BinaryIO, filename: str) -> Tuple[bytes, str]:
        """Handles uploading of the file to S3 storage."""
        _, file_path = LocalStorageProvider.upload_file(file, filename)
        try:
            s3_key = os.path.join(self.key_prefix, filename)
            self.s3_client.upload_file(file_path, self.bucket_name, s3_key)
            return (
                open(file_path, "rb").read(),
                "s3://" + self.bucket_name + "/" + s3_key,
            )
        except ClientError as e:
            raise RuntimeError(f"Error uploading file to S3: {e}")

    def get_file(self, file_path: str) -> str:
        """Handles downloading of the file from S3 storage."""
        try:
            s3_key = self._extract_s3_key(file_path)
            local_file_path = self._get_local_file_path(s3_key)
            self.s3_client.download_file(self.bucket_name, s3_key, local_file_path)
            return local_file_path
        except ClientError as e:
            raise RuntimeError(f"Error downloading file from S3: {e}")

    def delete_file(self, file_path: str) -> None:
        """Handles deletion of the file from S3 storage."""
        try:
            s3_key = self._extract_s3_key(file_path)
            self.s3_client.delete_object(Bucket=self.bucket_name, Key=s3_key)
        except ClientError as e:
            raise RuntimeError(f"Error deleting file from S3: {e}")

        # Always delete from local storage
        LocalStorageProvider.delete_file(file_path)

    def copy_file(self, src_path: str, dst_filename: str) -> str:
        """Server-side ``CopyObject`` — 같은 bucket 내 download/upload hop 0."""
        try:
            src_key = self._extract_s3_key(src_path)
            dst_key = os.path.join(self.key_prefix, dst_filename)
            self.s3_client.copy_object(
                Bucket=self.bucket_name,
                CopySource={"Bucket": self.bucket_name, "Key": src_key},
                Key=dst_key,
            )
            return f"s3://{self.bucket_name}/{dst_key}"
        except ClientError as e:
            raise RuntimeError(f"Error copying file in S3: {e}")

    def delete_all_files(self) -> None:
        """Handles deletion of all files from S3 storage."""
        try:
            response = self.s3_client.list_objects_v2(Bucket=self.bucket_name)
            if "Contents" in response:
                for content in response["Contents"]:
                    # Skip objects that were not uploaded from open-webui in the first place
                    if not content["Key"].startswith(self.key_prefix):
                        continue

                    self.s3_client.delete_object(
                        Bucket=self.bucket_name, Key=content["Key"]
                    )
        except ClientError as e:
            raise RuntimeError(f"Error deleting all files from S3: {e}")

        # Always delete from local storage
        LocalStorageProvider.delete_all_files()

    # The s3 key is the name assigned to an object. It excludes the bucket name, but includes the internal path and the file name.
    def _extract_s3_key(self, full_file_path: str) -> str:
        return "/".join(full_file_path.split("//")[1].split("/")[1:])

    def _get_local_file_path(self, s3_key: str) -> str:
        return f"{UPLOAD_DIR}/{s3_key.split('/')[-1]}"


class GCSStorageProvider(StorageProvider):
    def __init__(
        self,
        bucket_name: Optional[str] = None,
        credentials_json: Optional[str] = None,
    ):
        # Use provided values or fall back to config defaults
        _bucket_name = bucket_name or _get_config_value(GCS_BUCKET_NAME)
        _credentials_json = (
            credentials_json
            or _get_config_value(GOOGLE_APPLICATION_CREDENTIALS_JSON)
            or _get_config_value(GOOGLE_CLOUD_SERVICE_ACCOUNT_KEY)
        )

        self.bucket_name = _bucket_name

        if _credentials_json:
            self.gcs_client = storage.Client.from_service_account_info(
                info=json.loads(_credentials_json)
            )
        else:
            # if no credentials json is provided, credentials will be picked up from the environment
            # if running on local environment, credentials would be user credentials
            # if running on a Compute Engine instance, credentials would be from Google Metadata server
            self.gcs_client = storage.Client()
        self.bucket = self.gcs_client.bucket(_bucket_name)

    def upload_file(self, file: BinaryIO, filename: str) -> Tuple[bytes, str]:
        """Handles uploading of the file to GCS storage."""
        contents, file_path = LocalStorageProvider.upload_file(file, filename)
        try:
            blob = self.bucket.blob(filename)
            blob.upload_from_filename(file_path)
            return contents, "gs://" + self.bucket_name + "/" + filename
        except GoogleCloudError as e:
            raise RuntimeError(f"Error uploading file to GCS: {e}")

    def get_file(self, file_path: str) -> str:
        """Handles downloading of the file from GCS storage."""
        try:
            filename = file_path.removeprefix("gs://").split("/")[1]
            local_file_path = f"{UPLOAD_DIR}/{filename}"
            blob = self.bucket.get_blob(filename)
            blob.download_to_filename(local_file_path)

            return local_file_path
        except NotFound as e:
            raise RuntimeError(f"Error downloading file from GCS: {e}")

    def delete_file(self, file_path: str) -> None:
        """Handles deletion of the file from GCS storage."""
        try:
            filename = file_path.removeprefix("gs://").split("/")[1]
            blob = self.bucket.get_blob(filename)
            blob.delete()
        except NotFound as e:
            raise RuntimeError(f"Error deleting file from GCS: {e}")

        # Always delete from local storage
        LocalStorageProvider.delete_file(file_path)

    def copy_file(self, src_path: str, dst_filename: str) -> str:
        """Server-side ``copy_blob`` — 같은 bucket 내 download/upload hop 0."""
        try:
            src_name = src_path.removeprefix("gs://").split("/", 1)[1]
            src_blob = self.bucket.blob(src_name)
            self.bucket.copy_blob(src_blob, self.bucket, dst_filename)
            return f"gs://{self.bucket_name}/{dst_filename}"
        except NotFound as e:
            raise RuntimeError(f"Error copying file in GCS: {e}")

    def delete_all_files(self) -> None:
        """Handles deletion of all files from GCS storage."""
        try:
            blobs = self.bucket.list_blobs()

            for blob in blobs:
                blob.delete()

        except NotFound as e:
            raise RuntimeError(f"Error deleting all files from GCS: {e}")

        # Always delete from local storage
        LocalStorageProvider.delete_all_files()


class AzureStorageProvider(StorageProvider):
    def __init__(
        self,
        endpoint: Optional[str] = None,
        container_name: Optional[str] = None,
        storage_key: Optional[str] = None,
    ):
        # Use provided values or fall back to config defaults
        self.endpoint = endpoint or _get_config_value(AZURE_STORAGE_ENDPOINT)
        self.container_name = container_name or _get_config_value(
            AZURE_STORAGE_CONTAINER_NAME
        )
        _storage_key = storage_key or _get_config_value(AZURE_STORAGE_KEY)

        if _storage_key:
            # Configure using the Azure Storage Account Endpoint and Key
            self.blob_service_client = BlobServiceClient(
                account_url=self.endpoint, credential=_storage_key
            )
        else:
            # Configure using the Azure Storage Account Endpoint and DefaultAzureCredential
            # If the key is not configured, then the DefaultAzureCredential will be used to support Managed Identity authentication
            self.blob_service_client = BlobServiceClient(
                account_url=self.endpoint, credential=DefaultAzureCredential()
            )
        self.container_client = self.blob_service_client.get_container_client(
            self.container_name
        )

    def upload_file(self, file: BinaryIO, filename: str) -> Tuple[bytes, str]:
        """Handles uploading of the file to Azure Blob Storage."""
        contents, file_path = LocalStorageProvider.upload_file(file, filename)
        try:
            blob_client = self.container_client.get_blob_client(filename)
            blob_client.upload_blob(contents, overwrite=True)
            # Blob 업로드 성공 — 로컬 staging 사본 정리 (디스크 누적 방지).
            # blob URL 이 canonical path 라 staging 은 이후 사용되지 않음.
            try:
                os.remove(file_path)
            except OSError:
                pass  # 이미 삭제됐거나 권한 없음 — 무시
            # Use SDK-generated URL for proper encoding of Unicode/special chars
            return contents, blob_client.url
        except Exception as e:
            raise RuntimeError(f"Error uploading file to Azure Blob Storage: {e}")

    def _extract_blob_name(self, file_path: str) -> str:
        """Container 내 blob 경로 추출 — full URL / plain filename 둘 다 지원.

        Container 내부의 nested path (e.g. ``document-templates/pptx/foo.pptx``) 를
        보존해야 ``upload_file`` 이 nested 키로 저장한 blob 을 ``get_file``/``delete_file``
        에서 다시 찾을 수 있다. 이전 구현은 ``split("/")[-1]`` 로 마지막 segment 만
        남겨 nested 키를 사용하는 호출자 (document_templates 라우터 등) 가 silent 한
        404 에 빠졌다.

        full URL: https://acct.blob.core.windows.net/<container>/<key>?<sas>
                  → urlparse 로 path 추출 → container 이름 prefix 제거 → <key>
        plain key (slash 포함 가능): 그대로 (SAS '?' 만 제거)
        """
        if "://" in file_path:
            parsed = urlparse(file_path)
            path = parsed.path.lstrip("/")
            prefix = f"{self.container_name}/"
            if path.startswith(prefix):
                path = path[len(prefix) :]
            return unquote(path)
        # plain key — nested path 유지, SAS 가 단독으로 ? 뒤에 붙은 케이스 방어
        return unquote(file_path.split("?")[0])

    def get_file(self, file_path: str) -> str:
        """Handles downloading of the file from Azure Blob Storage."""
        filename = self._extract_blob_name(file_path)
        local_file_path = f"{UPLOAD_DIR}/{filename}"
        # nested key 지원: ``document-templates/pptx/foo.pptx`` 같은 키도 정상 staging.
        os.makedirs(os.path.dirname(local_file_path), exist_ok=True)
        try:
            blob_client = self.container_client.get_blob_client(filename)
            with open(local_file_path, "wb") as download_file:
                download_file.write(blob_client.download_blob().readall())
            return local_file_path
        except ResourceNotFoundError as e:
            # 실패 시 0-byte 잔재 파일 정리 — 다음 호출이 stale empty file 을 읽고
            # 잘못된 성공 신호를 주는 걸 막는다.
            try:
                if os.path.exists(local_file_path):
                    os.remove(local_file_path)
            except OSError:
                pass
            raise RuntimeError(f"Error downloading file from Azure Blob Storage: {e}")

    def delete_file(self, file_path: str) -> None:
        """Handles deletion of the file from Azure Blob Storage."""
        try:
            filename = self._extract_blob_name(file_path)
            blob_client = self.container_client.get_blob_client(filename)
            blob_client.delete_blob()
        except ResourceNotFoundError as e:
            raise RuntimeError(f"Error deleting file from Azure Blob Storage: {e}")

        # Always delete from local storage
        LocalStorageProvider.delete_file(file_path)

    def copy_file(self, src_path: str, dst_filename: str) -> str:
        """Server-side copy via ``start_copy_from_url``. 같은 container 내라
        대부분 즉시 완료 — pending 시 짧게 poll."""
        try:
            src_filename = self._extract_blob_name(src_path)
            src_blob = self.container_client.get_blob_client(src_filename)
            dst_blob = self.container_client.get_blob_client(dst_filename)
            dst_blob.start_copy_from_url(src_blob.url)
            # 같은 container 내 copy 는 보통 sync 완료지만 status 확인.
            for _ in range(30):  # max ~30 * 0.5s = 15s
                props = dst_blob.get_blob_properties()
                status = props.copy.status
                if status == "success":
                    return dst_blob.url
                if status in ("failed", "aborted"):
                    raise RuntimeError(
                        f"Azure copy {status}: {props.copy.status_description}"
                    )
                time.sleep(0.5)
            raise RuntimeError("Azure copy timeout")
        except ResourceNotFoundError as e:
            raise RuntimeError(f"Error copying file in Azure Blob Storage: {e}")

    def delete_all_files(self) -> None:
        """Handles deletion of all files from Azure Blob Storage."""
        try:
            blobs = self.container_client.list_blobs()
            for blob in blobs:
                self.container_client.delete_blob(blob.name)
        except Exception as e:
            raise RuntimeError(f"Error deleting all files from Azure Blob Storage: {e}")

        # Always delete from local storage
        LocalStorageProvider.delete_all_files()


def get_storage_provider(
    storage_provider: str,
    s3_config: Optional[dict] = None,
    gcs_config: Optional[dict] = None,
    azure_config: Optional[dict] = None,
) -> StorageProvider:
    """
    Create a storage provider instance.

    Args:
        storage_provider: Provider type ('local', 's3', 'gcs', 'azure')
        s3_config: Optional S3 configuration dict with keys:
            bucket_name, region_name, endpoint_url, access_key_id, secret_access_key, key_prefix
        gcs_config: Optional GCS configuration dict with keys:
            bucket_name, credentials_json
        azure_config: Optional Azure configuration dict with keys:
            endpoint, container_name, storage_key
    """
    if storage_provider == "local":
        return LocalStorageProvider()
    elif storage_provider == "s3":
        if s3_config:
            return S3StorageProvider(
                bucket_name=s3_config.get("bucket_name"),
                region_name=s3_config.get("region_name"),
                endpoint_url=s3_config.get("endpoint_url"),
                access_key_id=s3_config.get("access_key_id"),
                secret_access_key=s3_config.get("secret_access_key"),
                key_prefix=s3_config.get("key_prefix"),
            )
        return S3StorageProvider()
    elif storage_provider == "gcs":
        if gcs_config:
            return GCSStorageProvider(
                bucket_name=gcs_config.get("bucket_name"),
                credentials_json=gcs_config.get("credentials_json"),
            )
        return GCSStorageProvider()
    elif storage_provider == "azure":
        if azure_config:
            return AzureStorageProvider(
                endpoint=azure_config.get("endpoint"),
                container_name=azure_config.get("container_name"),
                storage_key=azure_config.get("storage_key"),
            )
        return AzureStorageProvider()
    else:
        raise RuntimeError(f"Unsupported storage provider: {storage_provider}")


class StorageManager:
    """
    Storage manager that allows dynamic reconfiguration of the storage provider.
    Used for media/image uploads — provider is configurable via admin settings.
    """

    def __init__(self, config=None):
        self._provider: Optional[StorageProvider] = None
        self._provider_type: Optional[str] = None
        self._config = config if config is not None else STORAGE_PROVIDER

    def _get_default_provider(self) -> StorageProvider:
        """Get or create the default storage provider from config."""
        provider_type = _get_config_value(self._config)
        if self._provider is None or self._provider_type != provider_type:
            self._provider = get_storage_provider(provider_type)
            self._provider_type = provider_type
        return self._provider

    def reinitialize(
        self,
        storage_provider: Optional[str] = None,
        s3_config: Optional[dict] = None,
        gcs_config: Optional[dict] = None,
        azure_config: Optional[dict] = None,
    ) -> None:
        """
        Reinitialize the storage provider with new configuration.
        If no arguments provided, reloads from PersistentConfig.
        """
        provider_type = storage_provider or _get_config_value(self._config)
        self._provider = get_storage_provider(
            provider_type,
            s3_config=s3_config,
            gcs_config=gcs_config,
            azure_config=azure_config,
        )
        self._provider_type = provider_type
        log.info(f"Storage provider reinitialized to: {provider_type}")

    def get_file(self, file_path: str) -> str:
        return self._get_default_provider().get_file(file_path)

    def upload_file(self, file: BinaryIO, filename: str) -> Tuple[bytes, str]:
        return self._get_default_provider().upload_file(file, filename)

    def delete_file(self, file_path: str) -> None:
        return self._get_default_provider().delete_file(file_path)

    def delete_all_files(self) -> None:
        return self._get_default_provider().delete_all_files()

    def copy_file(self, src_path: str, dst_filename: str) -> str:
        return self._get_default_provider().copy_file(src_path, dst_filename)

    @property
    def provider_type(self) -> str:
        """Get the current provider type."""
        return self._provider_type or _get_config_value(self._config)


class LocalStorageManager(StorageManager):
    """
    Storage manager that is always fixed to local filesystem.
    Used for general file uploads (documents, PDFs, etc.) — SMB 등 로컬 마운트 경로 사용.
    STORAGE_PROVIDER 설정값과 무관하게 항상 로컬 저장소를 사용.
    """

    def _get_default_provider(self) -> StorageProvider:
        if self._provider is None:
            self._provider = LocalStorageProvider()
            self._provider_type = "local"
        return self._provider

    def reinitialize(self, **kwargs) -> None:
        # 로컬 파일 스토리지는 재초기화 불필요 — 항상 로컬
        log.info("LocalStorageManager: reinitialize ignored (always local)")


class FileStorageManager(StorageManager):
    """
    Storage manager for general file uploads (documents, PDFs, etc.).
    Uses FILE_STORAGE_PROVIDER and FILE_S3_*/FILE_AZURE_*/FILE_GCS_* credentials
    independently from the image storage configuration.
    """

    def __init__(self):
        super().__init__(config=FILE_STORAGE_PROVIDER)

    def _get_default_provider(self) -> StorageProvider:
        """Get or create the file storage provider using file-specific credentials."""
        provider_type = _get_config_value(FILE_STORAGE_PROVIDER)

        # AZURE_STORAGE_MEDIA_* 가 환경에 있고 사용자가 명시적으로 FILE_STORAGE_PROVIDER
        # 를 지정하지 않은 경우, DB 에 stale 한 "local" 값이 박혀있어도 azure 로 강제
        # fallback. 이미지/미디어용 Azure 컨테이너를 파일 저장에도 재사용해 .env 에
        # 동일한 SAS 두 번 박지 않도록 하는 편의 동작.
        if (
            provider_type == "local"
            and not os.environ.get("FILE_STORAGE_PROVIDER")
            and os.environ.get("AZURE_STORAGE_MEDIA_BASE_URL")
        ):
            provider_type = "azure"
        if self._provider is None or self._provider_type != provider_type:
            if provider_type == "s3":
                self._provider = get_storage_provider(
                    "s3",
                    s3_config={
                        "bucket_name": _get_config_value(FILE_S3_BUCKET_NAME),
                        "region_name": _get_config_value(FILE_S3_REGION_NAME),
                        "endpoint_url": _get_config_value(FILE_S3_ENDPOINT_URL) or None,
                        "access_key_id": _get_config_value(FILE_S3_ACCESS_KEY_ID)
                        or None,
                        "secret_access_key": _get_config_value(
                            FILE_S3_SECRET_ACCESS_KEY
                        )
                        or None,
                        "key_prefix": _get_config_value(FILE_S3_KEY_PREFIX),
                    },
                )
            elif provider_type == "gcs":
                self._provider = get_storage_provider(
                    "gcs",
                    gcs_config={
                        "bucket_name": _get_config_value(FILE_GCS_BUCKET_NAME),
                        "credentials_json": _get_config_value(FILE_GCS_CREDENTIALS_JSON)
                        or None,
                    },
                )
            elif provider_type == "azure":
                # 동일 fallback: PersistentConfig 값이 (DB 에) 비어있으면
                # AZURE_STORAGE_MEDIA_* env 로 채움. config.py 의 env_value
                # fallback 과 함께 동작 — 신규 설치는 config.py 가, stale DB
                # 케이스는 여기가 커버.
                self._provider = get_storage_provider(
                    "azure",
                    azure_config={
                        "endpoint": _get_config_value(FILE_AZURE_STORAGE_ENDPOINT)
                        or os.environ.get("AZURE_STORAGE_MEDIA_BASE_URL", ""),
                        "container_name": _get_config_value(
                            FILE_AZURE_STORAGE_CONTAINER_NAME
                        )
                        or os.environ.get("AZURE_STORAGE_MEDIA_CONTAINER", ""),
                        "storage_key": (
                            _get_config_value(FILE_AZURE_STORAGE_KEY)
                            or os.environ.get("AZURE_STORAGE_MEDIA_SAS_KEY")
                            or None
                        ),
                    },
                )
            else:
                self._provider = get_storage_provider("local")
            self._provider_type = provider_type
        return self._provider


# General file uploads (documents, PDFs, etc.) — FILE_STORAGE_PROVIDER + 독립 자격증명
Storage = FileStorageManager()

# Media/image uploads — configurable via admin settings (STORAGE_PROVIDER)
ImageStorage = StorageManager()
