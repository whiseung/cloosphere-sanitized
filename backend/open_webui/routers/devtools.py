"""
Developer Tools Router

개발자 모드 관련 API 엔드포인트.
로케일 파일 관리 등 개발 편의 기능 제공.
"""

import json
import logging
import re
import shutil
from datetime import datetime
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Request, status
from open_webui.env import SRC_LOG_LEVELS
from open_webui.utils.auth import get_admin_user
from open_webui.utils.chat import generate_chat_completion
from pydantic import BaseModel

log = logging.getLogger(__name__)
log.setLevel(SRC_LOG_LEVELS["MODELS"])

router = APIRouter()

# 로케일 파일 경로 (소스 디렉토리 기준)
# 개발 환경에서는 src/lib/i18n/locales, 프로덕션에서는 다른 경로일 수 있음
# __file__ = backend/open_webui/routers/devtools.py
# parent x4 = /cloosphere (프로젝트 루트)
LOCALES_DIR = (
    Path(__file__).parent.parent.parent.parent / "src" / "lib" / "i18n" / "locales"
)


############################
# GetLocales
############################


class LocaleInfo(BaseModel):
    code: str
    title: str


@router.get("/locales", response_model=list[LocaleInfo])
async def get_locales(user=Depends(get_admin_user)):
    """사용 가능한 로케일 목록 조회"""
    languages_file = LOCALES_DIR / "languages.json"

    if not languages_file.exists():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Languages file not found"
        )

    try:
        with open(languages_file, "r", encoding="utf-8") as f:
            languages = json.load(f)
        return languages
    except Exception as e:
        log.exception(f"Error reading languages file: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error reading languages file: {str(e)}",
        )


############################
# GetLocaleTranslations
############################


@router.get("/locales/{locale_code}")
async def get_locale_translations(locale_code: str, user=Depends(get_admin_user)):
    """특정 로케일의 번역 데이터 조회"""
    translation_file = LOCALES_DIR / locale_code / "translation.json"

    if not translation_file.exists():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Locale '{locale_code}' not found",
        )

    try:
        with open(translation_file, "r", encoding="utf-8") as f:
            translations = json.load(f)
        return {"locale": locale_code, "translations": translations}
    except Exception as e:
        log.exception(f"Error reading translation file: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error reading translation file: {str(e)}",
        )


############################
# UpdateLocaleTranslations
############################


class UpdateTranslationsForm(BaseModel):
    translations: dict


@router.post("/locales/{locale_code}")
async def update_locale_translations(
    locale_code: str, form_data: UpdateTranslationsForm, user=Depends(get_admin_user)
):
    """특정 로케일의 번역 데이터 업데이트"""
    translation_file = LOCALES_DIR / locale_code / "translation.json"

    if not translation_file.exists():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Locale '{locale_code}' not found",
        )

    try:
        # 번역 파일 저장 (정렬하여 가독성 확보)
        with open(translation_file, "w", encoding="utf-8") as f:
            json.dump(form_data.translations, f, ensure_ascii=False, indent="\t")
            f.write("\n")  # 파일 끝에 개행 추가

        return {
            "success": True,
            "locale": locale_code,
            "message": f"Translations for '{locale_code}' updated successfully",
        }
    except Exception as e:
        log.exception(f"Error writing translation file: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error writing translation file: {str(e)}",
        )


############################
# UpdateSingleTranslation
############################


class UpdateSingleTranslationForm(BaseModel):
    key: str
    value: str


