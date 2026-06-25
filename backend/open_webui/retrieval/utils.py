import asyncio
import hashlib
import logging
import os
from typing import Optional, Union

from huggingface_hub import snapshot_download
from open_webui.config import (
    RAG_EMBEDDING_PREFIX_FIELD_NAME,
    RAG_EMBEDDING_QUERY_PREFIX,
)
from open_webui.env import (
    ENABLE_FORWARD_USER_INFO_HEADERS,
    OFFLINE_MODE,
    SRC_LOG_LEVELS,
)
from open_webui.models.files import Files
from open_webui.models.usage import UsageMessageType, Usages
from open_webui.models.users import UserModel
from open_webui.retrieval.embedding_retry import (
    EMBEDDING_MAX_CONCURRENCY,
    embedding_retry,
    post_embedding_request,
)
from open_webui.retrieval.vector.connector import VECTOR_DB_CLIENT

log = logging.getLogger(__name__)
log.setLevel(SRC_LOG_LEVELS["RAG"])


async def query_doc(
    collection_name: str, query_embedding: list[float], k: int, user: UserModel = None
):
    try:
        log.debug(f"query_doc:doc {collection_name}")
        result = VECTOR_DB_CLIENT.search(
            collection_name=collection_name,
            vectors=[query_embedding],
            limit=k,
        )

        if result:
            log.info(f"query_doc:result {result.ids} {result.metadatas}")

        return result
    except Exception as e:
        log.exception(f"Error querying doc {collection_name} with limit {k}: {e}")
        raise e


def get_doc(collection_name: str, user: UserModel = None):
    try:
        log.debug(f"get_doc:doc {collection_name}")
        result = VECTOR_DB_CLIENT.get(collection_name=collection_name)

        if result:
            log.info(f"query_doc:result {result.ids} {result.metadatas}")

        return result
    except Exception as e:
        log.exception(f"Error getting doc {collection_name}: {e}")
        raise e


def merge_get_results(get_results: list[dict]) -> dict:
    # Initialize lists to store combined data
    combined_documents = []
    combined_metadatas = []
    combined_ids = []

    for data in get_results:
        combined_documents.extend(data["documents"][0])
        combined_metadatas.extend(data["metadatas"][0])
        combined_ids.extend(data["ids"][0])

    # Create the output dictionary
    result = {
        "documents": [combined_documents],
        "metadatas": [combined_metadatas],
        "ids": [combined_ids],
    }

    return result


def merge_and_sort_query_results(query_results: list[dict], k: int) -> dict:
    # Initialize lists to store combined data
    combined = dict()  # To store documents with unique document hashes

    for data in query_results:
        distances = data["distances"][0]
        documents = data["documents"][0]
        metadatas = data["metadatas"][0]

        for distance, document, metadata in zip(distances, documents, metadatas):
            if isinstance(document, str):
                doc_hash = hashlib.md5(
                    document.encode()
                ).hexdigest()  # Compute a hash for uniqueness

                if doc_hash not in combined.keys():
                    combined[doc_hash] = (distance, document, metadata)
                    continue  # if doc is new, no further comparison is needed

                # if doc is alredy in, but new distance is better, update
                if distance > combined[doc_hash][0]:
                    combined[doc_hash] = (distance, document, metadata)

    combined = list(combined.values())
    # Sort the list based on distances
    combined.sort(key=lambda x: x[0], reverse=True)

    # Slice to keep only the top k elements
    sorted_distances, sorted_documents, sorted_metadatas = (
        zip(*combined[:k]) if combined else ([], [], [])
    )

    # Create and return the output dictionary
    return {
        "distances": [list(sorted_distances)],
        "documents": [list(sorted_documents)],
        "metadatas": [list(sorted_metadatas)],
    }


def get_all_items_from_collections(collection_names: list[str]) -> dict:
    results = []

    for collection_name in collection_names:
        if collection_name:
            try:
                result = get_doc(collection_name=collection_name)
                if result is not None:
                    results.append(result.model_dump())
            except Exception as e:
                log.exception(f"Error when querying the collection: {e}")
        else:
            pass

    return merge_get_results(results)


