from typing import Any, Dict, List, Optional, Union

from pydantic import BaseModel, Field


class DocumentToolsInput(BaseModel):
    operation: str = Field(
        ...,
        description="수행할 작업: 'get_summary'(짧은 요약 조회) | 'summarize'(심층 요약) | 'compare'(다중 대상 비교)",
    )
    args: Optional[Dict[str, Any]] = Field(
        default=None,
        description=(
            "작업별 인자 dict. 도구 설명의 operation 별 args 형식을 따르세요. "
            "예: get_summary→{file_ids:[...]}, summarize→{file_id:'..',focus?:'..'}, "
            "compare→{aspects:[..], file_ids?:[..], knowledge_ids?:[..], filters?:{..}}"
        ),
    )


class FilesContentsInput(BaseModel):
    file_ids: Optional[Union[str, List[str]]] = Field(
        default=None,
        description="파일 아이디 목록. 생략하면 업로드된 모든 파일의 컨텐츠를 반환합니다.",
    )


class KnowledgeHandlerInputBase(BaseModel):
    queries: Union[str, List[str]] = Field(
        ...,
        description=(
            "검색어를 **list 로 3~5개** 제공하세요(여러 질의 결과는 순위 융합(RRF)되어 "
            "누락이 줄어듭니다).\n"
            "1) 첫 번째는 **사용자 원본 질문 그대로** — 의미 재구성/단순화/임의 영어 변환/"
            "한국어 보충 표현 삭제 금지.\n"
            "2) 이어서 **서로 다른 관점의 검색 질의 2~4개**를 추가: 핵심 속성별로 분해한 "
            "질의, 동의어·약어, 한/영 용어 혼합, 단위·도메인 용어 포함.\n"
            "특히 비교·다중대상·다속성 질문은 **속성별로 나눈 질의를 반드시 포함**하세요 "
            "(예: '정격 유량 rated flow m3/hr', '정격 양정 total head', '펌프 모델명 model'). "
            "지시문 동사('비교해줘/정리해줘')는 검색어에서 빼고 찾으려는 내용만 담으세요."
        ),
        examples=[
            [
                "태국 수입화물의 import manifest(입항목록) 신고 마감 시간은?",
                "Thailand import manifest submission deadline",
                "태국 입항목록 신고 마감",
            ],
            [
                "펌프 정격 유량 양정 모델 사양",
                "rated flow head pump model capacity datasheet",
                "정격 유량 m3/hr 정격 양정 m 펌프 모델명",
            ],
        ],
    )


class DocumentSummaryInput(BaseModel):
    file_ids: Union[str, List[str]] = Field(
        ...,
        description=(
            "요약을 조회할 문서(파일)의 id 또는 id 목록. "
            "도구 설명의 '조회 가능한 문서 목록'에 있는 id 중에서만 선택하세요."
        ),
    )


class SummarizeDocumentInput(BaseModel):
    file_id: str = Field(
        ...,
        description=(
            "심층 요약할 문서(파일) id. 도구 설명의 '대상 문서 목록'에 있는 id 중에서만 "
            "선택하세요."
        ),
    )
    focus: Optional[str] = Field(
        default=None,
        description=(
            "선택: 특정 관점/주제로 요약 초점을 맞춥니다 (예: '리스크', '비용', "
            "'유지보수', '사양'). 생략하면 문서 전반을 요약합니다."
        ),
    )


class CompareDocumentsInput(BaseModel):
    aspects: Union[str, List[str]] = Field(
        ...,
        description=(
            "비교 기준 검색어를 **list 로 여러 개** 제공하세요(대상마다 각 검색어로 "
            "개별 검색 후 순위 융합(RRF)되어 사양 누락이 줄어듭니다).\n"
            "비교할 속성을 **속성별로 분해**하고 한/영·단위·도메인 용어를 섞으세요. "
            "예: ['정격 유량 rated flow m3/hr', '정격 양정 total head m', '펌프 모델명 model']. "
            "지시문 동사('비교해줘')는 빼고 찾을 내용만 담으세요."
        ),
    )
    file_ids: Optional[List[str]] = Field(
        default=None,
        description=(
            "문서(파일) 단위로 비교할 때 사용. 비교할 파일 id 목록 (2개 이상 권장). "
            "도구 설명의 문서 목록에 있는 id 중에서만 선택하세요."
        ),
    )
    knowledge_ids: Optional[List[str]] = Field(
        default=None,
        description=(
            "지식 기반(프로젝트) 단위로 비교할 때 사용. 비교할 지식 기반 id 목록 "
            "(2개 이상 권장). 도구 설명의 지식 기반 목록에 있는 id 중에서만 선택하세요. "
            "file_ids 와 함께 사용할 수도 있습니다."
        ),
    )


class EvaluateOutput(BaseModel):
    answerable: bool = Field(
        default=False,
        description="검색 결과가 질의에 대한 답변이 가능한 근거인지 판단하고 결과를 반환합니다.",
    )


class SearchInputBase(BaseModel):
    queries: Union[str, List[str]] = Field(
        ...,
        description=(
            "검색어를 제공하세요. **사용자 원본 질문을 그대로 첫 번째 query 로 사용**하고, "
            "의미 재구성 / 단순화 / 임의 영어 변환 / 한국어 보충 표현 삭제는 금지합니다. "
            "추가 검색어를 같이 제공하려면 list 로 전달하세요 (BM25 + dense 양쪽 매칭 강화)."
        ),
    )


class ExtractContextInfoInput(BaseModel):
    language: str = Field(..., description="짧은 언어 식별자 (예: Korean/English 등)")
    normalized_question: str = Field(
        ..., description="질문에서 오탈자나 문맥을 정제한 질문"
    )


class EvaluateSearchResultsOutput(BaseModel):
    eval_score: int = Field(
        ...,
        description="""1~5 사이의 점수를 반환합니다.
    1: 검색 결과가 질의에 대한 답변이 불가능한 근거입니다.
    2: 검색 결과가 질의에 대한 약간의 답변이 가능한 근거입니다.
    3: 검색 결과가 질의에 대한 일부 답변이 가능한 근거입니다.
    4: 검색 결과가 질의에 대한 답변이 충분히 가능한 근거입니다.
    5: 검색 결과가 질의에 대한 답변 및 추가적인 정보를 제공 가능한 근거입니다.""",
    )
    eval_reason: str = Field(
        ...,
        description="검색 결과가 질의에 대한 답변이 가능한 근거인지 판단하는 이유를 반환합니다.",
    )


class WebLoaderToolInput(BaseModel):
    urls: Union[str, List[str]] = Field(
        ...,
        description="웹 페이지 URL을 제공하세요. 해당 URL의 전체 내용을 추출합니다.",
    )


class WebSearchToolInput(BaseModel):
    query: str = Field(
        ...,
        description="""
                목표:
                - 사용자의 질문에 대해 웹에서 정확한 정보를 찾기 위한 "웹검색 최적화 쿼리"를 생성하세요.

                규칙:
                1. 웹검색 엔진에 바로 사용할 수 있는 자연스러운 문장 또는 키워드 조합으로 작성하세요.
                2. 동음이의어나 다의어가 있을 경우, 반드시 **도메인(분야)** 을 명확히 포함하세요.
                   - 예: 커피, 전기, 법률, IT, 의료, 해운, 건설 등
                3. 고유명사(브랜드, 제품명, 회사명, 표준명 등)는 원문 그대로 유지하세요.
                4. 불필요한 조사, 감탄사, 추측 표현은 제거하세요.
                5. 질문의 핵심 개념만 남겨 간결하게 작성하세요.
            """,
    )
