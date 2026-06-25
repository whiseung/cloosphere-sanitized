---
paths:
  - "backend/open_webui/routers/audio.py"
  - "backend/open_webui/routers/images.py"
  - "backend/open_webui/routers/files.py"
  - "backend/open_webui/models/files.py"
---

# 오디오/이미지/파일 처리 규칙

## Files 라우터 (routers/files.py)
- `/`: POST 파일 업로드 (UploadFile + FormData)
- `/{id}`: GET 파일 메타데이터, DELETE 삭제
- `/{id}/content`: GET 파일 다운로드 (FileResponse/StreamingResponse)
- `storage_type` 쿼리: "local" 또는 "image" → Storage/ImageStorage 선택
- `has_access_to_file()`: 지식베이스를 통한 간접 접근 권한 체크

## File 모델 스키마
```python
class File(Base):
    __tablename__ = "file"
    id, user_id, filename, path
    data(JSON), meta(JSON)
    created_at, updated_at
```
- `meta`: `{"name": ..., "content_type": ..., "size": ..., "data": {...}}`
- `id`: UUID v4 (파일명 접두사로도 사용)

## Audio 라우터 (routers/audio.py)
- `/transcriptions`: POST STT (음성→텍스트)
- `/speech`: POST TTS (텍스트→음성)
- 프로바이더: OpenAI Whisper, Azure Speech

## Images 라우터 (routers/images.py)
- `/generations`: POST 이미지 생성
- 프로바이더: DALL-E, Automatic1111, ComfyUI
- `/config`: GET/POST 이미지 생성 설정

## 스토리지 분리
- `Storage`: 일반 파일 (문서, 코드 등)
- `ImageStorage`: 이미지 전용 (프로필, 생성 이미지)
- 프로바이더: Local, S3, Azure Blob, GCS

## 참조 파일
- `routers/files.py`: 파일 업로드/다운로드
- `routers/audio.py`: STT/TTS
- `routers/images.py`: 이미지 생성
- `storage/provider.py`: 스토리지 추상화