async def query_collection(
    collection_names: list[str],
    queries: list[str],
    embedding_function,
    k: int,
    user: UserModel = None,
    chat_id: str = None,
    embedding_model: str = None,
) -> dict:
    results = []
    for query in queries:
        log.debug(f"query_collection:query {query}")
        query_embedding = await embedding_function(
            query, prefix=RAG_EMBEDDING_QUERY_PREFIX, user=user, chat_id=chat_id
        )

        # Record query embedding usage if user and chat_id are provided
        # Note: Usage is already recorded in generate_embeddings for OpenAI/Ollama
        # This is a fallback for other embedding engines or when not already tracked
        if user and chat_id and embedding_model:
            _record_query_embedding_usage(
                user_id=user.id,
                chat_id=chat_id,
                model=embedding_model,
                query=query,
            )

        for collection_name in collection_names:
            if collection_name:
                try:
                    result = await query_doc(
                        collection_name=collection_name,
                        k=k,
                        query_embedding=query_embedding,
                    )
                    if result is not None:
                        results.append(result.model_dump())
                except Exception as e:
                    log.exception(f"Error when querying the collection: {e}")
            else:
                pass

    return merge_and_sort_query_results(results, k=k)


def _record_query_embedding_usage(
    user_id: str,
    chat_id: str,
    model: str,
    query: str,
) -> None:
    """Record query embedding usage (fallback when not tracked by embedding engine)."""
    # Skip if already tracked by generate_embeddings functions
    # This is a no-op placeholder that can be extended if needed
    pass


def get_embedding_function(
    embedding_engine,
    embedding_model,
    embedding_function,
    url,
    key,
    embedding_batch_size,
    azure_api_version=None,
    vertex_ai_project_id=None,
    vertex_ai_location=None,
    vertex_ai_service_account_key=None,
    google_cloud_service_account_key=None,
):
    effective_vertex_key = (
        vertex_ai_service_account_key or google_cloud_service_account_key
    )
    func = lambda query, prefix=None, user=None, chat_id=None: generate_embeddings(
        engine=embedding_engine,
        model=embedding_model,
        text=query,
        prefix=prefix,
        url=url,
        key=key,
        user=user,
        chat_id=chat_id,
        azure_api_version=azure_api_version,
        vertex_ai_project_id=vertex_ai_project_id,
        vertex_ai_location=vertex_ai_location,
        vertex_ai_service_account_key=effective_vertex_key,
    )
    if embedding_engine == "":
        return (
            lambda query,
            prefix=None,
            user=None,
            chat_id=None: embedding_function.encode(
                query, **({"prompt": prefix} if prefix else {})
            ).tolist()
        )
    elif embedding_engine in [
        "ollama",
        "openai",
        "azure_openai",
        "gemini",
        "vertex_ai",
    ]:

        async def generate_multiple(query, prefix, user, chat_id, func):
            if isinstance(query, list):
                # Split into batches
                batches = [
                    query[i : i + embedding_batch_size]
                    for i in range(0, len(query), embedding_batch_size)
                ]

                # 한 임베딩 호출 내 배치 fan-out 의 동시 실행 수를 semaphore 로
                # 제한해 burst 를 줄인다 (0=무제한). per-call 범위라 요청 간/워커
                # 간 전역 제한은 아니며, 실제 방벽은 embedding_retry 의 backoff.
                # 전역 동시성 제한이 필요하면 Redis limiter 로 추후 확장.
                loop = asyncio.get_event_loop()
                semaphore = (
                    asyncio.Semaphore(EMBEDDING_MAX_CONCURRENCY)
                    if EMBEDDING_MAX_CONCURRENCY > 0
                    else None
                )

                async def _run_batch(batch):
                    if semaphore is None:
                        return await loop.run_in_executor(
                            None,
                            lambda: func(
                                batch, prefix=prefix, user=user, chat_id=chat_id
                            ),
                        )
                    async with semaphore:
                        return await loop.run_in_executor(
                            None,
                            lambda: func(
                                batch, prefix=prefix, user=user, chat_id=chat_id
                            ),
                        )

                # Gather all results (동시성은 semaphore 가 제한)
                results = await asyncio.gather(*[_run_batch(b) for b in batches])

                # Flatten results
                embeddings = []
                for result in results:
                    embeddings.extend(result)
                return embeddings
            else:
                return func(query, prefix, user, chat_id)

        async def wrapper(query, prefix=None, user=None, chat_id=None):
            return await generate_multiple(query, prefix, user, chat_id, func)

        return wrapper
    else:
        raise ValueError(f"Unknown embedding engine: {embedding_engine}")


