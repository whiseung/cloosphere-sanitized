import asyncio
import json
import logging
import os
from typing import Any, Dict, Iterable, List, Optional, Type, Union

from pydantic import BaseModel, model_validator

log = logging.getLogger(__name__)
# log.setLevel(SRC_LOG_LEVELS["CUSTOM"])


def _require_sdk():
    try:
        import azure.search.documents.aio  # noqa: F401

        return True
    except Exception as e:
        raise RuntimeError(
            "azure-search-documents 패키지가 필요합니다. pip install azure-search-documents"
        ) from e


def _get_env(name: str, default: Optional[str] = None) -> Optional[str]:
    return os.getenv(name, default)


class SearchSchemaBase(BaseModel):
    index_name: str
    id_field: str = "id"
    select_fields: Optional[Union[str, List[str]]] = None
    text_search_fields: Optional[Union[str, List[str]]] = None
    vector_query_fields: Optional[Union[str, List[str]]] = None
    semantic_configuration_name: Optional[str] = None
    # OData filter expression, e.g. "category eq 'news' and year ge 2024"
    filter_expression: Optional[str] = None
    match_filter_expression: Optional[str] = None

    @model_validator(mode="after")
    def ensure_fields(self):
        def to_list(val, fallback=None):
            if isinstance(val, str):
                return [val]
            if isinstance(val, list):
                return list(val)
            return list(fallback) if fallback is not None else []

        sel = to_list(self.select_fields, [])
        self.select_fields = list(dict.fromkeys(sel))

        txt_fallback = [self.select_fields[0]] if self.select_fields else []
        txt = to_list(self.text_search_fields, txt_fallback)
        self.text_search_fields = list(dict.fromkeys(txt))

        vec_fallback = [self.text_search_fields[0]] if self.text_search_fields else []
        vec = to_list(self.vector_query_fields, vec_fallback)
        self.vector_query_fields = list(dict.fromkeys(vec))

        if (
            isinstance(self.semantic_configuration_name, str)
            and not self.semantic_configuration_name.strip()
        ):
            self.semantic_configuration_name = None
        return self


