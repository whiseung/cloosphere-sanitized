#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
피난계획 적정성 검토 시스템
- 사용자 쿼리 분석
- 법률 인덱스(checklist-extended-index-v1) 검색
- 도면 인덱스(drawing-index-v1) 검색
- 방화구획도 크롭
- 최종 답변 생성 및 출력
"""

import asyncio
import os
from datetime import datetime
from typing import Any, Dict, List, Optional

import aiohttp
import fitz  # PyMuPDF
import requests
from azure.storage.blob import BlobServiceClient
from dotenv import load_dotenv

# 환경변수 로드
load_dotenv()


class EvacuationPlanAnalyzer:
    """피난계획 적정성 검토 분석기"""

    def __init__(self, valves):
        """분석기 초기화"""
        print("=== 피난계획 적정성 검토 시스템 초기화 ===")

        # Azure OpenAI 설정
        self.aoai_endpoint = valves.AZURE_OPENAI_ENDPOINT
        self.aoai_key = valves.AZURE_OPENAI_API_KEY
        self.aoai_api_version = valves.AZURE_OPENAI_API_VERSION
        self.deployment_name = valves.AZURE_OPENAI_DEPLOYMENT

        # Azure AI Search 설정
        self.search_endpoint = valves.AZURE_SEARCH_ENDPOINT
        self.search_key = valves.AZURE_SEARCH_API_KEY
        self.search_api_version = valves.AZURE_SEARCH_API_VERSION

        self.embedding_endpoint = valves.AZURE_OPENAI_ENDPOINT
        self.embedding_key = valves.AZURE_OPENAI_API_KEY
        self.embedding_deployment = valves.AZURE_OPENAI_DEPLOYMENT_EMBEDDING

        if not all([self.search_endpoint, self.search_key]):
            raise ValueError("Azure AI Search 설정이 필요합니다.")

        self.search_headers = {
            "Content-Type": "application/json",
            "api-key": self.search_key,
        }
        self.search_params = {"api-version": self.search_api_version}

        # Azure Blob Storage 설정
        self.account_name = valves.ACCOUNT_NAME
        self.account_key = valves.ACCOUNT_KEY
        self.container_name_drawing = valves.CONTAINER_NAME_DRAWING

        if all([self.account_name, self.account_key, self.container_name_drawing]):
            connection_string = f"DefaultEndpointsProtocol=https;AccountName={self.account_name};AccountKey={self.account_key};EndpointSuffix=core.windows.net"
            self.blob_service_client = BlobServiceClient.from_connection_string(
                connection_string
            )
            self.blob_available = True
            print("✅ Azure Blob Storage 초기화 완료")
        else:
            print("⚠️ Azure Blob Storage 설정이 없습니다.")
            self.blob_available = False

        # 이미지 출력 디렉토리 설정
        # 우선 환경변수 DRAWING_IMAGE_DIR을 사용하고, 없으면 프로젝트의 backend/data/drawings 사용
        # (기존 tools/drawing/img는 사용하지 않음)
        default_data_dir = os.path.join(
            os.path.dirname(
                os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
            ),
            "data",
            "drawings",
        )
        self.img_dir = os.getenv("DRAWING_IMAGE_DIR", default_data_dir)
        os.makedirs(self.img_dir, exist_ok=True)
        print(f"✅ 이미지 출력 디렉토리: {self.img_dir}")

        print("✓ 피난계획 검토 시스템 초기화 완료")

    def extract_floor_from_query(self, user_query: str) -> str:
        """사용자 쿼리에서 층수 정보 간단 추출"""
        import re

        # 지하4층, 1층, 2층 등 패턴 찾기
        floor_match = re.search(r"(지하\d+층|\d+층)", user_query)
        if floor_match:
            return floor_match.group(1)
        return ""

    def generate_law_search_query(self, user_query: str) -> str:
        """사용자 쿼리에서 직접 법률 검색 쿼리 생성"""
        print("🔍 법률 검색 쿼리 생성 중...")

        law_query_prompt = """사용자 질문을 보고 관련 법률을 검색하기 위한 간단한 쿼리를 생성해주세요.
        
        1. 실 이름은 쿼리에 포함하지 않습니다.
        2. 필요 법률에 맞는 쿼리를 생성해주세요.
        3. 방화구획, 피난 규정을 포함시켜주세요.
        4. 지하에 있는 실일 경우 지하층이라고 표시해주세요.

        예시 : 지하층 방화구획 및 피난 규정