async def get_sources_from_files(
    request,
    files,
    queries,
    embedding_function,
    k,
    full_context=False,
):
    log.debug(f"files: {files} {queries} {embedding_function} {full_context}")

    extracted_collections = []
    relevant_contexts = []

    for file in files:
        context = None
        if file.get("docs"):
            # BYPASS_WEB_SEARCH_EMBEDDING_AND_RETRIEVAL
            context = {
                "documents": [[doc.get("content") for doc in file.get("docs")]],
                "metadatas": [[doc.get("metadata") for doc in file.get("docs")]],
            }
        elif file.get("context") == "full":
            # Manual Full Mode Toggle
            context = {
                "documents": [[file.get("file").get("data", {}).get("content")]],
                "metadatas": [[{"file_id": file.get("id"), "name": file.get("name")}]],
            }
        elif (
            file.get("type") != "web_search"
            and request.app.state.config.BYPASS_EMBEDDING_AND_RETRIEVAL
        ):
            # BYPASS_EMBEDDING_AND_RETRIEVAL
            if file.get("type") == "collection":
                file_ids = file.get("data", {}).get("file_ids", [])

                documents = []
                metadatas = []
                for file_id in file_ids:
                    file_object = Files.get_file_by_id(file_id)

                    if file_object:
                        documents.append(file_object.data.get("content", ""))
                        metadatas.append(
                            {
                                "file_id": file_id,
                                "name": file_object.filename,
                                "source": file_object.filename,
                            }
                        )

                context = {
                    "documents": [documents],
                    "metadatas": [metadatas],
                }

            elif file.get("id"):
                file_object = Files.get_file_by_id(file.get("id"))
                if file_object:
                    context = {
                        "documents": [[file_object.data.get("content", "")]],
                        "metadatas": [
                            [
                                {
                                    "file_id": file.get("id"),
                                    "name": file_object.filename,
                                    "source": file_object.filename,
                                }
                            ]
                        ],
                    }
            elif file.get("file").get("data"):
                context = {
                    "documents": [[file.get("file").get("data", {}).get("content")]],
                    "metadatas": [
                        [file.get("file").get("data", {}).get("metadata", {})]
                    ],
                }
        else:
            collection_names = []
            if file.get("type") == "collection":
                if file.get("legacy"):
                    collection_names = file.get("collection_names", [])
                elif file.get("collection_name"):
                    collection_names.append(file["collection_name"])
                elif file.get("id"):
                    collection_names.append(file["id"])
            elif file.get("collection_name"):
                collection_names.append(file["collection_name"])
            elif file.get("id"):
                if file.get("legacy"):
                    collection_names.append(f"{file['id']}")
                else:
                    collection_names.append(f"file-{file['id']}")

            collection_names = set(collection_names).difference(extracted_collections)
            if not collection_names:
                log.debug(f"skipping {file} as it has already been extracted")
                continue

            if full_context:
                try:
                    context = get_all_items_from_collections(collection_names)
                except Exception as e:
                    log.exception(e)

            else:
                try:
                    context = None
                    if file.get("type") == "text":
                        context = file["content"]
                    else:
                        context = await query_collection(
                            collection_names=collection_names,
                            queries=queries,
                            embedding_function=embedding_function,
                            k=k,
                        )
                except Exception as e:
                    log.exception(e)

            extracted_collections.extend(collection_names)

        if context:
            if "data" in file:
                del file["data"]

            relevant_contexts.append({**context, "file": file})

    sources = []
    for context in relevant_contexts:
        try:
            if "documents" in context:
                if "metadatas" in context:
                    source = {
                        "source": context["file"],
                        "document": context["documents"][0],
                        "metadata": context["metadatas"][0],
                    }
                    if "distances" in context and context["distances"]:
                        source["distances"] = context["distances"][0]

                    sources.append(source)
        except Exception as e:
            log.exception(e)

    return sources