class AsyncAzureSearchClient:
    """
    Azure AI Search 비동기 검색 전용 클라이언트.

    - 다양한 인덱스 스키마 정규화를 위해 normalizer를 주입
    - 컬렉션/쿼리 다건을 비동기 병렬 처리 후 score 기준 상위 limit 반환
    """

    def __init__(
        self,
        *,
        endpoint: Optional[str] = None,
        api_key: Optional[str] = None,
    ) -> None:
        _require_sdk()
        from azure.core.credentials import AzureKeyCredential
        from azure.search.documents.aio import SearchClient

        self.endpoint = endpoint or (_get_env("AZURE_SEARCH_ENDPOINT") or "")
        self.api_key = api_key or (_get_env("AZURE_SEARCH_API_KEY") or "")
        if not (self.endpoint and self.api_key):
            raise RuntimeError("Azure Search 환경변수(endpoint/key)가 필요합니다.")

        self._client_cache: Dict[str, SearchClient] = {}
        self._credential = AzureKeyCredential(self.api_key)

    async def aclose(self) -> None:
        for c in list(self._client_cache.values()):
            try:
                await c.close()
            except Exception:
                pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        await self.aclose()

    def _get_client(self, index_name: str):
        from azure.search.documents.aio import SearchClient

        cli = self._client_cache.get(index_name)
        if cli is None:
            cli = SearchClient(
                endpoint=self.endpoint,
                index_name=index_name,
                credential=self._credential,
            )
            self._client_cache[index_name] = cli
        return cli

    async def _asearch_hybrid_single(
        self,
        schema: SearchSchemaBase,
        query: str,
        topk: int,
        topk_vector: int,
        item_model: Optional[Type[BaseModel]] = None,
    ) -> List[Union[Dict[str, Any], BaseModel]]:
        from azure.search.documents.models import VectorizableTextQuery

        client = self._get_client(schema.index_name)

        vqs: List[VectorizableTextQuery] = []
        for vf in schema.vector_query_fields or []:
            vqs.append(
                VectorizableTextQuery(
                    text=query,
                    fields=vf,
                    k_nearest_neighbors=topk_vector,
                    exhaustive=True,
                )
            )

        select_fields = list(schema.select_fields or [])

        params: Dict[str, Any] = {
            "search_text": query,
            "vector_queries": vqs if vqs else None,
            "search_fields": (schema.text_search_fields or None),
            "top": topk,
            "select": ",".join(select_fields),
        }
        if schema.filter_expression:
            params["filter"] = schema.filter_expression
        if schema.semantic_configuration_name:
            params["query_type"] = "semantic"
            params["semantic_configuration_name"] = schema.semantic_configuration_name
        if schema.match_filter_expression:
            params["match_filter_expression"] = schema.match_filter_expression

        params = {k: v for k, v in params.items() if v is not None}

        async def run_once(p: Dict[str, Any]) -> List[Union[Dict[str, Any], BaseModel]]:
            results = await client.search(**p)
            out: List[Union[Dict[str, Any], BaseModel]] = []
            async for r in results:
                rec = {f: r.get(f) for f in select_fields}
                score = r.get("@search.score", 0.0)
                reranker_score = r.get("@search.reranker_score", 0.0)
                try:
                    score = float(score)
                    reranker_score = float(reranker_score)
                except Exception:
                    score = 0.0
                    reranker_score = 0.0
                rec["score"] = score
                rec["reranker_score"] = reranker_score
                rec["query"] = query
                # stable dedup key: prefer id_field if present in selected fields
                key_val = rec.get(schema.id_field)
                if key_val is None:
                    try:
                        key_val = json.dumps(
                            {k: rec.get(k) for k in select_fields},
                            sort_keys=True,
                            ensure_ascii=False,
                        )
                    except Exception:
                        key_val = None
                rec["_key"] = key_val
                if item_model is not None:
                    # filter to declared fields
                    try:
                        model_fields = getattr(item_model, "model_fields", None)
                        if isinstance(model_fields, dict):
                            filtered = {
                                k: v for k, v in rec.items() if k in model_fields
                            }
                        else:
                            filtered = rec
                        out.append(item_model(**filtered))
                    except Exception:
                        # fallback to raw dict if instantiation fails
                        out.append(rec)
                else:
                    out.append(rec)
            return out

        try:
            return await run_once(params)
        except Exception:
            params.pop("query_type", None)
            params.pop("semantic_configuration_name", None)
            return await run_once(params)

    async def asearch_hybrid(
        self,
        *,
        schemas: Union[SearchSchemaBase, Iterable[SearchSchemaBase]],
        queries: Union[str, Iterable[str]],
        top_k: int = 5,
        top_k_vector: int = 10,
        item_model: Optional[Type[BaseModel]] = None,
        reranker_threshold: float = 2.0,
    ) -> Dict[str, List[Union[Dict[str, Any], BaseModel]]]:
        schemas_list: List[SearchSchemaBase] = (
            [schemas] if isinstance(schemas, SearchSchemaBase) else list(schemas)
        )
        qs: List[str] = [queries] if isinstance(queries, str) else list(queries)
        if not schemas_list or not qs:
            return {"items": []}

        tasks = [
            self._asearch_hybrid_single(
                s, q, top_k, top_k_vector, item_model=item_model
            )
            for s in schemas_list
            for q in qs
        ]
        batches = await asyncio.gather(*tasks, return_exceptions=True)

        all_items: List[Union[Dict[str, Any], BaseModel]] = []
        for b in batches:
            if isinstance(b, Exception):
                log.debug(f"asearch_hybrid task error: {b}")
                raise b
            all_items.extend(b)

        if not all_items:
            return {"items": []}

        # deduplicate by _key (or by serialized record if missing)
        merged: Dict[str, Dict[str, Any]] = {}
        for x in all_items:
            # normalize to dict
            if isinstance(x, BaseModel):
                rec = x.model_dump()
            else:
                rec = dict(x)
            key = rec.get("_key")
            if key is None:
                try:
                    key = json.dumps(rec, sort_keys=True, ensure_ascii=False)
                except Exception:
                    key = str(rec)
            cur = merged.get(key)
            if cur is None:
                # initialize queries as set
                qset = set()
                if rec.get("query"):
                    qset.add(rec.get("query"))
                rec["queries"] = list(qset)
                merged[key] = rec
            else:
                # keep max score
                try:
                    if float(rec.get("score", 0.0)) > float(cur.get("score", 0.0)):
                        # update fields from better record
                        for k, v in rec.items():
                            if k not in {"queries"}:
                                cur[k] = v
                except Exception:
                    pass
                # merge queries
                qset = set(cur.get("queries", []))
                if rec.get("query"):
                    qset.add(rec.get("query"))
                cur["queries"] = list(qset)

        deduped_items = list(merged.values())

        def get_score(x: Dict[str, Any]) -> float:
            try:
                val = x.get("score", 0.0)
                return float(val)
            except Exception:
                return 0.0

        deduped_items.sort(key=get_score, reverse=True)
        top = []
        i = 0
        for item in deduped_items:
            reranker_score = item.get("reranker_score")
            if i >= top_k:
                break
            if reranker_score >= reranker_threshold:
                reranker_pct = min(max(reranker_score / 4, 0), 1)
                item["score"] = reranker_pct
                top.append(item)
                i += 1
        # remove helper fields
        for rec in top:
            rec.pop("_key", None)
            rec.pop("query", None)
        return {"items": top}