쿼리만 출력하세요."""

        messages = [
            {"role": "system", "content": law_query_prompt},
            {"role": "user", "content": user_query},
        ]

        content = self._call_llm(messages)
        if not content:
            # LLM 실패시 기본 쿼리
            basic_query = "건축법 피난계획"
            print(f"🔄 기본 쿼리 사용: {basic_query}")
            return basic_query

        law_query = content.strip()
        print(f"✅ 법률 검색 쿼리: {law_query}")
        return law_query

    def get_embedding_vector(self, text: str) -> List[float]:
        """텍스트의 임베딩 벡터를 생성합니다."""
        try:
            url = f"{self.embedding_endpoint}/openai/deployments/{self.embedding_deployment}/embeddings"
            headers = {
                "api-key": self.embedding_key,
                "Content-Type": "application/json",
            }
            params = {"api-version": self.aoai_api_version}
            data = {"input": text}

            response = requests.post(url, headers=headers, params=params, json=data)
            response.raise_for_status()

            return response.json()["data"][0]["embedding"]
        except Exception as e:
            raise Exception(f"❌ 임베딩 생성 실패: {e}")
            return []

    async def search_law_index(self, query: str) -> List[Dict[str, Any]]:
        """법률 인덱스 검색"""
        print(f"🔍 법률 인덱스 검색: {query}")

        if not query or not query.strip():
            print("❌ 빈 쿼리로 인한 검색 건너뜀")
            return []

        # 임베딩 벡터 생성
        embedding_vector = self.get_embedding_vector(query)
        if not embedding_vector:
            raise Exception("❌ 임베딩 벡터 생성 실패")
            return []

        # 검색 쿼리 구성
        query_payloads = {
            "count": True,
            "top": 10,
            "search": query,
            "queryType": "full",
            "searchFields": "content",
            "select": "content",
            "vectorQueries": [
                {
                    "k": 10,
                    "fields": "content_vector",
                    "kind": "vector",
                    "exhaustive": True,
                    "vector": embedding_vector,
                }
            ],
        }

        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    f"{self.search_endpoint}/indexes/checklist-extended-index-v1/docs/search",
                    json=query_payloads,
                    headers=self.search_headers,
                    params=self.search_params,
                ) as response:
                    response.raise_for_status()
                    data = await response.json()
                    results = data.get("value", [])

                    print(f"✅ 법률 검색 결과: {len(results)}건")
                    return results

        except Exception as e:
            raise Exception(f"❌ 법률 검색 실패: {e}")
            return []

    async def search_drawing_index(self, floor: str) -> List[Dict[str, Any]]:
        """도면 인덱스에서 해당 층 데이터 검색"""
        print(f"🔍 도면 인덱스 검색 - 층수: {floor}")

        # 실내재료마감표 검색 (필터 조건 단순화)
        filter_condition = "search.ismatch('실내재료마감표', 'drawing_name')"

        query_payloads = {
            "count": True,
            "top": 50,
            "search": floor,  # 층수를 검색어로 사용
            "queryType": "simple",
            "filter": filter_condition,
            "select": "drawing_name, area, content, blob_path, page_num",
        }

        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    f"{self.search_endpoint}/indexes/drawing-index-v1/docs/search",
                    json=query_payloads,
                    headers=self.search_headers,
                    params=self.search_params,
                ) as response:
                    response.raise_for_status()
                    data = await response.json()
                    results = data.get("value", [])

                    print(f"✅ 도면 검색 결과: {len(results)}건")
                    return results

        except Exception as e:
            raise Exception(f"❌ 도면 검색 실패: {e}")
            return []

    async def get_fire_compartment_drawing(
        self, floor: str = "지하4층"
    ) -> Dict[str, Any]:
        """방화구획도-1 데이터 검색 및 이미지 크롭"""
        print("🔍 방화구획도-1 검색 중...")

        # 방화구획도-1 검색
        filter_condition = "drawing_name eq '방화구획도-1'"

        query_payloads = {
            "count": True,
            "top": 1,
            "search": "*",
            "queryType": "full",
            "filter": filter_condition,
            "select": "drawing_name, blob_path, page_num",
        }

        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    f"{self.search_endpoint}/indexes/drawing-index-v1/docs/search",
                    json=query_payloads,
                    headers=self.search_headers,
                    params=self.search_params,
                ) as response:
                    response.raise_for_status()
                    data = await response.json()
                    results = data.get("value", [])

                    if not results:
                        print("❌ 방화구획도-1을 찾을 수 없습니다.")
                        return {}

                    result = results[0]
                    blob_path = result.get("blob_path", "")
                    page_num = result.get("page_num", 1)

                    print(f"✅ 방화구획도-1 발견: {blob_path}, 페이지: {page_num}")

                    # 이미지 크롭
                    cropped_image_path = await self._crop_fire_compartment_drawing(
                        blob_path, page_num, floor
                    )

                    return {
                        "drawing_name": result.get("drawing_name", ""),
                        "blob_path": blob_path,
                        "page_num": page_num,
                        "cropped_image_path": cropped_image_path,
                    }

        except Exception as e:
            raise Exception(f"❌ 방화구획도-1 검색 실패: {e}")
            return {}

    def get_pdf_bytes_from_blob(self, blob_url: str) -> Optional[bytes]:
        """Blob URL에서 PDF 바이트를 다운로드합니다."""
        if not self.blob_available:
            print("❌ Blob Storage를 사용할 수 없습니다.")
            return None

        try:
            # URL에서 컨테이너명과 blob명 추출
            # 예: https://ailab01storage01.blob.core.windows.net/drawings/filename.pdf
            parts = blob_url.split("/")
            if len(parts) < 5:
                print(f"❌ 잘못된 blob URL 형식: {blob_url}")
                return None

            container_name = parts[3]  # drawings
            blob_name = "/".join(parts[4:])  # filename.pdf (또는 path/filename.pdf)

            print(f"   컨테이너: {container_name}")
            print(f"   Blob 이름: {blob_name}")

            blob_client = self.blob_service_client.get_blob_client(
                container=container_name, blob=blob_name
            )

            pdf_bytes = blob_client.download_blob().readall()
            print(f"✅ PDF 메모리 로드 완료: {len(pdf_bytes)} bytes")
            return pdf_bytes

        except Exception as e:
            raise Exception(f"❌ PDF 메모리 로드 오류: {e}")
            return None

    async def _crop_fire_compartment_drawing(
        self, blob_path: str, page_num: int, floor: str
    ) -> str:
        """방화구획도를 크롭하여 이미지 디렉토리에 저장"""
        print(f"🖼️ 방화구획도 크롭 중: {blob_path}, 페이지: {page_num}")

        try:
            # Blob에서 PDF 다운로드
            pdf_bytes = self.get_pdf_bytes_from_blob(blob_path)
            if not pdf_bytes:
                return ""

            # PDF 열기
            doc = fitz.open(stream=pdf_bytes, filetype="pdf")

            if page_num > len(doc):
                print(
                    f"❌ 페이지 번호 {page_num}이 PDF 페이지 수 {len(doc)}를 초과합니다."
                )
                return ""

            page = doc[page_num - 1]  # 0부터 시작

            # 키워드 검색 (사용자 쿼리에서 추출한 층수 사용)
            keyword = floor if floor else "지하4층"  # 기본값으로 지하4층 사용
            text_instances = page.search_for(keyword)

            if text_instances:
                print(f"✅ '{keyword}' 키워드 발견")
                rect = text_instances[0]

                # 크롭 영역 정의 (find_and_crop_keyword.py와 동일한 크기)
                crop_size = 350
                crop_rect = fitz.Rect(
                    rect.x0,  # 키워드 x 좌표를 시작점으로
                    rect.y1 - crop_size,  # 키워드 하단에서 위쪽으로 crop_size만큼
                    rect.x0 + crop_size + 50,  # +x 방향으로 crop_size만큼
                    rect.y1,  # 키워드 하단까지
                )

                # 고해상도로 이미지 변환
                mat = fitz.Matrix(2.0, 2.0)  # 2배 확대
                pix = page.get_pixmap(matrix=mat, clip=crop_rect)

                # 저장 경로 생성
                timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                output_path = os.path.join(
                    self.img_dir, f"방화구획도_{floor}_{timestamp}_crop.png"
                )

                # 이미지 저장
                pix.save(output_path)
                print(f"✅ 크롭된 이미지 저장: {output_path}")

                doc.close()
                return output_path
            else:
                print(f"❌ '{keyword}' 키워드를 찾을 수 없습니다.")
                doc.close()
                return ""

        except Exception as e:
            raise Exception(f"❌ 이미지 크롭 실패: {e}")
            return ""

    async def get_floor_plan_image(
        self, floor: str = "", user_query: str = "", drawing_content: List = None
    ) -> Dict[str, Any]:
        """평면도에서 해당 층의 페이지를 PNG 이미지로 변환"""
        print(f"🖼️ 평면도 이미지 생성 중 - 층수: {floor}")

        if not floor:
            print("❌ 층수 정보가 없습니다.")
            return {}

        # 평면도 검색 (drawing_name에 '평면도'가 포함되고 area에 해당 층이 완전 일치)
        filter_condition = (
            f"search.ismatch('평면도', 'drawing_name') and area/any(a: a eq '{floor}')"
        )

        query_payloads = {
            "count": True,
            "top": 1,
            "search": "*",
            "queryType": "full",
            "filter": filter_condition,
            "select": "drawing_name, area, blob_path, page_num",
        }

        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    f"{self.search_endpoint}/indexes/drawing-index-v1/docs/search",
                    json=query_payloads,
                    headers=self.search_headers,
                    params=self.search_params,
                ) as response:
                    response.raise_for_status()
                    data = await response.json()
                    results = data.get("value", [])

                    if not results:
                        print(f"❌ {floor} 평면도를 찾을 수 없습니다.")
                        return {}

                    result = results[0]
                    blob_path = result.get("blob_path", "")
                    page_num = result.get("page_num", 1)
                    drawing_name = result.get("drawing_name", "")

                    print(f"✅ 평면도 발견: {drawing_name}, 페이지: {page_num}")

                    # 페이지를 PNG 이미지로 변환 (키워드 박스 표시 포함)
                    image_path = await self._convert_page_to_png_with_annotations(
                        blob_path, page_num, floor, user_query, drawing_content
                    )

                    return {
                        "drawing_name": drawing_name,
                        "blob_path": blob_path,
                        "page_num": page_num,
                        "area": result.get("area", []),
                        "image_path": image_path,
                    }

        except Exception as e:
            raise Exception(f"❌ 평면도 검색 실패: {e}")
            return {}

    async def _convert_page_to_png_with_annotations(
        self,
        blob_path: str,
        page_num: int,
        floor: str,
        user_query: str,
        drawing_content: List,
    ) -> str:
        """PDF의 특정 페이지를 PNG로 변환하고 키워드별 박스 표시하여 이미지 디렉토리에 저장"""
        print(f"🔄 평면도 페이지 PNG 변환 및 키워드 박스 표시 중: 페이지 {page_num}")
        print(f"   📝 전달받은 user_query: {user_query}")
        print(
            f"   📝 전달받은 drawing_content 개수: {len(drawing_content) if drawing_content else 0}"
        )

        try:
            # Blob에서 PDF 다운로드
            pdf_bytes = self.get_pdf_bytes_from_blob(blob_path)
            if not pdf_bytes:
                return ""

            # PDF 열기
            doc = fitz.open(stream=pdf_bytes, filetype="pdf")

            if page_num > len(doc):
                print(
                    f"❌ 페이지 번호 {page_num}이 PDF 페이지 수 {len(doc)}를 초과합니다."
                )
                return ""

            page = doc[page_num - 1]  # 0부터 시작

            # 페이지를 고해상도 이미지로 변환
            mat = fitz.Matrix(2.0, 2.0)  # 2배 확대
            pix = page.get_pixmap(matrix=mat)

            # PIL Image로 변환
            import io

            from PIL import Image, ImageDraw

            img_data = pix.tobytes("png")
            img = Image.open(io.BytesIO(img_data))
            draw = ImageDraw.Draw(img)

            # 색깔 정의
            colors = {
                "fire_shutter": "red",  # 방화셔터 - 빨간색
                "staircase": "blue",  # 계단실 - 파란색
                "target_room": "green",  # 분석 대상 실 - 초록색
            }

            # 1. 방화셔터 키워드 검색 및 박스 표시
            fire_shutter_instances = page.search_for("방화셔터")
            for rect in fire_shutter_instances:
                # 좌표를 2배 확대에 맞게 조정
                x0, y0, x1, y1 = rect.x0 * 2, rect.y0 * 2, rect.x1 * 2, rect.y1 * 2
                draw.rectangle(
                    [x0 - 5, y0 - 5, x1 + 5, y1 + 5],
                    outline=colors["fire_shutter"],
                    width=3,
                )
            print(f"✅ 방화셔터 {len(fire_shutter_instances)}개 박스 표시 완료")

            # 2. 계단실 키워드 검색 및 박스 표시
            staircase_instances = page.search_for("계단실")
            for rect in staircase_instances:
                x0, y0, x1, y1 = rect.x0 * 2, rect.y0 * 2, rect.x1 * 2, rect.y1 * 2
                draw.rectangle(
                    [x0 - 5, y0 - 5, x1 + 5, y1 + 5],
                    outline=colors["staircase"],
                    width=3,
                )
            print(f"✅ 계단실 {len(staircase_instances)}개 박스 표시 완료")

            # 3. 사용자 질문에서 실명을 정규식으로 추출하고 LLM으로 실제 실명 찾기
            if drawing_content and user_query:
                extracted_room = self._extract_room_name_from_query(user_query)
                print(f"   🔍 추출된 실명: '{extracted_room}'")
                if extracted_room != "해당 실":
                    actual_room_names = await self._find_all_actual_room_names(
                        extracted_room, drawing_content
                    )
                else:
                    actual_room_names = []
                total_instances = 0
                for actual_room_name in actual_room_names:
                    if actual_room_name and actual_room_name != "해당 실":
                        # 실제 실명으로 검색
                        room_instances = page.search_for(actual_room_name)
                        for rect in room_instances:
                            x0, y0, x1, y1 = (
                                rect.x0 * 2,
                                rect.y0 * 2,
                                rect.x1 * 2,
                                rect.y1 * 2,
                            )
                            draw.rectangle(
                                [x0 - 5, y0 - 5, x1 + 5, y1 + 5],
                                outline=colors["target_room"],
                                width=3,
                            )
                        total_instances += len(room_instances)
                        if room_instances:
                            print(
                                f"✅ 분석 대상 실 '{actual_room_name}' {len(room_instances)}개 박스 표시"
                            )

                if total_instances > 0:
                    print(f"✅ 총 {total_instances}개 분석 대상 실 박스 표시 완료")

            # 저장 경로 생성
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            output_path = os.path.join(
                self.img_dir, f"평면도_{floor}_annotated_{timestamp}.png"
            )

            # 주석이 추가된 이미지 저장
            img.save(output_path)
            print(f"✅ 주석 표시된 평면도 저장: {output_path}")

            doc.close()
            return output_path

        except Exception as e:
            raise Exception(f"❌ 평면도 주석 표시 실패: {e}")
            return ""

    async def _find_all_actual_room_names(
        self, room_name: str, drawing_content: List
    ) -> List[str]:
        """추출된 실명을 바탕으로 실내재료마감표에서 모든 관련 실명 찾기"""
        if not drawing_content or not room_name:
            return []

        # 실내재료마감표 내용에서 실명 추출
        content_text = ""
        for drawing in drawing_content:
            content_text += drawing.get("content", "") + "\n"

        # LLM을 사용해서 추출된 실명과 매칭되는 모든 실명 찾기
        find_room_prompt = f"""실내재료마감표 데이터에서 '{room_name}'과 관련된 모든 실제 실명을 찾아주세요.

