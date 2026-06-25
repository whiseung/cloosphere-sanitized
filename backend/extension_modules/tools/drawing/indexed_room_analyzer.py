#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
인덱스 기반 실 분석 시스템
- Azure AI Search 인덱스에서 필요한 정보를 검색하여 분석
- 기존 프롬프트와 분석 로직은 그대로 유지
"""

import json
import os
import sys
from typing import Any, Dict, List

import fitz  # PyMuPDF
import requests
from azure.storage.blob import BlobServiceClient
from dotenv import load_dotenv
from langchain_core.output_parsers import PydanticOutputParser
from PIL import Image
from pydantic import BaseModel, Field

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from extension_modules.tools.drawing.room_analysis_prompts import (
    FLOOR_PLAN_ANALYSIS_PROMPT,
    MATERIAL_CODE_ANALYSIS_PROMPT,
    PARTITION_INTEGRATION_PROMPT,
    WALL_GUIDE_ANALYSIS_PROMPT,
    WALL_TABLE_ANALYSIS_PROMPT,
)
from extension_modules.tools.drawing.room_analysis_utils import RoomAnalysisUtils

# 환경변수 로드
load_dotenv()


class WallGuideAnalysisResult(BaseModel):
    wall_type_codes: List[str] = Field(description="벽체 라벨 코드")
    reason: str = Field(description="분석 이유")


class MaterialInfoResult(BaseModel):
    material_code: str = Field(description="실번호")
    ceiling_height: str = Field(description="층고")
    reason: str = Field(description="분석 이유")


class IndexedRoomAnalyzer:
    """인덱스 기반 실 분석기"""

    def __init__(self, valves):
        """분석기 초기화"""
        print("=== 인덱스 기반 실 분석 시스템 초기화 ===")

        # 유틸리티 초기화
        self.utils = RoomAnalysisUtils(valves)

        # Azure AI Search 설정
        self.search_endpoint = valves.AZURE_SEARCH_ENDPOINT
        self.search_key = valves.AZURE_SEARCH_API_KEY
        self.search_api_version = valves.AZURE_SEARCH_API_VERSION

        if not all([self.search_endpoint, self.search_key]):
            raise ValueError("Azure AI Search 설정이 필요합니다.")

        self.search_headers = {
            "Content-Type": "application/json",
            "api-key": self.search_key,
        }
        self.search_params = {"api-version": self.search_api_version}
        self.index_name = "drawing-index-v1"

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
        else:
            print("⚠️ Azure Blob Storage 설정이 없습니다.")
            self.blob_available = False

        print("✓ 모든 서비스 초기화 완료")

    async def analyze_user_query(self, user_query: str) -> Dict[str, Any]:
        """사용자 쿼리를 분석하여 필요한 정보 추출"""
        print(f"🔍 사용자 쿼리 분석 중: {user_query}")

        analysis_prompt = """당신은 건축 도면 분석 전문가입니다. 사용자의 질문을 분석하여 다음 정보를 추출해주세요:

1. 층수 정보 (예: 지하4층, 1층, 2층 등)
2. 분석할 실명 (예: 관리실, 전기실 등)
3. 필요한 문서 유형들

**중요**: 층수는 정확히 추출하세요. "지하4층"과 "4층"은 다릅니다.

JSON 형식으로 응답해주세요:
{
  "floor": "지하4층",
  "room_name": "관리실",
  "required_documents": ["평면도", "벽체 안내도", "건식 벽체 일람표", "실내재료마감표"]
}"""

        messages = [
            {"role": "system", "content": analysis_prompt},
            {"role": "user", "content": f"다음 질문을 분석해주세요: {user_query}"},
        ]

        content = await self.utils.call_llm_4(messages)
        if not content:
            print("❌ 쿼리 분석 실패")
            return {}

        try:
            result = json.loads(content)
            print(f"✅ 쿼리 분석 완료: {result}")
            return result
        except json.JSONDecodeError:
            raise Exception(f"❌ JSON 파싱 오류: {content}")
            return {}

    async def extract_and_match_room_names(
        self, pdf_bytes: bytes, user_room_name: str, target_page_num: int = None
    ) -> str:
        """PDF에서 실명들을 추출하고 사용자 입력과 매칭"""
        print(f"🔍 PDF에서 실명 추출 및 '{user_room_name}' 매칭 중...")

        # PDF에서 텍스트 추출 (특정 페이지 또는 전체)
        doc = fitz.open(stream=pdf_bytes, filetype="pdf")
        all_text = ""
        print(f"   PDF 총 페이지 수: {len(doc)}")

        if target_page_num and target_page_num <= len(doc):
            # 특정 페이지에서만 추출
            page = doc[target_page_num - 1]  # page_num은 1부터 시작
            all_text = page.get_text()
            print(f"   ✅ 페이지 {target_page_num}에서만 텍스트 추출")
        else:
            # 기본적으로는 첫 번째 페이지만 사용
            if len(doc) > 0:
                page = doc[0]
                all_text = page.get_text()
                print("   ⚠️ target_page_num이 없어서 첫 번째 페이지만 사용")
            else:
                print("   ❌ PDF에 페이지가 없습니다")
                return user_room_name
        doc.close()

        print(f"   PDF 전체 텍스트 길이: {len(all_text)} 문자")

        # 1단계: LLM으로 실명만 추출
        extraction_prompt = """당신은 건축 도면 분석 전문가입니다.
주어진 PDF 텍스트에서 실명(방 이름)들만 추출해주세요.

