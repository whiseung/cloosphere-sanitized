from typing import Any, List, Optional

from pydantic import BaseModel


class VectorItem(BaseModel):
    id: str
    text: str
    vector: List[float | int]
    metadata: Any
    # KB 질의예시 생성 기능용 필드
    sample_questions: Optional[str] = None  # LLM 생성 질의예시 (개행 구분)
    vector_question: Optional[List[float]] = None  # 질의예시 임베딩


class GetResult(BaseModel):
    ids: Optional[List[List[str]]]
    documents: Optional[List[List[str]]]
    metadatas: Optional[List[List[Any]]]


class SearchResult(GetResult):
    distances: Optional[List[List[float | int]]]