찾는 실명: {room_name}

실내재료마감표 데이터:
{content_text}

예시:
- 찾는 실명: "전기실" → 실제 실명들: ["전기실(판매용)", "전기실(업무용)"]
- 찾는 실명: "UPS실" → 실제 실명들: ["UPS실"]
- 찾는 실명: "소화가스실" → 실제 실명들: ["소화가스실-1", "소화가스실-2", "소화가스실-3"]

**중요**: 반드시 순수한 JSON 배열 형태로만 출력하세요. 설명이나 다른 텍스트는 포함하지 마세요.

예시 출력:
["전기실(판매용)", "전기실(업무용)"]

또는

[]

JSON 배열만 출력하세요."""

        messages = [
            {"role": "system", "content": find_room_prompt},
            {
                "role": "user",
                "content": f"'{room_name}'과 관련된 모든 실명을 찾아주세요.",
            },
        ]

        content = self._call_llm(messages)
        if content and content.strip():
            try:
                # JSON 파싱 (더 robust한 처리)
                import json

                content = content.strip()

                # 마크다운 코드 블록 제거
                if content.startswith("```json"):
                    content = content[7:]
                if content.startswith("```"):
                    content = content[3:]
                if content.endswith("```"):
                    content = content[:-3]
                content = content.strip()

                # JSON 배열 부분만 추출 (설명 텍스트 제거)
                import re

                json_match = re.search(r"\[.*?\]", content, re.DOTALL)
                if json_match:
                    json_content = json_match.group(0)
                    actual_names = json.loads(json_content)
                    if isinstance(actual_names, list):
                        print(f"✅ 실명 매칭 완료: '{room_name}' → {actual_names}")
                        return actual_names
                else:
                    print(f"❌ JSON 배열을 찾을 수 없음: {content}")
                    return []

            except json.JSONDecodeError as e:
                raise Exception(f"❌ 실명 매칭 JSON 파싱 실패: {e}")
                print(f"❌ 원본 내용: {content}")
                return []

        return []

    async def collect_all_content(self, user_query: str) -> Dict[str, Any]:
        """모든 컨텐츠를 수집하여 JSON으로 정리"""
        print("🔄 피난계획 검토용 컨텐츠 수집 시작...")

        # 1. 층수 정보 추출
        floor = self.extract_floor_from_query(user_query)

        # 1-2. 실명 정보 추출 (한 번만 실행)
        extracted_room = self._extract_room_name_from_query(user_query)

        # 2. 법률 검색 쿼리 생성
        law_query = self.generate_law_search_query(user_query)

        # 3. 병렬로 모든 데이터 수집
        tasks = []

        # 법률 인덱스 검색
        if law_query:
            tasks.append(self.search_law_index(law_query))
        else:
            tasks.append(asyncio.create_task(self._empty_result()))

        # 도면 인덱스 검색 (해당 층)
        if floor:
            tasks.append(self.search_drawing_index(floor))
        else:
            tasks.append(asyncio.create_task(self._empty_result()))

        # 방화구획도 검색 및 크롭
        tasks.append(self.get_fire_compartment_drawing(floor))

        # 평면도 이미지 생성 (나중에 drawing_content를 받아서 처리)

        # 모든 작업 병렬 실행
        law_results, drawing_results, fire_drawing_info = await asyncio.gather(*tasks)

        # 평면도 이미지 생성 (drawing_results를 사용)
        floor_plan_info = await self.get_floor_plan_image(
            floor, user_query, drawing_results
        )

        # 4. 결과 정리
        collected_content = {
            "timestamp": datetime.now().isoformat(),
            "user_query": user_query,
            "extracted_floor": floor,
            "extracted_room": extracted_room,
            "law_search_query": law_query,
            "law_content": law_results,
            "drawing_content": drawing_results,
            "fire_compartment_drawing": fire_drawing_info,
            "floor_plan_image": floor_plan_info,
            "summary": {
                "law_results_count": len(law_results) if law_results else 0,
                "drawing_results_count": len(drawing_results) if drawing_results else 0,
                "fire_drawing_available": bool(
                    fire_drawing_info.get("cropped_image_path")
                ),
                "floor_plan_available": bool(floor_plan_info.get("image_path")),
            },
        }

        print("✅ 모든 컨텐츠 수집 완료")
        return collected_content

    def encode_image_to_base64(self, image_path: str) -> str:
        """이미지를 base64로 인코딩"""
        try:
            import base64

            with open(image_path, "rb") as image_file:
                return base64.b64encode(image_file.read()).decode("utf-8")
        except Exception as e:
            raise Exception(f"❌ 이미지 인코딩 실패: {e}")
            return ""

    async def generate_final_answer(
        self, user_query: str, collected_content: Dict[str, Any]
    ) -> str:
        """수집된 모든 데이터를 바탕으로 최종 답변 생성"""
        print("🤖 최종 답변 생성 중...")

        # 이미 추출된 실명 사용 (중복 추출 방지)
        room_name = collected_content.get("extracted_room", "해당 실")

        # 답변 생성 프롬프트 구성
        answer_prompt = f"""당신은 건축 법규 및 피난계획 전문가입니다. 
