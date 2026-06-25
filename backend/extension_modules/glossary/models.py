"""
Glossary - Pydantic 모델 정의
"""

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field


class GlossaryEntryInput(BaseModel):
    """용어집 용어 입력 모델"""

    id: str = Field(..., description="용어 ID")
    glossary_id: str = Field(..., description="소속 용어집 ID (collection으로 사용)")
    term: str = Field(..., description="용어")
    synonyms: list[str] = Field(default_factory=list, description="유사어/동의어 목록")
    description: str = Field(default="", description="용어 정의/설명")
    example: str = Field(default="", description="예문")
    category: Optional[str] = Field(default=None, description="카테고리 분류")

    def to_embedding_content(self) -> str:
        """
        임베딩용 컨텐츠 생성.

        용어, 유사어, 설명, 예문을 하나의 텍스트로 결합합니다.

        Returns:
            str: 임베딩에 사용할 결합된 텍스트
        """
        parts = [self.term]

        if self.synonyms:
            parts.append(f"유사어: {', '.join(self.synonyms)}")

        if self.description:
            parts.append(f"설명: {self.description}")

        if self.example:
            parts.append(f"예문: {self.example}")

        return "\n".join(parts)


class GlossarySearchResult(BaseModel):
    """용어집 검색 결과 모델"""

    id: str = Field(..., description="용어 ID")
    glossary_id: str = Field(..., description="소속 용어집 ID")
    term: str = Field(..., description="용어")
    synonyms: list[str] = Field(default_factory=list, description="유사어 목록")
    description: str = Field(default="", description="용어 설명")
    example: str = Field(default="", description="예문")
    category: Optional[str] = Field(default=None, description="카테고리")
    score: float = Field(..., description="검색 관련성 점수")
    created_at: Optional[datetime] = Field(default=None, description="생성 시간")
    updated_at: Optional[datetime] = Field(default=None, description="수정 시간")
