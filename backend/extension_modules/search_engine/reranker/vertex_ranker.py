"""
Reranker - Vertex AI Ranking API 구현

Google Cloud Discovery Engine의 Rank API를 사용하여 검색 결과를 재정렬합니다.
SDK: google.cloud.discoveryengine_v1.RankServiceAsyncClient

인증 우선순위:
1. service_account_key (JSON 문자열) 제공 시 → from_service_account_info()
2. 미제공 시 → Application Default Credentials (ADC)
   - GOOGLE_APPLICATION_CREDENTIALS 환경변수로 로컬 키 파일 지정 가능

project_id 자동 감지:
1. 명시적 project_id 설정 시 → 해당 값 사용
2. 미설정 시 → service_account_key JSON의 project_id 필드에서 추출
3. 둘 다 없으면 → ADC의 기본 프로젝트 사용 (google.auth.default())
"""

import json
import logging
from typing import Dict, List, Optional

from ..models import SearchResult
from .base import RerankerBase

log = logging.getLogger(__name__)

# Vertex AI Ranking API 배치 제한
MAX_RECORDS_PER_REQUEST = 200


class VertexRanker(RerankerBase):
    """
    Vertex AI Ranking API를 사용한 리랭커.

    Args:
        project_id: GCP 프로젝트 ID (선택). 미설정 시 자격증명에서 자동 감지.
        location: 리전 (기본: "global")
        model: 랭킹 모델 (기본: "semantic-ranker-default@latest")
        service_account_key: GCP 서비스 계정 키 JSON 문자열 (선택).
                             미설정 시 ADC 사용 (GOOGLE_APPLICATION_CREDENTIALS 등).
    """

    def __init__(
        self,
        project_id: Optional[str] = None,
        location: str = "global",
        model: str = "semantic-ranker-default@latest",
        service_account_key: Optional[str] = None,
    ):
        self.project_id = project_id or None
        self.location = location
        self.model = model
        self.service_account_key = service_account_key

        self._client = None
        self._ranking_config: Optional[str] = None

    def _resolve_project_id(self) -> str:
        """
        프로젝트 ID를 결정.

        우선순위:
        1. 명시적 project_id
        2. service_account_key JSON의 project_id
        3. google.auth.default()의 기본 프로젝트

        Raises:
            RuntimeError: 프로젝트 ID를 어디서도 찾을 수 없는 경우
        """
        # 1. 명시적 설정
        if self.project_id:
            return self.project_id

        # 2. 서비스 계정 키에서 추출
        if self.service_account_key:
            try:
                key_info = json.loads(self.service_account_key)
                pid = key_info.get("project_id")
                if pid:
                    return pid
            except (json.JSONDecodeError, ValueError):
                pass

        # 3. ADC에서 기본 프로젝트 추출
        try:
            import google.auth

            _, project = google.auth.default()
            if project:
                return project
        except Exception:
            pass

        raise RuntimeError(
            "Vertex AI Ranking API requires a project ID. "
            "Set RERANKER_VERTEX_PROJECT_ID, provide a service account key, "
            "or configure GOOGLE_APPLICATION_CREDENTIALS."
        )

    def _get_ranking_config(self) -> str:
        """ranking_config 경로 반환 (lazy resolve)"""
        if self._ranking_config is None:
            project_id = self._resolve_project_id()
            self._ranking_config = (
                f"projects/{project_id}/locations/{self.location}"
                f"/rankingConfigs/default_ranking_config"
            )
            log.info(f"Vertex AI Ranking config: {self._ranking_config}")
        return self._ranking_config

    async def _get_client(self):
        """RankServiceAsyncClient 인스턴스 생성 (lazy)"""
        if self._client is None:
            try:
                from google.cloud.discoveryengine_v1 import RankServiceAsyncClient
            except ImportError as e:
                raise RuntimeError(
                    "google-cloud-discoveryengine package required. "
                    "Install: pip install google-cloud-discoveryengine"
                ) from e

            if self.service_account_key:
                try:
                    key_info = json.loads(self.service_account_key)
                    self._client = RankServiceAsyncClient.from_service_account_info(
                        key_info
                    )
                except (json.JSONDecodeError, ValueError) as e:
                    log.warning(
                        f"Invalid service account key, falling back to ADC: {e}"
                    )
                    self._client = RankServiceAsyncClient()
            else:
                self._client = RankServiceAsyncClient()

        return self._client

    async def rerank(
        self,
        query: str,
        results: List[SearchResult],
        top_k: int = 10,
        threshold: float = 0.0,
    ) -> List[SearchResult]:
        if not results:
            return []

        try:
            client = await self._get_client()
            ranking_config = self._get_ranking_config()
            from google.cloud.discoveryengine_v1 import RankingRecord, RankRequest

            # SearchResult → RankingRecord 변환 + 원본 매핑
            result_map: Dict[str, SearchResult] = {}
            records: List[RankingRecord] = []
            for r in results:
                result_map[r.id] = r
                records.append(
                    RankingRecord(
                        id=r.id,
                        content=r.content,
                    )
                )

            # 200개 초과 시 배치 분할
            all_ranked: List[RankingRecord] = []
            for i in range(0, len(records), MAX_RECORDS_PER_REQUEST):
                batch = records[i : i + MAX_RECORDS_PER_REQUEST]
                response = await client.rank(
                    request=RankRequest(
                        ranking_config=ranking_config,
                        model=self.model,
                        query=query,
                        records=batch,
                    )
                )
                all_ranked.extend(response.records)

            # 점수 정규화 + threshold 필터링 + top_k 제한
            scored: List[SearchResult] = []
            for record in all_ranked:
                score = record.score  # 이미 0-1 범위
                if score >= threshold:
                    original = result_map.get(record.id)
                    if original:
                        scored.append(
                            SearchResult(
                                id=record.id,
                                content=original.content,
                                score=score,
                                metadata=original.metadata,
                            )
                        )

            scored.sort(key=lambda x: x.score, reverse=True)
            return scored[:top_k]

        except Exception as e:
            # Graceful degradation: API 오류 시 원본 반환
            log.warning(f"Vertex AI Ranking API error, returning original results: {e}")
            filtered = [r for r in results if r.score >= threshold]
            return filtered[:top_k]

    async def close(self) -> None:
        """클라이언트 리소스 정리"""
        if self._client:
            transport = getattr(self._client, "_transport", None)
            if transport and hasattr(transport, "close"):
                await transport.close()
            self._client = None