다음 데이터를 종합하여 사용자 질문에 대한 상세한 답변을 생성해주세요.

사용자 질문: {user_query}
분석 대상 실: {room_name}

제공된 데이터:
1. 법률 검색 결과: {len(collected_content.get("law_content", []))}건
2. 실내재료마감표 데이터: {len(collected_content.get("drawing_content", []))}건  
3. 방화구획도 크롭 이미지: {"있음" if collected_content["summary"]["fire_drawing_available"] else "없음"}
4. 평면도 전체 이미지: {"있음" if collected_content["summary"]["floor_plan_available"] else "없음"}

답변 형식:
## 1. 법률 검토 사항
- 관련 법규와 기준을 정리해주세요

## 2. 실내재료 마감 현황
- {room_name}의 바닥, 벽, 천장 마감재료를 표 형식으로 정리해주세요
- 실내재료마감표에서 해당 실 정보를 찾아 정리해주세요
- 실내재료 마감표의 실제 데이터의 실명과 {room_name}이 정확히 일치하지 않을 수 있습니다. 그럴 경우 실내재료 마감표의 실명과 {room_name}과 유사한 실명을 찾아 정리해주세요
 예) 전기실 -> 전기실(판매용), 전기실(업무용)

## 3. 방화구획 현황  
- 크롭된 방화구획도 이미지와 기호를 참고하여 해당 실의 방화구획 상태를 설명해주세요
- 방화구획, 방화문, 피난경로 등을 분석해주세요

