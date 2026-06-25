from pydantic import BaseModel


class SearchDocon(BaseModel):
    id: str
    title: str
    content: str
    url: str
    source: str
    source_url: str
    source_title: str
    source_content: str
    source_url: str
    source_title: str
    source_content: str