@router.patch("/locales/{locale_code}")
async def update_single_translation(
    locale_code: str,
    form_data: UpdateSingleTranslationForm,
    user=Depends(get_admin_user),
):
    """특정 로케일의 단일 번역 키 업데이트"""
    translation_file = LOCALES_DIR / locale_code / "translation.json"

    if not translation_file.exists():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Locale '{locale_code}' not found",
        )

    try:
        # 기존 번역 읽기
        with open(translation_file, "r", encoding="utf-8") as f:
            translations = json.load(f)

        # 키 업데이트
        translations[form_data.key] = form_data.value

        # 저장
        with open(translation_file, "w", encoding="utf-8") as f:
            json.dump(translations, f, ensure_ascii=False, indent="\t")
            f.write("\n")

        return {
            "success": True,
            "locale": locale_code,
            "key": form_data.key,
            "value": form_data.value,
        }
    except Exception as e:
        log.exception(f"Error updating translation: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error updating translation: {str(e)}",
        )


############################
# DeleteTranslationKey
############################


class DeleteTranslationForm(BaseModel):
    key: str


@router.delete("/locales/{locale_code}")
async def delete_translation_key(
    locale_code: str, form_data: DeleteTranslationForm, user=Depends(get_admin_user)
):
    """특정 로케일의 번역 키 삭제"""
    translation_file = LOCALES_DIR / locale_code / "translation.json"

    if not translation_file.exists():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Locale '{locale_code}' not found",
        )

    try:
        # 기존 번역 읽기
        with open(translation_file, "r", encoding="utf-8") as f:
            translations = json.load(f)

        # 키 삭제
        if form_data.key in translations:
            del translations[form_data.key]

        # 저장
        with open(translation_file, "w", encoding="utf-8") as f:
            json.dump(translations, f, ensure_ascii=False, indent="\t")
            f.write("\n")

        return {
            "success": True,
            "locale": locale_code,
            "key": form_data.key,
            "deleted": True,
        }
    except Exception as e:
        log.exception(f"Error deleting translation key: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error deleting translation key: {str(e)}",
        )


############################
# SyncTranslations
############################


class SyncTranslationsForm(BaseModel):
    model_id: str
    source_locales: list[str] = ["en-US"]  # 최대 3개까지 참조 로케일
    target_locales: list[str]


class SyncTranslationsResponse(BaseModel):
    success: bool
    results: dict  # locale_code -> {translated: int, failed: int, errors: list}