## 4. 평면도 분석
- 평면도에서 분석 대상 실의 위치를 파악하고, 주변 피난시설과의 상대적 위치 관계를 분석해주세요
- 계단실의 위치와 해당 실로부터의 방향을 구체적으로 설명해주세요 (예: "북쪽", "동쪽 복도 끝", "왼쪽 오른쪽")
- 방화셔터가 설치된 위치와 해당 실과의 관계를 설명해주세요
- 방화셔터는 평면도에 "방화셔터" 텍스트로 표시되어 있습니다. 해당 텍스트가 없을 시 방화셔터가 있다고 가정하지 마세요
- 해당 실에서 가장 가까운 피난시설까지의 경로와 거리를 구체적으로 분석해주세요

## 5. 종합 검토 결과
- 법규 적합성 여부
- 개선 필요사항
- 최종 결론

**중요한 답변 원칙:**
1. 제공된 데이터에만 기반하여 답변하세요
2. 정보가 없거나 불충분한 경우 "정보 없음" 또는 "데이터 부족으로 판단 불가"라고 명시하세요
3. 추측이나 일반적인 지식으로 빈 공간을 채우지 마세요
4. 각 검토 항목별로 근거 데이터를 명확히 제시하세요

**방화구획 검토 시 중요사항:**
- 방화셔터, 방화문, 방화벽 세가지가 필수로 있어야 하는 것이 아니라 법적 요건에 근거해 세가지 중 필수적인 요소만 있으면 적절한 방화구획으로 판단할 수 있음
- 대신 법적 요건에 필수적이라고 하는 요소가 없다면 적절한 방화구획으로 판단할 수 없음

