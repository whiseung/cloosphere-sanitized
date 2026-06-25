---
paths:
  - "backend/extension_modules/utils/**/*.py"
---

# LLM 유틸리티 사용 규칙

## LLMConfig 데이터클래스
```python
@dataclass
class LLMConfig:
    model_id: str
    api_key: str
    base_url: str
    provider_type: str  # "azure-openai", "vertex-gemini", "vertex-ai", "ollama", default
    azure_endpoint: Optional[str] = None
    azure_deployment: Optional[str] = None
    azure_api_version: Optional[str] = None
    api_config: Optional[Dict[str, Any]] = None  # 프로바이더별 추가 설정
```

## create_llm(config, *, streaming, model_kwargs) → LangChain Chat Model
```python
# 5종 프로바이더 지원 + streaming, model_kwargs
if provider_type == "azure-openai":
    return AzureChatOpenAI(deployment_name, endpoint, api_key, api_version, streaming, model_kwargs)
elif provider_type == "vertex-gemini":
    return ChatGoogleGenerativeAI(model, credentials, streaming, model_kwargs)
elif provider_type == "vertex-ai":
    return ChatVertexAI(model, project, location, credentials, streaming, model_kwargs)
elif provider_type == "ollama":
    return ChatOllama(model, base_url, streaming)
else:
    return ChatOpenAI(model, api_key, base_url, streaming, model_kwargs)
```

## get_model_config_from_app(app, model_id) → LLMConfig
```python
# FastAPI app에서 모델 설정 추출
model_config = get_model_config_from_app(request.app, model_id)
llm = create_llm(model_config)
response = await llm.ainvoke([HumanMessage(content=prompt)])
```

## generate_text(config, prompt, system_prompt) → str
- 간단한 텍스트 생성 래퍼
- 내부적으로 create_llm() 사용

## 사용 패턴 (react_base.py, schema_extractor.py 등에서)
```python
from extension_modules.utils.llm import get_model_config_from_app, create_llm

model_config = get_model_config_from_app(request.app, model_id)
llm = create_llm(model_config)
response = await llm.ainvoke([HumanMessage(content=prompt)])

# 스트리밍 + model_kwargs 사용 (react_base.py 등)
llm = create_llm(config, streaming=True, model_kwargs={"temperature": 0.7})
```

## 참조 파일
- `utils/llm.py`: LLMConfig, create_llm, get_model_config_from_app, generate_text
- `react/react_base.py`: `_create_llm`이 `create_llm`에 위임