실명의 특징:
- 한글로 된 방 이름 (예: 관리실, 전기실, 발전기실, 경유탱크실, 창고-1, 창고-2, ELEV홀 등)
- 숫자나 특수문자가 포함될 수 있음 (예: 창고-3, 전기실#1, ELEV#2홀)
- 괄호 안의 세부 구분도 포함 (예: 전기실(업무용))

**중요**: 축척, 도면번호, 치수, 좌표값 등은 실명이 아닙니다.

JSON 형식으로 실명만 배열로 응답해주세요:
{"room_names": ["실명1", "실명2", "실명3", ...]}"""

        extraction_user_prompt = f"""다음 PDF 텍스트에서 실명들만 추출해주세요:

{all_text[:10000]}

위 텍스트에서 실명(방 이름)들만 찾아서 JSON 배열로 응답해주세요."""

        extraction_messages = [
            {"role": "system", "content": extraction_prompt},
            {"role": "user", "content": extraction_user_prompt},
        ]

        extraction_content = await self.utils.call_llm_4(extraction_messages)
        if not extraction_content:
            print("❌ 실명 추출 실패")
            return user_room_name

        try:
            extraction_result = json.loads(extraction_content)
            extracted_rooms = extraction_result.get("room_names", [])
        except:
            raise Exception("❌ 실명 추출 JSON 파싱 실패")
            return user_room_name

        if not extracted_rooms:
            print("❌ 추출된 실명이 없습니다.")
            return user_room_name

        print(f"✅ 추출된 실명들: {extracted_rooms}")

        # 2단계: 사용자 입력과 가장 유사한 실명 찾기
        matching_prompt = """당신은 건축 도면 분석 전문가입니다.
사용자가 입력한 실명과 PDF에서 추출된 실명들을 비교하여 가장 일치하는 실명을 찾아주세요.

매칭 규칙:
- 완전 일치가 최우선
- 부분 일치 (예: "창고3" → "창고-3", "전기실1" → "전기실#1")
- 공백, 특수문자 차이 무시
- 의미상 같은 실명 찾기

JSON 형식으로 응답해주세요:
{"matched_room": "실제_실명", "confidence": "high/medium/low"}"""

        matching_user_prompt = f"""사용자 입력 실명: "{user_room_name}"

PDF에서 추출된 실명 목록:
{json.dumps(extracted_rooms, ensure_ascii=False, indent=2)}

사용자 입력과 가장 일치하는 실명을 찾아주세요."""

        matching_messages = [
            {"role": "system", "content": matching_prompt},
            {"role": "user", "content": matching_user_prompt},
        ]

        matching_content = await self.utils.call_llm_4(matching_messages)
        if not matching_content:
            print("❌ 실명 매칭 실패")
            return user_room_name

        try:
            matching_result = json.loads(matching_content)
            matched_room = matching_result.get("matched_room", user_room_name)
            confidence = matching_result.get("confidence", "low")

            # None이나 빈 문자열인 경우 원본 실명 사용
            if not matched_room or matched_room == "None" or matched_room.strip() == "":
                print(f"⚠️ 매칭 실패, 원본 실명 사용: '{user_room_name}'")
                return user_room_name
            else:
                print(
                    f"✅ 매칭 성공 ({confidence}): '{user_room_name}' → '{matched_room}'"
                )
                return matched_room

        except Exception as e:
            raise Exception(f"❌ 실명 매칭 JSON 파싱 실패: {e}")
            return user_room_name

    async def search_documents_with_filter(
        self, filter_condition: str, select_fields: str = "*"
    ) -> List[Dict]:
        """필터 조건으로 문서 검색"""
        try:
            url = f"{self.search_endpoint}/indexes/{self.index_name}/docs/search"

            search_payload = {"search": "*", "select": select_fields, "top": 1000}

            # 필터 조건이 있을 때만 추가
            if filter_condition.strip():
                search_payload["filter"] = filter_condition

            print(f"   검색 요청: {search_payload}")

            response = requests.post(
                url,
                headers=self.search_headers,
                params=self.search_params,
                json=search_payload,
            )

            if response.status_code == 200:
                result = response.json()
                documents = result.get("value", [])
                print(f"   ✅ 필터 검색 완료: {len(documents)}개 문서 발견")

                # 검색 결과 샘플 출력
                if documents:
                    print("   검색 결과 샘플:")
                    for i, doc in enumerate(documents[:3]):
                        print(
                            f"     {i + 1}. '{doc.get('drawing_name', '')}' - area: {doc.get('area', [])}"
                        )

                return documents
            else:
                print(f"   ❌ 검색 실패: {response.status_code} - {response.text}")
                return []

        except Exception as e:
            raise Exception(f"   ❌ 검색 오류: {e}")
            return []

    async def get_filtered_documents(
        self, query_analysis: Dict[str, Any]
    ) -> Dict[str, List[Dict]]:
        """쿼리 분석 결과를 바탕으로 4가지 필터로 문서 검색"""
        floor = query_analysis.get("floor", "")
        results = {}

        print("📋 필터 조건으로 문서 검색 중...")

        # 먼저 전체 문서를 조회해서 실제 데이터 확인
        print("📋 전체 문서 조회로 디버깅...")
        all_docs = await self.search_documents_with_filter("", "drawing_name,area")
        print(f"전체 문서 수: {len(all_docs)}")

        # 도면명 샘플 출력
        if all_docs:
            print("도면명 샘플:")
            for i, doc in enumerate(all_docs[:5]):
                print(
                    f"  {i + 1}. '{doc.get('drawing_name', '')}' - area: {doc.get('area', [])}"
                )

        # 1. 평면도 검색 (contains 사용)
        floor_plan_filter = (
            f"search.ismatch('평면도', 'drawing_name') and area/any(a: a eq '{floor}')"
        )
        print(f"🔍 평면도 필터: {floor_plan_filter}")
        results["floor_plan"] = await self.search_documents_with_filter(
            floor_plan_filter, "id,page_num,drawing_name,area,blob_path"
        )
        print(f"  - 평면도: {len(results['floor_plan'])}개")

        # 2. 벽체 안내도 검색
        wall_guide_filter = f"search.ismatch('벽체', 'drawing_name') and search.ismatch('안내도', 'drawing_name') and area/any(a: a eq '{floor}')"
        print(f"🔍 벽체 안내도 필터: {wall_guide_filter}")
        results["wall_guide"] = await self.search_documents_with_filter(
            wall_guide_filter, "id,page_num,drawing_name,area,blob_path"
        )
        print(f"  - 벽체 안내도: {len(results['wall_guide'])}개")

        # 3. 건식 벽체 일람표 검색
        wall_table_filter = "search.ismatch('건식', 'drawing_name') and search.ismatch('벽체', 'drawing_name') and search.ismatch('일람표', 'drawing_name')"
        print(f"🔍 건식 벽체 일람표 필터: {wall_table_filter}")
        results["wall_table"] = await self.search_documents_with_filter(
            wall_table_filter, "id,drawing_name,content"
        )
        print(f"  - 건식 벽체 일람표: {len(results['wall_table'])}개")

        # 4. 실내재료마감표 검색
        material_table_filter = f"search.ismatch('실내재료마감표', 'drawing_name') and (area/any(a: a eq '{floor}') or area/any(a: a eq '공통'))"
        print(f"🔍 실내재료마감표 필터: {material_table_filter}")
        results["material_table"] = await self.search_documents_with_filter(
            material_table_filter, "id,drawing_name,content,area"
        )
        print(f"  - 실내재료마감표: {len(results['material_table'])}개")

        return results

    async def get_pdf_bytes_from_blob(self, blob_url: str) -> bytes:
        """Blob URL에서 PDF를 메모리로 가져오기"""
        try:
            if not self.blob_available:
                print("⚠️ Blob Storage 설정이 없습니다.")
                return None

            print(f"🔍 Blob에서 PDF 다운로드 중: {blob_url}")

            # blob_url에서 컨테이너명과 blob명 추출
            # 예: https://account.blob.core.windows.net/container/blob.pdf
            url_parts = blob_url.replace(
                f"https://{self.account_name}.blob.core.windows.net/", ""
            ).split("/", 1)
            if len(url_parts) != 2:
                print(f"❌ 잘못된 blob URL: {blob_url}")
                return None

            container_name, blob_name = url_parts
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

    async def analyze_room_from_indexed_data(
        self,
        user_query: str,
        filtered_docs: Dict[str, List[Dict]],
        query_analysis: Dict[str, Any],
        show_ui: bool = False,
        send_status=None,
    ):
        """인덱스 데이터를 바탕으로 실 분석 수행"""
        user_room_name = query_analysis.get("room_name", "")

        print(f"🏠 '{user_room_name}' 실 분석 시작...")
        await send_status(f"'{user_room_name}' 공간 분석 시작...", done=False)

        # 먼저 실명 매칭 수행 (평면도 또는 벽체안내도 PDF 사용)

        # 평면도나 벽체안내도 중 하나에서 실명 매칭 수행
        pdf_for_matching = None
        matching_doc_info = None

        if filtered_docs["floor_plan"]:
            floor_plan_doc = filtered_docs["floor_plan"][0]
            matching_doc_info = floor_plan_doc
            pdf_for_matching = await self.get_pdf_bytes_from_blob(
                floor_plan_doc["blob_path"]
            )
            print("🔍 평면도 PDF로 실명 매칭 수행")
            print(f"   - 도면명: {floor_plan_doc.get('drawing_name', 'N/A')}")
            print(f"   - 영역: {floor_plan_doc.get('area', [])}")
            print(f"   - 페이지: {floor_plan_doc.get('page_num', 'N/A')}")
            print(f"   - Blob URL: {floor_plan_doc.get('blob_path', 'N/A')}")
        elif filtered_docs["wall_guide"]:
            wall_guide_doc = filtered_docs["wall_guide"][0]
            matching_doc_info = wall_guide_doc
            pdf_for_matching = await self.get_pdf_bytes_from_blob(
                wall_guide_doc["blob_path"]
            )
            print("🔍 벽체안내도 PDF로 실명 매칭 수행")
            print(f"   - 도면명: {wall_guide_doc.get('drawing_name', 'N/A')}")
            print(f"   - 영역: {wall_guide_doc.get('area', [])}")
            print(f"   - 페이지: {wall_guide_doc.get('page_num', 'N/A')}")
            print(f"   - Blob URL: {wall_guide_doc.get('blob_path', 'N/A')}")

        if pdf_for_matching and matching_doc_info:
            # 해당 페이지에서만 실명 추출
            target_page = matching_doc_info.get("page_num", None)
            matched_room = await self.extract_and_match_room_names(
                pdf_for_matching, user_room_name, target_page
            )
            if matched_room and matched_room != "None" and matched_room.strip():
                actual_room_name = matched_room
                print(f"🏠 최종 사용할 실명: '{actual_room_name}'")
            else:
                print(f"⚠️ 실명 매칭 실패, 원본 사용: '{actual_room_name}'")

        await send_status(f"'{actual_room_name}' 실번호 추출 시작...", done=False)
        # 1. 평면도에서 실번호 추출
        material_info = {}
        if filtered_docs["floor_plan"]:
            floor_plan_doc = filtered_docs["floor_plan"][0]  # 첫 번째 문서 사용
            blob_url = floor_plan_doc["blob_path"]
            page_num = floor_plan_doc["page_num"]

            # PDF를 메모리로 로드
            pdf_bytes = await self.get_pdf_bytes_from_blob(blob_url)
            if pdf_bytes:
                # 메모리에서 PDF 열기
                doc = fitz.open(stream=pdf_bytes, filetype="pdf")
                if page_num <= len(doc):
                    pdf_page = doc[page_num - 1]  # page_num은 1부터 시작

                    # 특정 페이지만 추출해서 새로운 PDF 생성

                    # 해당 페이지만 추출해서 새로운 PDF 생성
                    single_page_doc = fitz.open()
                    single_page_doc.insert_pdf(
                        doc, from_page=page_num - 1, to_page=page_num - 1
                    )

                    # 단일 페이지 PDF를 design_poc 디렉토리에 저장
                    current_dir = os.path.dirname(
                        os.path.dirname(os.path.abspath(__file__))
                    )
                    temp_pdf_path = os.path.join(
                        current_dir,
                        f"temp_floor_plan_page_{page_num}_{actual_room_name}.pdf",
                    )
                    single_page_doc.save(temp_pdf_path)
                    single_page_doc.close()

                    print(
                        f"   단일 페이지 PDF 생성: {temp_pdf_path} (페이지 {page_num})"
                    )

                    # 단일 페이지 PDF에서 텍스트 추출 테스트
                    test_doc = fitz.open(temp_pdf_path)
                    test_page = test_doc[0]
                    test_text = test_page.get_text()
                    if actual_room_name in test_text:
                        print(f"   ✅ '{actual_room_name}' 텍스트 발견!")
                    else:
                        print(f"   ❌ '{actual_room_name}' 텍스트 없음")
                    test_doc.close()

                    room_coords = await self.utils.extract_room_coordinates(
                        temp_pdf_path, actual_room_name
                    )
                    print(f"   평면도 실 좌표 결과: {room_coords}")

                    if room_coords:
                        high_res_image = await self.utils.create_high_res_image(
                            temp_pdf_path
                        )
                        print(f"   평면도 이미지 크기: {high_res_image.size}")

                        # 단일 페이지 PDF의 첫 번째 페이지 사용
                        single_doc = fitz.open(temp_pdf_path)
                        single_pdf_page = single_doc[
                            0
                        ]  # 단일 페이지 PDF의 첫 번째 페이지

                        cropped_image = await self.utils.crop_room_area(
                            high_res_image,
                            room_coords,
                            actual_room_name,
                            single_pdf_page,
                            "평면도",
                        )
                        single_doc.close()
                        print(f"   평면도 크롭된 이미지 크기: {cropped_image.size}")

                        # 실번호 추출 (기존 함수 사용)
                        (
                            material_info,
                            material_info_reason,
                            material_info_image_url,
                        ) = await self.extract_material_codes_from_floor_plan(
                            cropped_image, actual_room_name, show_ui
                        )
                        print(f"   평면도 실번호 추출 결과: {material_info}")
                    else:
                        print(
                            f"   ❌ 평면도에서 '{actual_room_name}' 실 좌표를 찾을 수 없습니다."
                        )

                    # 임시 파일 정리
                    try:
                        os.unlink(temp_pdf_path)
                    except:
                        pass
                doc.close()
        await send_status(f"평면도 실번호 추출 결과: {material_info}", done=False)

        await send_status(f"'{actual_room_name}' 벽체코드 추출 시작...", done=False)
        # 2. 벽체안내도에서 벽체코드 추출
        wall_codes = []
        if filtered_docs["wall_guide"]:
            wall_guide_doc = filtered_docs["wall_guide"][0]  # 첫 번째 문서 사용
            blob_url = wall_guide_doc["blob_path"]
            page_num = wall_guide_doc["page_num"]

            # PDF를 메모리로 로드
            pdf_bytes = await self.get_pdf_bytes_from_blob(blob_url)
            if pdf_bytes:
                # 메모리에서 PDF 열기
                doc = fitz.open(stream=pdf_bytes, filetype="pdf")
                if page_num <= len(doc):
                    pdf_page = doc[page_num - 1]  # page_num은 1부터 시작

                    # 특정 페이지만 추출해서 새로운 PDF 생성

                    # 해당 페이지만 추출해서 새로운 PDF 생성
                    single_page_doc = fitz.open()
                    single_page_doc.insert_pdf(
                        doc, from_page=page_num - 1, to_page=page_num - 1
                    )

                    # 단일 페이지 PDF를 design_poc 디렉토리에 저장
                    current_dir = os.path.dirname(
                        os.path.dirname(os.path.abspath(__file__))
                    )
                    temp_pdf_path = os.path.join(
                        current_dir,
                        f"temp_wall_guide_page_{page_num}_{actual_room_name}.pdf",
                    )
                    single_page_doc.save(temp_pdf_path)
                    single_page_doc.close()

                    print(
                        f"   단일 페이지 PDF 생성: {temp_pdf_path} (페이지 {page_num})"
                    )

                    # 단일 페이지 PDF에서 텍스트 추출 테스트
                    test_doc = fitz.open(temp_pdf_path)
                    test_page = test_doc[
                        0
                    ]  # 이제 첫 번째 페이지가 우리가 원하는 페이지
                    test_text = test_page.get_text()
                    if actual_room_name in test_text:
                        print(f"   ✅ '{actual_room_name}' 텍스트 발견!")
                    else:
                        print(f"   ❌ '{actual_room_name}' 텍스트 없음")
                    test_doc.close()

                    # 기존 utils 함수 사용 (이제 첫 번째 페이지가 우리가 원하는 페이지)
                    room_coords = await self.utils.extract_room_coordinates(
                        temp_pdf_path, actual_room_name
                    )
                    print(f"   벽체안내도 실 좌표 결과: {room_coords}")

                    if room_coords:
                        # 기존 utils 함수 사용
                        high_res_image = await self.utils.create_high_res_image(
                            temp_pdf_path
                        )
                        print(f"   벽체안내도 이미지 크기: {high_res_image.size}")

                        # 단일 페이지 PDF의 첫 번째 페이지 사용
                        single_doc = fitz.open(temp_pdf_path)
                        single_pdf_page = single_doc[
                            0
                        ]  # 단일 페이지 PDF의 첫 번째 페이지

                        cropped_image = await self.utils.crop_room_area(
                            high_res_image,
                            room_coords,
                            actual_room_name,
                            single_pdf_page,
                            "벽체안내도",
                        )
                        single_doc.close()
                        print(f"   벽체안내도 크롭된 이미지 크기: {cropped_image.size}")

                        # 벽체코드 추출 (기존 함수 사용)
                        (
                            wall_codes,
                            wall_codes_reason,
                            wall_codes_image_url,
                        ) = await self.extract_wall_codes_from_wall_guide(
                            cropped_image, actual_room_name, show_ui
                        )

                    else:
                        print(
                            f"   ❌ 벽체안내도에서 '{actual_room_name}' 실 좌표를 찾을 수 없습니다."
                        )

                    # 임시 파일 정리
                    try:
                        os.unlink(temp_pdf_path)
                    except:
                        pass
                doc.close()

        def md_table_escape(text: str) -> str:
            if text is None:
                return ""
            s = str(text)
            s = s.replace("\\", "\\\\")  # 역슬래시 먼저
            s = s.replace("|", "\\|")  # 파이프 이스케이프
            s = s.replace("`", "\\`")  # 백틱 이스케이프
            s = s.replace("\r\n", "<br>").replace("\n", "<br>")
            return s

        safe_wall_codes = [code.replace("|", "\\|") for code in wall_codes]

        await send_status(f"벽체코드 추출 결과: {wall_codes}", done=False)

        await send_status("도면 분석 결과 생성", done=False)
        table_output_data = f"""
## 도면 분석 결과

| 실번호 추출 결과 | 벽체 라벨 추출 결과 |
| --- | --- |
| ![]({material_info_image_url}) | ![]({wall_codes_image_url}) |
| 실번호 : `{material_info["material_code"]}` 층고 : `{material_info["ceiling_height"]}` | 벽체코드 : {", ".join(f"`{code}`" for code in safe_wall_codes)} |
| {md_table_escape(material_info_reason)} | {md_table_escape(wall_codes_reason)} |

"""

        yield table_output_data

        await send_status("도면 분석 결과 추론 시작...", done=False)

        # 3. 건식벽체일람표 내용 수집
        wall_table_content = ""
        for doc in filtered_docs["wall_table"]:
            content = doc.get("content", "")
            if content:
                wall_table_content += (
                    f"\n=== {doc.get('drawing_name', 'Unknown')} ===\n{content}"
                )

        # 4. 실내재료마감표 내용 수집
        material_table_content = ""
        for doc in filtered_docs["material_table"]:
            content = doc.get("content", "")
            if content:
                material_table_content += (
                    f"\n=== {doc.get('drawing_name', 'Unknown')} ===\n{content}"
                )

        # 5. 기존 분석 로직 사용하여 통합 분석
        # 건식벽체일람표 분석
        wall_analysis_result = (
            await self.analyze_wall_types_with_llm(wall_table_content)
            if wall_table_content
            else {"wall_types": []}
        )

        # 재료 정보 분석
        material_details = "찾을 수 없음"
        if material_info.get("material_code", "-") != "-" and material_table_content:
            material_details = await self.find_material_by_code(
                material_info.get("material_code", ""), material_table_content
            )

        # 최종 분석 결과 구성
        all_material_analysis = [
            {
                "room_name": actual_room_name,
                "wall_codes": wall_codes,
                "material_code": material_info.get("material_code", "-"),
                "ceiling_height": material_info.get("ceiling_height", "-"),
                "material_details": material_details,
            }
        ]

        # 통합 벽체 분석 (기존 로직 사용)
        integrated_wall_analysis = await self.analyze_wall_integration(
            wall_analysis_result, wall_codes
        )

        # 최종 비교 분석
        final_response = await self.generate_final_comparison(
            integrated_wall_analysis, all_material_analysis, user_query
        )

        # 최종 응답 yield
        yield final_response

    async def extract_wall_codes_from_wall_guide(
        self, cropped_image, room_name: str, show_ui: bool = False
    ) -> List[str]:
        """벽체안내도에서 다이아몬드 라벨 벽체 코드 추출 (기존 로직 사용)"""
        print(f"🔍 [{room_name}] 벽체안내도에서 다이아몬드 라벨 벽체 코드 추출 중...")

        # image_base64 = self.utils.encode_image_to_base64(cropped_image)
        image_url = await self.utils.upload_image_to_blob(cropped_image)

        user_prompt = f"""이 도면에서 빨간색 박스로 표시된 '{room_name}' 실과 연결된 벽체의 라벨을 찾아주세요."""
        system_prompt = (
            WALL_GUIDE_ANALYSIS_PROMPT
            + f"""
        답변 포멧은 아래를 지켜서 제공 하세요
        {PydanticOutputParser(pydantic_object=WallGuideAnalysisResult).get_format_instructions()}
        """
        )

        messages = [
            {"role": "system", "content": system_prompt},
            {
                "role": "user",
                "content": [
                    {
                        "type": "text",
                        "text": "이 이미지를 보고 관리실과 연결된 벽체 라벨을 찾아주세요.",
                    },
                    {
                        "type": "image_url",
                        "image_url": {
                            "url": "https://ailab01storage01.blob.core.windows.net/drawings/c61a0521-1ba1-468f-a9f9-7b63b600962b.png"
                        },
                    },
                ],
            },
            {
                "role": "assistant",
                "content": json.dumps(
                    {
                        "wall_type_codes": ["BL6|A", "W2|A"],
                        "reason": """
                    - DF1|A → 관리실 공간 상단 벽체 근처에 있지만, 연결부위가 관리실 공간에 없고 계단실#2 전실 공간에 있으므로 **[제외]**
                    - BL8|A → 연결부위가 관리실 공간이 아닌 인접 공간에 있으므로 **[제외]**
                    - BL6|A → 관리실 공간 오른쪽 벽체 및 입구 쪽에 연결부위가 존재하며 해당 연결부위와 연결된 라벨로 **[포함]**
                    - W2|A → 관리실 공간 하단 벽체에 연결부위가 있으며 직접 연결된 라벨로 **[포함]**
                    - DA → 설비 코드이므로 **[제외]**
                """,
                    }
                ),
            },
            {
                "role": "user",
                "content": [
                    {
                        "type": "text",
                        "text": "이 이미지를 보고 연료전지실과 연결된 벽체 라벨을 찾아주세요.",
                    },
                    {
                        "type": "image_url",
                        "image_url": {
                            "url": "https://ailab01storage01.blob.core.windows.net/drawings/fda5f889-b0b7-495d-8a37-ef77b7549456.png"
                        },
                    },
                ],
            },
            {
                "role": "assistant",
                "content": json.dumps(
                    {
                        "wall_type_codes": ["DF3|A", "BL6|A", "W1|A"],
                        "reason": """
                    - DF3|A → 연료전지실 공간 주변 총 2개의 DF3|A가 확인되며 상단의 라벨은 연결부위가 연료전지실이 아닌 비상용ELEV#2홀에 연결되어 제외입니다. 하지만 연료전지실 하단 벽체 근처에 연결부위가 식별되고 연결된 라벨로 **[포함]** 
                    - BL6|A → 연료전지실 공간 상단 벽체에 연결부위가 있으며 벽체와 직접 연결된 라벨로 **[포함]**
                    - W2|A → 연료전지실 공간 하단 벽체와 연결된 라벨로 보이지만 연결부위가 연료전지실의 벽체가 아닌 다른 공간의 벽체와 연결된 것으로 보입니다 **[제외]**
                    - W1|A → 연료전지실 공간 상단 벽체에 연결부위가 있으며 벽체와 직접 연결된 라벨로 **[포함]**
                """,
                    }
                ),
            },
            {
                "role": "user",
                "content": [
                    {
                        "type": "text",
                        "text": "이 이미지를 보고 발전기실과 연결된 벽체 라벨을 찾아주세요.",
                    },
                    {
                        "type": "image_url",
                        "image_url": {
                            "url": "https://ailab01storage01.blob.core.windows.net/drawings/dfffd6a6-c337-4143-9fa8-9f5994ed51b1.png"
                        },
                    },
                ],
            },
            {
                "role": "assistant",
                "content": json.dumps(
                    {
                        "wall_type_codes": ["BL8|A", "W2|A"],
                        "reason": """
                    - BL8|A → 발전기실 공간의 벽체와 직접 연결된 라벨이며, 벽체의 연결부위가 반복적으로 해당 공간에 속해있으므로 **[포함]**
                    - DF3|A → 연결부위가 다른 공간의 벽체와 연결되어 있으므로 **[제외]**
                    - W2|A → 발전기실 공간의 상단 벽체에 연결부위가 있으며 직접 연결된 라벨이므로 **[포함]**
                    - BL6|A → 발전기실 공간 상단 벽체와 연결되어 있는 것으로 보이나, 연결 부위 (짧고 굵은 직선) 가 존재 하지 않으므로 **[제외]**
                    - DA, OA → 설비 코드이며, 벽체와 관련없음 **[제외]**
                """,
                    }
                ),
            },
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": user_prompt},
                    {"type": "image_url", "image_url": {"url": image_url}},
                ],
            },
        ]
        content = await self.utils.call_llm_4o(messages)
        if not content:
            print("   ❌ LLM 응답 없음")
            return []

        try:
            result = json.loads(content)
            wall_codes = result.get("wall_type_codes", [])
            reason = result.get("reason", "")
            return wall_codes, reason, image_url
        except:
            return [], ""

    async def extract_material_codes_from_floor_plan(
        self, cropped_image: Image.Image, room_name: str, show_ui: bool = False
    ) -> Dict[str, str]:
        """평면도에서 실번호 층고 추출 (기존 로직 사용)"""
        print(f"🔍 [{room_name}] 평면도에서 실번호 층고 추출 중...")

        # image_base64 = self.utils.encode_image_to_base64(cropped_image)
        image_url = await self.utils.upload_image_to_blob(cropped_image)

        user_prompt = f"""이 도면에서 빨간색 박스로 표시된 '{room_name}' 실의 실번호와 층고를 찾아주세요.

실번호는 영문+숫자 형태이고, 층고는 숫자로 표시됩니다.
"-"로 표시된 것은 없는 것으로 간주하세요.

JSON 형식으로 응답해주세요."""

        system_prompt = (
            FLOOR_PLAN_ANALYSIS_PROMPT
            + f"""
        답변 포멧은 아래를 지켜서 제공 하세요
        {PydanticOutputParser(pydantic_object=MaterialInfoResult).get_format_instructions()}
        """
        )

        messages = [
            {"role": "system", "content": system_prompt},
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": user_prompt},
                    {"type": "image_url", "image_url": {"url": image_url}},
                ],
            },
        ]

        content = await self.utils.call_llm_4o(messages)
        if not content:
            print("   ❌ LLM 응답 없음")
            return {"material_code": "-", "ceiling_height": "-"}

        try:
            result = json.loads(content)
            material_info = {
                "material_code": result.get("material_code", "-"),
                "ceiling_height": result.get("ceiling_height", "-"),
            }
            material_info_reason = result.get("reason", "")

            return material_info, material_info_reason, image_url
        except:
            return {"material_code": "-", "ceiling_height": "-"}, "", image_url

    async def analyze_wall_types_with_llm(
        self, wall_table_content: str
    ) -> Dict[str, Any]:
        """건식벽체일람표 내용을 LLM으로 분석 (기존 로직 사용)"""
        print("🔍 건식벽체일람표 LLM 분석 중...")

        user_prompt = f"""다음은 여러 건식벽체일람표 파일의 텍스트입니다:

{wall_table_content}

이 텍스트들을 모두 분석하여 벽체 타입별로 벽체 종류와 내화구조 정보를 추출해주세요.
중복된 벽체 타입이 있으면 통합하여 정리해주세요."""

        messages = [
            {"role": "system", "content": WALL_TABLE_ANALYSIS_PROMPT},
            {"role": "user", "content": user_prompt},
        ]

        content = await self.utils.call_llm_4(messages)
        if not content:
            print("   ❌ LLM 응답 없음")
            return {"wall_types": []}

        try:
            result = json.loads(content)
            return result
        except:
            return {"wall_types": []}

    async def find_material_by_code(
        self, material_code: str, material_table_content: str
    ) -> str:
        """실번호 실제 재료 정보 찾기 (기존 로직 사용)"""
        print(f"🔍 실번호 '{material_code}'의 실제 재료 찾기...")

        user_prompt = f"""다음 테이블에서 실번호 '{material_code}'에 해당하는 재료 정보를 찾아주세요.

{material_table_content}

위 테이블에서 '{material_code}' 코드를 찾아서 해당하는 재료 정보를 추출해주세요.

JSON 형식으로 응답해주세요."""

        messages = [
            {"role": "system", "content": MATERIAL_CODE_ANALYSIS_PROMPT},
            {"role": "user", "content": user_prompt},
        ]

        content = await self.utils.call_llm_4(messages)
        if not content:
            print("   ❌ LLM 응답 없음")
            return "찾을 수 없음"

        try:
            result = json.loads(content)
            if result.get("found", False):
                return result.get("materials", "")
            else:
                return "찾을 수 없음"
        except:
            return "찾을 수 없음"

    async def analyze_wall_integration(
        self, wall_analysis_result: Dict, wall_codes: List[str]
    ) -> str:
        """벽체 정보 통합 분석 (간소화된 버전)"""
        print("🔍 벽체 정보 통합 분석 중...")

        # 벽체 분석 결과를 텍스트로 변환
        wall_analysis_text = "건식벽체일람표 분석 결과:\n"
        if "wall_types" in wall_analysis_result:
            for i, wall in enumerate(wall_analysis_result["wall_types"], 1):
                wall_analysis_text += f"{i}. {wall.get('type', 'N/A')}\n"
                wall_analysis_text += f"   벽체 종류: {wall.get('wall_type', 'N/A')}\n"
                wall_analysis_text += (
                    f"   내화구조: {wall.get('fire_rating', 'N/A')}\n\n"
                )

        user_prompt = f"""다음 정보들을 통합하여 벽체 정보를 분석해주세요.

**건식벽체일람표 정보**:
{wall_analysis_text}

**벽체안내도에서 추출한 벽체코드**:
{wall_codes}

위 정보를 종합하여 각 벽체코드에 대한 실제 구성 재료와 높이 정보를 분석해주세요."""

        messages = [
            {"role": "system", "content": PARTITION_INTEGRATION_PROMPT},
            {"role": "user", "content": user_prompt},
        ]

        content = await self.utils.call_llm_4(messages)
        if not content:
            print("   ❌ LLM 응답 없음")
            return "분석 불가"

        print("   ✅ 벽체 정보 통합 분석 완료")
        return content

    async def generate_final_comparison(
        self, wall_analysis: str, material_analysis: List[Dict], user_query: str
    ) -> str:
        """최종 비교 분석 및 응답 생성 (마크다운 테이블 형태)"""
        print("📝 최종 비교 분석 및 응답 생성 중...")

        user_prompt = f"""다음 정보들을 분석하여 마크다운 테이블 형태로 정리해주세요.

**사용자 쿼리**: {user_query}

**통합 벽체 정보**:
{wall_analysis}

**실별 재료 정보**:
{json.dumps(material_analysis, ensure_ascii=False, indent=2)}

**파티션종류기호 참조 정보**:
- 0.5B: 0.5B 시멘트벽돌
- 1.0B: 1.0B 시멘트벽돌  
- BL4: 4" 콘크리트 블록
- BL6: 6" 콘크리트 블록
- BL8: 8" 콘크리트 블록
- D NO: GYPSUM WALL BOARD
- 높이코드 A: FULL HEIGHT (전체 높이)

**중요한 규칙**:
1. 주어진 데이터에 없는 정보는 절대 추측하거나 지어내지 마세요
2. 확인할 수 없는 정보는 "확인할 수 없음" 또는 "데이터 없음"으로 표시하세요
3. 실제 추출된 코드와 정보만 사용하세요

다음 형식으로 응답해주세요:

## 코드별 정보 분석 결과

### 실번호 정보
| 항목 | 코드 | 정보 | 출처 |
|------|------|------|------|
| 실번호 | (실제코드 또는 확인할수없음) | (실제정보 또는 확인할수없음) | 평면도 |
| 층고 | (실제값 또는 확인할수없음) | (실제정보 또는 확인할수없음) | 평면도 |

### 벽체 라벨 정보  
| 항목 | 코드 | 정보 | 출처 |
|------|------|------|------|
| 벽체코드 | (실제코드 또는 확인할수없음) | (실제정보 또는 확인할수없음) | 벽체안내도 |
| 높이코드 | (실제코드 또는 확인할수없음) | (실제정보 또는 확인할수없음) | 벽체안내도 |


### 코드간 연결 관계 및 호환성
**주어진 데이터를 바탕으로만 분석:**
- 실번호와 벽체코드의 연결성: (실제 데이터 기반 분석 또는 "확인할 수 없음")
- 층고와 벽체 높이의 호환성: (실제 데이터 기반 분석 또는 "확인할 수 없음")
- 전체적인 일관성: (실제 데이터 기반 평가 또는 "확인할 수 없음")

**절대 금지**: 추측, 가정, 일반적인 건축 지식으로 빈 정보 채우기, 추가 작업 제안"""

        messages = [
            {
                "role": "system",
                "content": "당신은 건축 도면 분석 전문가입니다. 주어진 정보를 마크다운 테이블 형태로 정확하게 정리해주세요.",
            },
            {"role": "user", "content": user_prompt},
        ]

        content = await self.utils.call_llm_4(messages)
        if not content:
            print("   ❌ LLM 응답 없음")
            return "분석 불가"

        print("   ✅ 최종 응답 생성 완료")
        return content

    async def run_indexed_analysis(self, user_query: str) -> str:
        """인덱스 기반 실 분석 실행"""
        print("=== 인덱스 기반 실 분석 시스템 시작 ===")
        print(f"사용자 쿼리: {user_query}")

        try:
            # 1. 사용자 쿼리 분석
            query_analysis = await self.analyze_user_query(user_query)
            if not query_analysis or (
                len(query_analysis.get("floor", "")) == 0
                and len(query_analysis.get("room_name", "")) == 0
                and query_analysis.get("required_documents", []) == []
            ):
                return "사용자 쿼리 분석에 실패했습니다. 층수, 실명, 필요한 문서 유형을 명시적으로 입력해주세요."

            # 2. 필터 조건으로 문서 검색
            filtered_docs = await self.get_filtered_documents(query_analysis)

            # 검색 결과 확인
            total_docs = sum(len(docs) for docs in filtered_docs.values())
            if total_docs == 0:
                return "검색된 문서가 없습니다. 인덱스에 해당 데이터가 있는지 확인해주세요."

            # 3. 인덱스 데이터를 바탕으로 실 분석
            result = await self.analyze_room_from_indexed_data(
                user_query, filtered_docs, query_analysis, show_ui=False
            )

            return result

        except Exception as e:
            raise Exception(f"분석 중 오류 발생: {e}")
            return f"분석 중 오류가 발생했습니다: {str(e)}"

    async def run_indexed_analysis_with_ui(self, user_query: str, send_status):
        """UI 표시가 포함된 인덱스 기반 실 분석 실행"""
        print("=== 인덱스 기반 실 분석 시스템 시작 (UI 포함) ===")
        print(f"사용자 쿼리: {user_query}")

        await send_status("=== 도면 분석 시스템 시작 ===", done=False)

        try:
            # 1. 사용자 쿼리 분석
            query_analysis = await self.analyze_user_query(user_query)
            if not query_analysis or not any(
                [
                    query_analysis.get("floor"),
                    query_analysis.get("room_name"),
                    query_analysis.get("required_documents"),
                ]
            ):
                yield "❌ 사용자 쿼리 분석에 실패했습니다. 층수, 실명, 필요한 문서 유형을 명시적으로 입력해주세요."
                return

            # 2. 필터 조건으로 문서 검색
            filtered_docs = await self.get_filtered_documents(query_analysis)

            # 검색 결과 확인
            total_docs = sum(len(docs) for docs in filtered_docs.values())
            if total_docs == 0:
                yield "❌ 검색된 문서가 없습니다. 인덱스에 해당 데이터가 있는지 확인해주세요."
                return

            # 3. 인덱스 데이터를 바탕으로 실 분석 (UI 표시 포함)
            async for ui_content in self.analyze_room_from_indexed_data(
                user_query,
                filtered_docs,
                query_analysis,
                show_ui=True,
                send_status=send_status,
            ):
                if ui_content:
                    yield ui_content

        except Exception as e:
            raise Exception(f"❌ 분석 중 오류 발생: {e}")
            yield f"❌ 분석 중 오류가 발생했습니다: {str(e)}"