상세하고 전문적으로 답변해주세요."""

        # 법률 내용 추가
        law_content = ""
        if collected_content.get("law_content"):
            law_content = "\n\n=== 법률 검색 결과 ===\n"
            for i, law in enumerate(collected_content["law_content"], 1):  # 상위 5개만
                law_content += f"{i}. {law.get('content', '')}...\n\n"

        # 실내재료마감표 내용 추가
        drawing_content = ""
        if collected_content.get("drawing_content"):
            drawing_content = "\n\n=== 실내재료마감표 내용 ===\n"
            for drawing in collected_content["drawing_content"]:
                drawing_content += f"도면명: {drawing.get('drawing_name', '')}\n"
                drawing_content += f"내용: {drawing.get('content', '')}...\n\n"

        # 방화구획도 정보 추가
        fire_info = ""
        if collected_content.get("fire_compartment_drawing"):
            fire_info = "\n\n=== 방화구획도 정보 ===\n"
            fire_info += f"도면명: {collected_content['fire_compartment_drawing'].get('drawing_name', '')}\n"
            fire_info += f"페이지: {collected_content['fire_compartment_drawing'].get('page_num', '')}\n"
            fire_info += f"크롭 이미지: {collected_content['fire_compartment_drawing'].get('cropped_image_path', '')}\n"
            fire_info += """※ 방화구획도 기호 해석:
첨부된 기호 이미지를 참조하여 크롭된 방화구획도에서 다음 기호들을 찾아 해당 실의 방화구획 상태를 분석해주세요:
- 방화구획선: 굵은 검은 실선
- 방화셔터: 굵은 점선
- 제연구역선: 굵은 선 사이에 검은 점 조합
- 갑종방화문 or 승강기 방화문: 검은 원형 기호 (●)
- 방화유리문 or 방화자동문: 흰 원형 기호 (○)

