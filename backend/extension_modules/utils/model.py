import os

AZURE_OPENAI_ENDPOINT = os.getenv("AZURE_OPENAI_ENDPOINT")
AZURE_OPENAI_DEPLOYMENT = os.getenv("AZURE_OPENAI_DEPLOYMENT")
AZURE_OPENAI_API_VERSION = os.getenv("AZURE_OPENAI_API_VERSION")
AZURE_OPENAI_API_KEY = os.getenv("AZURE_OPENAI_API_KEY")


def mk_model():
    print("[Azure MCP Agent Pipe] _mk_model called")
    try:
        from langchain_openai import AzureChatOpenAI
    except Exception as e:
        raise RuntimeError(
            f"[deps] langchain-openai 미설치: pip install langchain-openai ({e})"
        )

    if not AZURE_OPENAI_API_KEY:
        raise RuntimeError("AZURE_OPENAI_API_KEY 미설정")

    model = AzureChatOpenAI(
        azure_endpoint=AZURE_OPENAI_ENDPOINT,
        azure_deployment=AZURE_OPENAI_DEPLOYMENT,
        api_version=AZURE_OPENAI_API_VERSION,
        api_key=AZURE_OPENAI_API_KEY,
    )
    print("[Azure MCP Agent Pipe] _mk_model ok")
    return model