def get_model_path(model: str, update_model: bool = False):
    # Construct huggingface_hub kwargs with local_files_only to return the snapshot path
    cache_dir = os.getenv("SENTENCE_TRANSFORMERS_HOME")

    local_files_only = not update_model

    if OFFLINE_MODE:
        local_files_only = True

    snapshot_kwargs = {
        "cache_dir": cache_dir,
        "local_files_only": local_files_only,
    }

    log.debug(f"model: {model}")
    log.debug(f"snapshot_kwargs: {snapshot_kwargs}")

    # Inspiration from upstream sentence_transformers
    if (
        os.path.exists(model)
        or ("\\" in model or model.count("/") > 1)
        and local_files_only
    ):
        # If fully qualified path exists, return input, else set repo_id
        return model
    elif "/" not in model:
        # Set valid repo_id for model short-name
        model = "sentence-transformers" + "/" + model

    snapshot_kwargs["repo_id"] = model

    # Attempt to query the huggingface_hub library to determine the local path and/or to update
    try:
        model_repo_path = snapshot_download(**snapshot_kwargs)
        log.debug(f"model_repo_path: {model_repo_path}")
        return model_repo_path
    except Exception as e:
        log.exception(f"Cannot determine model snapshot path: {e}")
        return model


def generate_openai_batch_embeddings(
    model: str,
    texts: list[str],
    url: str = "https://api.openai.com/v1",
    key: str = "",
    prefix: str = None,
    user: UserModel = None,
    azure_api_version=None,
    chat_id: str = None,
    trace_context=None,
) -> Optional[list[list[float]]]:
    """Generate batch embeddings using OpenAI/Azure OpenAI API with usage tracking and optional tracing."""
    from open_webui.models.message_trace import RunType

    # Setup tracing context manager if available
    ctx_manager = None
    if trace_context and hasattr(trace_context, "enabled") and trace_context.enabled:
        ctx_manager = trace_context.start_run(
            run_type=RunType.EMBEDDING.value,
            name="openai_batch_embedding",
            inputs={"text_count": len(texts), "model": model},
            model_id=model,
            push_stack=False,  # leaf 노드 — 동시 실행 시 _run_stack 오염 방지
        )

    def _do_embedding():
        log.debug(
            f"generate_openai_batch_embeddings:model {model} batch size: {len(texts)}"
        )
        json_data = {"input": texts, "model": model}
        if isinstance(RAG_EMBEDDING_PREFIX_FIELD_NAME, str) and isinstance(prefix, str):
            json_data[RAG_EMBEDDING_PREFIX_FIELD_NAME] = prefix

        base_url = url.rstrip("/")
        if azure_api_version:
            request_url = f"{base_url}/openai/deployments/{model}/embeddings?api-version={azure_api_version}"
        else:
            request_url = f"{base_url}/embeddings"

        r = post_embedding_request(
            request_url,
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {key}",
                **(
                    {
                        "X-OpenWebUI-User-Name": user.name,
                        "X-OpenWebUI-User-Id": user.id,
                        "X-OpenWebUI-User-Email": user.email,
                        "X-OpenWebUI-User-Role": user.role,
                    }
                    if ENABLE_FORWARD_USER_INFO_HEADERS and user
                    else {}
                ),
            },
            json_data=json_data,
            label="Embedding API error",
        )
        data = r.json()

        # Usage 기록
        usage_data = data.get("usage", {})
        if user and "usage" in data:
            try:
                Usages.insert_new_usage(
                    user_id=user.id,
                    chat_id=chat_id,
                    agent_id=None,
                    model_id=model,
                    message_id=f"embedding:{len(texts)}",  # 임베딩 배치 크기 표시
                    message_type=UsageMessageType.EMBEDDING,
                    total_tokens=usage_data.get("total_tokens", 0),
                    usage=usage_data,
                )
            except Exception as e:
                log.error(f"Failed to insert embedding usage: {e}")

        if "data" in data:
            return [elem["embedding"] for elem in data["data"]], usage_data
        else:
            raise Exception("Something went wrong :/")

    try:
        if ctx_manager:
            with ctx_manager as run:
                embeddings, usage_data = _do_embedding()
                if run:
                    run.set_outputs({"embedding_count": len(embeddings)})
                    run.set_token_usage(
                        {
                            "prompt_tokens": usage_data.get("prompt_tokens", 0),
                            "total_tokens": usage_data.get("total_tokens", 0),
                        }
                    )
                return embeddings
        else:
            embeddings, _ = _do_embedding()
            return embeddings
    except Exception as e:
        log.exception(f"Error generating openai batch embeddings: {e}")
        return None