기호 이미지와 크롭된 방화구획도를 비교하여 정확한 기호를 식별하고 분석해주세요.\n"""

        # 평면도 정보 추가
        floor_plan_info = ""
        if collected_content.get("floor_plan_image"):
            floor_plan_info = "\n\n=== 평면도 정보 ===\n"
            floor_plan_info += f"도면명: {collected_content['floor_plan_image'].get('drawing_name', '')}\n"
            floor_plan_info += (
                f"페이지: {collected_content['floor_plan_image'].get('page_num', '')}\n"
            )
            floor_plan_info += (
                f"구역: {collected_content['floor_plan_image'].get('area', [])}\n"
            )
            floor_plan_info += f"평면도 이미지: {collected_content['floor_plan_image'].get('image_path', '')}\n"
            floor_plan_info += """※ 평면도 분석 시 주의사항:
첨부된 평면도 이미지에서:
- 빨간색 박스로 표시된 곳: 방화셔터 위치
- 파란색 박스로 표시된 곳: 계단실 위치  
- 초록색 박스로 표시된 곳: 분석 대상 실 위치

**중요**: 답변에서는 색깔로 설명하지 말고 구체적인 위치로 설명하세요.
예시: "전기실 북쪽에 위치한 비상계단", "전기실 동쪽 복도에 있는 방화셔터" 등
이미지에서 각 요소들의 상대적 위치 관계를 직접 확인하여 설명해주세요.\n"""

        full_prompt = (
            answer_prompt + law_content + drawing_content + fire_info + floor_plan_info
        )

        # 이미지들을 base64로 인코딩하여 메시지에 포함
        user_message_content = [
            {
                "type": "text",
                "text": f"위 데이터를 종합하여 '{user_query}'에 대한 상세한 답변을 생성해주세요.",
            }
        ]

        # 기호.png 이미지 추가
        symbol_image_path = os.path.join(os.path.dirname(__file__), "기호.png")
        if os.path.exists(symbol_image_path):
            symbol_base64 = self.encode_image_to_base64(symbol_image_path)
            if symbol_base64:
                user_message_content.append(
                    {
                        "type": "image_url",
                        "image_url": {
                            "url": f"data:image/png;base64,{symbol_base64}",
                            "detail": "high",
                        },
                    }
                )
                print("✅ 방화구획도 기호 이미지 추가됨")

        # 크롭된 방화구획도 이미지 추가
        if collected_content["summary"]["fire_drawing_available"]:
            fire_image_path = collected_content["fire_compartment_drawing"].get(
                "cropped_image_path", ""
            )
            if fire_image_path and os.path.exists(fire_image_path):
                fire_base64 = self.encode_image_to_base64(fire_image_path)
                if fire_base64:
                    user_message_content.append(
                        {
                            "type": "image_url",
                            "image_url": {
                                "url": f"data:image/png;base64,{fire_base64}",
                                "detail": "high",
                            },
                        }
                    )
                    print("✅ 크롭된 방화구획도 이미지 추가됨")

        # 평면도 이미지 추가
        if collected_content["summary"]["floor_plan_available"]:
            floor_image_path = collected_content["floor_plan_image"].get(
                "image_path", ""
            )
            if floor_image_path and os.path.exists(floor_image_path):
                floor_base64 = self.encode_image_to_base64(floor_image_path)
                if floor_base64:
                    user_message_content.append(
                        {
                            "type": "image_url",
                            "image_url": {
                                "url": f"data:image/png;base64,{floor_base64}",
                                "detail": "high",
                            },
                        }
                    )
                    print("✅ 평면도 이미지 추가됨")

        # GPT-4o 비전으로 답변 생성
        messages = [
            {"role": "system", "content": full_prompt},
            {"role": "user", "content": user_message_content},
        ]

        # 답변 생성용 GPT 설정 사용
        answer_url = f"{self.aoai_endpoint}/openai/deployments/{self.deployment_name}/chat/completions"
        answer_headers = {"api-key": self.aoai_key, "Content-Type": "application/json"}
        answer_params = {"api-version": self.aoai_api_version}
        answer_data = {"messages": messages, "temperature": 0.3, "max_tokens": 4000}

        try:
            response = requests.post(
                answer_url,
                headers=answer_headers,
                params=answer_params,
                json=answer_data,
            )
            response.raise_for_status()
            response_data = response.json()

            if "choices" in response_data and len(response_data["choices"]) > 0:
                choice = response_data["choices"][0]
                if "message" in choice and "content" in choice["message"]:
                    final_answer = choice["message"]["content"]
                    print("✅ 최종 답변 생성 완료")
                    return final_answer

        except Exception as e:
            raise Exception(f"❌ 답변 생성 실패: {e}")
            return "답변 생성 중 오류가 발생했습니다."

        return "답변을 생성할 수 없습니다."

    def _extract_room_name_from_query(self, user_query: str) -> str:
        """사용자 쿼리에서 실명 추출"""
        import re

        print(f"🔍 정규식으로 실명 추출 중: {user_query}")

        # UPS실, 전기실, 관리실 등 패턴 찾기
        room_patterns = [
            r"([가-힣]+\s+홀)",  # ~홀 패턴 (승강기 홀 등, 공백 필수)
            r"([가-힣]+홀)",  # ~홀 패턴 (ELEV홀 등, 공백 없음)
            r"([가-힣]+실)",  # ~실 패턴
            r"([가-힣]+룸)",  # ~룸 패턴
        ]

        for pattern in room_patterns:
            match = re.search(pattern, user_query)
            if match:
                extracted_room = match.group(1)
                print(f"✅ 정규식 추출 성공: '{extracted_room}'")
                return extracted_room

        print("❌ 정규식으로 실명을 찾을 수 없음")
        return "해당 실"

    async def _empty_result(self):
        """빈 결과 반환용 헬퍼 함수"""
        return []

    def _call_llm(self, messages: list) -> str:
        """LLM을 호출하여 응답을 받습니다."""
        url = f"{self.aoai_endpoint}/openai/deployments/{self.deployment_name}/chat/completions"
        headers = {"api-key": self.aoai_key, "Content-Type": "application/json"}
        params = {"api-version": self.aoai_api_version}
        data = {"messages": messages, "temperature": 0}

        try:
            response = requests.post(url, headers=headers, params=params, json=data)
            response.raise_for_status()
            response_data = response.json()

            # 응답 구조 확인
            if "choices" in response_data and len(response_data["choices"]) > 0:
                choice = response_data["choices"][0]

                # 컨텐츠 필터링 체크
                if choice.get("finish_reason") == "content_filter":
                    print(
                        f"⚠️ 컨텐츠 필터링 발생: {choice.get('content_filter_results', {})}"
                    )
                    print("🔄 더 중립적인 표현으로 재시도합니다.")
                    return ""

                if "message" in choice and "content" in choice["message"]:
                    return choice["message"]["content"]
                else:
                    raise Exception(f"❌ 응답 구조 오류 - choice: {choice}")
                    return ""
            else:
                raise Exception(f"❌ 응답 구조 오류 - response: {response_data}")
                return ""

        except Exception as e:
            raise Exception(f"❌ LLM 호출 실패: {e}")
            return ""

    async def analyze_evacuation_plan(self, user_query: str, send_status):
        """피난계획 적정성 검토 메인 함수"""
        print("=" * 80)
        print("피난계획 적정성 검토 시스템 실행")
        print("=" * 80)
        print(f"📝 분석 쿼리: {user_query}")

        # 1단계: 컨텐츠 수집
        print("\n🔄 1단계: 데이터 수집 중...")
        await send_status("1단계: 데이터 수집 중...", False)
        collected_content = await self.collect_all_content(user_query)

        # 2단계: 최종 답변 생성
        print("\n🤖 2단계: 최종 답변 생성 중...")
        await send_status("2단계: 최종 답변 생성 중...", False)

        def upload_to_blob(local_path):
            blob_name = os.path.basename(local_path)
            blob_client = self.blob_service_client.get_blob_client(
                container=self.container_name_drawing, blob=blob_name
            )
            with open(local_path, "rb") as data:
                blob_client.upload_blob(data, overwrite=True)
            return blob_client.url

        # 생성된 이미지 파일 정보를 Azure Blob에 업로드한 후, Blob URL을 반환해야 합니다.
        # 예시:
        if collected_content["summary"]["fire_drawing_available"]:
            fire_image = collected_content["fire_compartment_drawing"].get(
                "cropped_image_path", ""
            )
            fire_blob_url = upload_to_blob(fire_image)

        if collected_content["summary"]["floor_plan_available"]:
            floor_image = collected_content["floor_plan_image"].get("image_path", "")
            floor_blob_url = upload_to_blob(floor_image)

        yield f"""## 수집된 데이터