@router.post("/locales/sync", response_model=SyncTranslationsResponse)
async def sync_translations(
    request: Request, form_data: SyncTranslationsForm, user=Depends(get_admin_user)
):
    """
    AI 모델을 사용하여 빈 번역 값들을 자동 번역

    복수의 소스 로케일(최대 3개)을 참조하여
    타겟 로케일의 빈 값들을 번역합니다.
    """
    # 모델 확인
    models = request.app.state.MODELS
    if form_data.model_id not in models:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Model '{form_data.model_id}' not found",
        )

    # 소스 로케일들 읽기 (최대 3개)
    source_locales = form_data.source_locales[:3]
    source_translations_map = {}  # locale_code -> translations

    for source_locale in source_locales:
        source_file = LOCALES_DIR / source_locale / "translation.json"
        if not source_file.exists():
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Source locale '{source_locale}' not found",
            )
        with open(source_file, "r", encoding="utf-8") as f:
            source_translations_map[source_locale] = json.load(f)

    # 기본 소스 (첫 번째)
    primary_source = source_locales[0]
    primary_translations = source_translations_map[primary_source]

    # languages.json에서 언어 이름 가져오기
    languages_file = LOCALES_DIR / "languages.json"
    languages = {}
    if languages_file.exists():
        with open(languages_file, "r", encoding="utf-8") as f:
            for lang in json.load(f):
                languages[lang["code"]] = lang["title"]

    results = {}

    for target_locale in form_data.target_locales:
        if target_locale in source_locales:
            continue

        target_file = LOCALES_DIR / target_locale / "translation.json"
        if not target_file.exists():
            results[target_locale] = {
                "translated": 0,
                "failed": 0,
                "errors": ["Locale file not found"],
            }
            continue

        with open(target_file, "r", encoding="utf-8") as f:
            target_translations = json.load(f)

        # 백업 파일 생성 (동기화 시작 전)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_file = (
            LOCALES_DIR / target_locale / f"translation.backup.{timestamp}.json"
        )
        try:
            shutil.copy2(target_file, backup_file)
            log.info(f"Created backup file: {backup_file}")
        except Exception as e:
            log.warning(f"Failed to create backup file for {target_locale}: {e}")

        # 빈 값 찾기 (기본 소스에 값이 있는 키만)
        empty_keys = [
            key
            for key, value in target_translations.items()
            if (value is None or value.strip() == "")
            and key in primary_translations
            and primary_translations[key]
        ]

        if not empty_keys:
            results[target_locale] = {"translated": 0, "failed": 0, "errors": []}
            continue

        # 배치로 번역 (한 번에 최대 50개)
        translated_count = 0
        failed_count = 0
        errors = []
        batch_size = 50

        target_lang_name = languages.get(target_locale, target_locale)

        for i in range(0, len(empty_keys), batch_size):
            batch_keys = empty_keys[i : i + batch_size]

            # 번역 참조 데이터 준비 (복수 소스 로케일)
            reference_data = {}
            for key in batch_keys:
                reference_data[key] = {}
                for src_locale in source_locales:
                    src_trans = source_translations_map.get(src_locale, {})
                    if key in src_trans and src_trans[key]:
                        reference_data[key][src_locale] = src_trans[key]

            # 소스 로케일 이름들
            source_lang_names = [languages.get(loc, loc) for loc in source_locales]

            # 프롬프트 생성
            prompt = f"""You are a professional translator. Translate the following UI text to {target_lang_name}.

REFERENCE SOURCES (in order of priority):
{", ".join(source_lang_names)}

IMPORTANT RULES:
1. Keep the translation natural and appropriate for UI/software context
2. Preserve any placeholders like {{{{variable}}}} or {{{{count}}}} exactly as they are
3. Do not add any explanation, just output the JSON
4. Return ONLY a valid JSON object with the same keys
5. For English (en-US) source: the key and value may be identical (e.g., "Save": "Save"). This is intentional - translate the VALUE appropriately for the target language.
6. Use all reference sources to understand context and ensure accurate translation

Reference translations by locale:
{json.dumps(reference_data, ensure_ascii=False, indent=2)}

Output the translated JSON for {target_lang_name} (keys only, with translated values):"""

            payload = {
                "model": form_data.model_id,
                "messages": [{"role": "user", "content": prompt}],
                "stream": False,
                "max_tokens": 4000,
            }

            try:
                response = await generate_chat_completion(
                    request, form_data=payload, user=user
                )

                # 응답에서 JSON 추출
                if hasattr(response, "body"):
                    response_data = json.loads(response.body.decode())
                else:
                    response_data = response

                content = (
                    response_data.get("choices", [{}])[0]
                    .get("message", {})
                    .get("content", "")
                )

                # JSON 블록 추출 (```json ... ``` 형식 처리)
                json_match = re.search(r"```(?:json)?\s*([\s\S]*?)\s*```", content)
                if json_match:
                    content = json_match.group(1)

                # JSON 파싱
                translated = json.loads(content.strip())

                # 번역 결과 적용
                for key, value in translated.items():
                    if key in target_translations and isinstance(value, str):
                        target_translations[key] = value
                        translated_count += 1

            except json.JSONDecodeError as e:
                failed_count += len(batch_keys)
                errors.append(
                    f"JSON parse error in batch {i // batch_size + 1}: {str(e)}"
                )
            except Exception as e:
                failed_count += len(batch_keys)
                errors.append(f"Error in batch {i // batch_size + 1}: {str(e)}")

        # 번역 결과 저장
        if translated_count > 0:
            with open(target_file, "w", encoding="utf-8") as f:
                json.dump(target_translations, f, ensure_ascii=False, indent="\t")
                f.write("\n")

        results[target_locale] = {
            "translated": translated_count,
            "failed": failed_count,
            "errors": errors,
        }

    return {"success": True, "results": results}