def generate_ollama_batch_embeddings(
    model: str,
    texts: list[str],
    url: str,
    key: str = "",
    prefix: str = None,
    user: UserModel = None,
    chat_id: str = None,
    trace_context=None,
) -> Optional[list[list[float]]]:
    """Generate batch embeddings using Ollama API with usage tracking and optional tracing."""
    from open_webui.models.message_trace import RunType

    # Setup tracing context manager if available
    ctx_manager = None
    if trace_context and hasattr(trace_context, "enabled") and trace_context.enabled:
        ctx_manager = trace_context.start_run(
            run_type=RunType.EMBEDDING.value,
            name="ollama_batch_embedding",
            inputs={"text_count": len(texts), "model": model},
            model_id=model,
            push_stack=False,  # leaf 노드 — 동시 실행 시 _run_stack 오염 방지
        )

    def _do_embedding():
        log.debug(
            f"generate_ollama_batch_embeddings:model {model} batch size: {len(texts)}"
        )
        json_data = {"input": texts, "model": model}
        if isinstance(RAG_EMBEDDING_PREFIX_FIELD_NAME, str) and isinstance(prefix, str):
            json_data[RAG_EMBEDDING_PREFIX_FIELD_NAME] = prefix

        r = post_embedding_request(
            f"{url.rstrip('/')}/api/embed",
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {key}",
                **(
                    {
                        "X-OpenWebUI-User-Name": user.name,
                        "X-OpenWebUI-User-Id": user.id,
                        "X-OpenWebUI-User-Email": user.email,
                        "X-OpenWebUI-User-Role": user.role,
                    }
                    if ENABLE_FORWARD_USER_INFO_HEADERS
                    else {}
                ),
            },
            json_data=json_data,
            label="Ollama embedding API error",
        )
        data = r.json()

        # Usage 기록 (Ollama는 prompt_eval_count를 토큰 수로 사용)
        prompt_eval_count = data.get("prompt_eval_count", 0)
        usage_data = {
            "prompt_tokens": prompt_eval_count,
            "total_tokens": prompt_eval_count,
            "total_duration": data.get("total_duration"),
        }

        if user:
            try:
                Usages.insert_new_usage(
                    user_id=user.id,
                    chat_id=chat_id,
                    agent_id=None,
                    model_id=model,
                    message_id=f"embedding:{len(texts)}",
                    message_type=UsageMessageType.EMBEDDING,
                    total_tokens=prompt_eval_count,
                    usage=usage_data,
                )
            except Exception as e:
                log.error(f"Failed to insert ollama embedding usage: {e}")

        if "embeddings" in data:
            return data["embeddings"], usage_data
        else:
            raise Exception("Something went wrong :/")

    try:
        if ctx_manager:
            with ctx_manager as run:
                embeddings, usage_data = _do_embedding()
                if run:
                    run.set_outputs({"embedding_count": len(embeddings)})
                    run.set_token_usage(
                        {
                            "prompt_tokens": usage_data.get("prompt_tokens", 0),
                            "total_tokens": usage_data.get("total_tokens", 0),
                        }
                    )
                return embeddings
        else:
            embeddings, _ = _do_embedding()
            return embeddings
    except Exception as e:
        log.exception(f"Error generating ollama batch embeddings: {e}")
        return None


def generate_gemini_batch_embeddings(
    model: str, texts: list[str], api_key: str
) -> list[list[float]]:
    """Generate embeddings using Gemini API (google-generativeai SDK)."""
    import google.generativeai as genai

    genai.configure(api_key=api_key)

    @embedding_retry
    def _embed():
        return genai.embed_content(model=model, content=texts)

    result = _embed()
    return result["embedding"]


def generate_vertex_ai_batch_embeddings(
    model: str,
    texts: list[str],
    project_id: str,
    location: str,
    service_account_key: str,
) -> list[list[float]]:
    """
    Generate embeddings using Vertex AI SDK.

    인증:
    - service_account_key 제공 시 → from_service_account_info() 사용
    - 미제공 시 → Application Default Credentials (ADC) 사용
    """
    import vertexai
    from vertexai.language_models import TextEmbeddingModel

    if service_account_key:
        import json as json_module

        from google.oauth2 import service_account

        key_info = json_module.loads(service_account_key)
        resolved_project_id = project_id or key_info.get("project_id", "")
        credentials = service_account.Credentials.from_service_account_info(
            key_info,
            scopes=["https://www.googleapis.com/auth/cloud-platform"],
        )
        vertexai.init(
            project=resolved_project_id, location=location, credentials=credentials
        )
    else:
        log.info("Using Application Default Credentials for Vertex AI embeddings")
        vertexai.init(project=project_id or None, location=location)
    embedding_model = TextEmbeddingModel.from_pretrained(model)

    @embedding_retry
    def _embed():
        return embedding_model.get_embeddings(texts)

    embeddings_response = _embed()
    return [e.values for e in embeddings_response]