- 법률 검색 결과: {collected_content["summary"]["law_results_count"]}건
- 도면 검색 결과: {collected_content["summary"]["drawing_results_count"]}건
- 방화구획도 크롭: {"성공" if collected_content["summary"]["fire_drawing_available"] else "실패"}
- 평면도 이미지: {"성공" if collected_content["summary"]["floor_plan_available"] else "실패"}

| 방화구획도 | 평면도 |
|---|---|
| ![방화구획도 크롭 이미지]({fire_blob_url}) | ![평면도 주석 이미지]({floor_blob_url}) |

"""

        final_answer = await self.generate_final_answer(user_query, collected_content)
        yield final_answer


# # 사용 예시
# async def main():
#     """메인 실행 함수"""
#     analyzer = EvacuationPlanAnalyzer()

#     # 예시 쿼리
#     test_query = "지하4층 판매시설 승강기 홀 건축법규 기준으로 피난계획의 적정성을 검토하고, 그 검토내용을 '검토항목', '검토내용', '검토결과'가 포함된 표 형식으로 만들어서 보여줘."

#     # 피난계획 분석 실행
#     result = await analyzer.analyze_evacuation_plan(test_query)

#     return result

# if __name__ == "__main__":
#     # 비동기 실행
#     import asyncio
#     asyncio.run(main())
