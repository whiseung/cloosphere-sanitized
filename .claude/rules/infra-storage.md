---
paths:
  - "backend/open_webui/storage/**/*.py"
---

# 파일 저장소 추상화 규칙

## StorageProvider ABC
```python
class StorageProvider(ABC):
    def get_file(self, file_path: str) -> BinaryIO
    def upload_file(self, file: BinaryIO, filename: str) -> tuple[bytes, str]
    def delete_file(self, file_path: str) -> None
    def delete_all_files(self) -> None
```

## 4종 프로바이더
- `LocalStorageProvider`: 로컬 파일시스템 (DATA_DIR/uploads/)
- `S3StorageProvider`: AWS S3 / 호환 스토리지
  - key prefix, accelerate endpoint, addressing style 지원
- `AzureBlobStorageProvider`: Azure Blob Storage
  - Managed Identity / connection string 지원
- `GoogleCloudStorageProvider`: Google Cloud Storage

## 2개 인스턴스
- `Storage`: 일반 파일 (문서, 코드 등) — STORAGE_PROVIDER 설정
- `ImageStorage`: 이미지 전용 (프로필, 생성 이미지) — IMAGE_STORAGE_PROVIDER 설정

## 동적 프로바이더 전환
- `_get_config_value()`: PersistentConfig와 raw 값 모두 처리
- 런타임에 프로바이더 변경 가능 (관리자 설정)

## 파일 업로드 패턴
```python
storage = ImageStorage if storage_type == "image" else Storage
contents, file_path = storage.upload_file(file.file, filename)
```

## 참조 파일
- `storage/provider.py`: StorageProvider ABC, 프로바이더 구현, Storage/ImageStorage 인스턴스