def generate_embeddings(
    engine: str,
    model: str,
    text: Union[str, list[str]],
    prefix: Union[str, None] = None,
    **kwargs,
):
    url = kwargs.get("url", "")
    key = kwargs.get("key", "")
    user = kwargs.get("user")
    chat_id = kwargs.get("chat_id")
    azure_api_version = kwargs.get("azure_api_version", None)
    trace_context = kwargs.get("trace_context", None)

    if prefix is not None and RAG_EMBEDDING_PREFIX_FIELD_NAME is None:
        if isinstance(text, list):
            text = [f"{prefix}{text_element}" for text_element in text]
        else:
            text = f"{prefix}{text}"

    if engine == "ollama":
        if isinstance(text, list):
            embeddings = generate_ollama_batch_embeddings(
                **{
                    "model": model,
                    "texts": text,
                    "url": url,
                    "key": key,
                    "prefix": prefix,
                    "user": user,
                    "chat_id": chat_id,
                    "trace_context": trace_context,
                }
            )
        else:
            embeddings = generate_ollama_batch_embeddings(
                **{
                    "model": model,
                    "texts": [text],
                    "url": url,
                    "key": key,
                    "prefix": prefix,
                    "user": user,
                    "chat_id": chat_id,
                    "trace_context": trace_context,
                }
            )
        if embeddings is None:
            raise ValueError(
                f"Embedding generation failed for engine '{engine}', model '{model}'"
            )
        return embeddings[0] if isinstance(text, str) else embeddings
    elif engine == "openai":
        if isinstance(text, list):
            embeddings = generate_openai_batch_embeddings(
                model,
                text,
                url,
                key,
                prefix,
                user,
                chat_id=chat_id,
                trace_context=trace_context,
            )
        else:
            embeddings = generate_openai_batch_embeddings(
                model,
                [text],
                url,
                key,
                prefix,
                user,
                chat_id=chat_id,
                trace_context=trace_context,
            )
        if embeddings is None:
            raise ValueError(
                f"Embedding generation failed for engine '{engine}', model '{model}'"
            )
        return embeddings[0] if isinstance(text, str) else embeddings
    elif engine == "azure_openai":
        if isinstance(text, list):
            embeddings = generate_openai_batch_embeddings(
                model,
                text,
                url,
                key,
                prefix,
                user,
                azure_api_version,
                chat_id=chat_id,
                trace_context=trace_context,
            )
        else:
            embeddings = generate_openai_batch_embeddings(
                model,
                [text],
                url,
                key,
                prefix,
                user,
                azure_api_version,
                chat_id=chat_id,
                trace_context=trace_context,
            )
        if embeddings is None:
            raise ValueError(
                f"Embedding generation failed for engine '{engine}', model '{model}'"
            )
        return embeddings[0] if isinstance(text, str) else embeddings
    elif engine == "gemini":
        texts = text if isinstance(text, list) else [text]
        embeddings = generate_gemini_batch_embeddings(model, texts, key)
        if embeddings is None:
            raise ValueError(
                f"Embedding generation failed for engine '{engine}', model '{model}'"
            )
        return embeddings[0] if isinstance(text, str) else embeddings
    elif engine == "vertex_ai":
        texts = text if isinstance(text, list) else [text]
        embeddings = generate_vertex_ai_batch_embeddings(
            model,
            texts,
            kwargs.get("vertex_ai_project_id", ""),
            kwargs.get("vertex_ai_location", "us-central1"),
            kwargs.get("vertex_ai_service_account_key", ""),
        )
        if embeddings is None:
            raise ValueError(
                f"Embedding generation failed for engine '{engine}', model '{model}'"
            )
        return embeddings[0] if isinstance(text, str) else embeddings
