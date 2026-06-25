#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
실 분석 시스템용 유틸리티 함수들
- PDF 처리 함수
- 이미지 처리 함수
- 좌표 추출 함수
- Document Intelligence 처리 함수
"""

import base64
import io
import os
import uuid
from typing import Dict, List, Optional

import fitz  # PyMuPDF
import pdfplumber
import requests
from azure.ai.documentintelligence import DocumentIntelligenceClient
from azure.core.credentials import AzureKeyCredential
from azure.storage.blob import BlobServiceClient
from PIL import Image, ImageDraw


class RoomAnalysisUtils:
    """실 분석 시스템용 유틸리티 클래스"""

    def __init__(self, valves):
        """유틸리티 초기화"""
        # Azure OpenAI 설정
        self.aoai_key = valves.AZURE_OPENAI_API_KEY
        self.aoai_endpoint = valves.AZURE_OPENAI_ENDPOINT

        # GPT-4o 설정 (이미지 분석용)
        self.aoai_deployment_4o = valves.AZURE_OPENAI_DEPLOYMENT_IMAGE
        self.aoai_version_4o = valves.AZURE_OPENAI_API_VERSION

        # GPT-4 설정 (텍스트 분석용)
        self.aoai_deployment_4 = valves.AZURE_OPENAI_DEPLOYMENT
        self.aoai_version_4 = valves.AZURE_OPENAI_API_VERSION

        # Azure Document Intelligence 설정
        self.di_endpoint = valves.AZURE_DOCUMENT_INTELLIGENCE_ENDPOINT
        self.di_key = valves.AZURE_DOCUMENT_INTELLIGENCE_API_KEY

        # 설정 검증
        if not all([self.aoai_key, self.aoai_endpoint]):
            raise ValueError("Azure OpenAI 기본 설정이 필요합니다.")
        if not all([self.aoai_deployment_4o, self.aoai_version_4o]):
            raise ValueError("GPT-4o 설정이 필요합니다.")
        if not all([self.aoai_deployment_4]):
            raise ValueError("GPT-4 설정이 필요합니다.")
        if not all([self.di_endpoint, self.di_key]):
            raise ValueError("Azure Document Intelligence 설정이 필요합니다.")

        # Document Intelligence 클라이언트 초기화
        self.di_client = DocumentIntelligenceClient(
            endpoint=self.di_endpoint, credential=AzureKeyCredential(self.di_key)
        )

        # Azure Storage 설정
        self.storage_account_name = valves.ACCOUNT_NAME
        self.storage_account_key = valves.ACCOUNT_KEY
        self.container_name = valves.CONTAINER_NAME_DRAWING

        # Blob Service Client 초기화
        self.blob_service_client = BlobServiceClient(
            account_url=f"https://{self.storage_account_name}.blob.core.windows.net",
            credential=self.storage_account_key,
        )

    async def call_llm_4o(self, messages: List[Dict], temperature: float = 0) -> str:
        """GPT-4o 호출 (이미지 분석용)"""
        url = f"{self.aoai_endpoint}/openai/deployments/{self.aoai_deployment_4o}/chat/completions?api-version={self.aoai_version_4o}"
        headers = {"Content-Type": "application/json", "api-key": self.aoai_key}

        data = {"messages": messages, "temperature": temperature}

        try:
            response = requests.post(url, headers=headers, json=data, timeout=180)
            response.raise_for_status()
            result = response.json()
            content = result["choices"][0]["message"]["content"]

            # JSON 파싱 (마크다운 코드 블록 제거)
            if "```json" in content:
                content = content.split("```json")[1].split("```")[0].strip()
            elif "```" in content:
                content = content.split("```")[1].split("```")[0].strip()

            return content

        except Exception as e:
            print(f"   GPT-4o 호출 오류: {e}")
            return ""

    async def call_llm_4(self, messages: List[Dict], temperature: float = 0) -> str:
        """GPT-4 호출 (텍스트 분석용)"""
        url = f"{self.aoai_endpoint}/openai/deployments/{self.aoai_deployment_4}/chat/completions?api-version={self.aoai_version_4}"
        headers = {"Content-Type": "application/json", "api-key": self.aoai_key}

        data = {"messages": messages, "temperature": temperature}

        try:
            print(f"   GPT-4 요청 URL: {url}")
            print(f"   GPT-4 deployment: {self.aoai_deployment_4}")
            print(f"   GPT-4 API version: {self.aoai_version_4}")
            response = requests.post(url, headers=headers, json=data, timeout=180)
            response.raise_for_status()
            result = response.json()
            content = result["choices"][0]["message"]["content"]

            # JSON 파싱 (마크다운 코드 블록 제거)
            if "```json" in content:
                content = content.split("```json")[1].split("```")[0].strip()
            elif "```" in content:
                content = content.split("```")[1].split("```")[0].strip()

            return content

        except Exception as e:
            print(f"   GPT-4 호출 오류: {e}")
            return ""

    async def extract_room_coordinates(
        self, pdf_path: str, room_name: str
    ) -> Optional[Dict]:
        """실명을 찾아서 좌표를 추출"""
        print(f"PDF에서 '{room_name}' 실 좌표 추출 중...")

        doc = fitz.open(pdf_path)
        page = doc[0]
        text_dict = page.get_text("dict")

        room_coords = None
        for block in text_dict["blocks"]:
            if "lines" in block:
                for line in block["lines"]:
                    for span in line["spans"]:
                        text = span["text"].strip()
                        if room_name in text:
                            bbox = span["bbox"]
                            room_coords = {
                                "x1": bbox[0],
                                "y1": bbox[1],
                                "x2": bbox[2],
                                "y2": bbox[3],
                            }
                            print(
                                f"   실명 발견: '{text}' at ({bbox[0]:.1f}, {bbox[1]:.1f})"
                            )
                            break

        doc.close()
        return room_coords

    async def create_high_res_image(self, pdf_path: str) -> Image.Image:
        """PDF를 고해상도 이미지로 변환"""
        print("PDF를 고해상도 이미지로 변환 중...")

        doc = fitz.open(pdf_path)
        page = doc[0]
        mat = fitz.Matrix(600 / 72, 600 / 72)
        pix = page.get_pixmap(matrix=mat, alpha=False)
        img_data = pix.tobytes("png")
        image = Image.open(io.BytesIO(img_data))
        doc.close()

        print(f"   이미지 크기: {image.size}")
        return image

    async def crop_room_area(
        self,
        image: Image.Image,
        room_coords: Dict,
        room_name: str,
        pdf_page,
        pdf_type: str,
    ) -> Image.Image:
        """실 좌표를 기반으로 넓게 크롭합니다."""
        print(f"'{room_name}' 실 영역 크롭 중...")

        # PDF 좌표를 이미지 좌표로 변환
        pdf_width = pdf_page.rect.width
        pdf_height = pdf_page.rect.height
        scale_x = image.size[0] / pdf_width
        scale_y = image.size[1] / pdf_height

        # PDF 좌표를 이미지 좌표로 변환 (Y축 뒤집기)
        img_x = room_coords["x1"] * scale_x
        img_y = room_coords["y1"] * scale_y
        img_x1 = room_coords["x2"] * scale_x
        img_y1 = room_coords["y2"] * scale_y

        # Y좌표 정렬 (y1이 y보다 작을 수 있음)
        if img_y1 < img_y:
            img_y, img_y1 = img_y1, img_y

        print(
            f"   이미지 좌표: ({img_x:.1f}, {img_y:.1f}) - ({img_x1:.1f}, {img_y1:.1f})"
        )

        # 넓은 크롭 영역 설정 (이미지의 1/4 크기)
        crop_width = image.width // 4
        crop_height = image.height // 4

        # 실 중심으로 크롭 영역 계산
        center_x = (img_x + img_x1) / 2
        center_y = (img_y + img_y1) / 2

        crop_x1 = max(0, int(center_x - crop_width // 2))
        crop_y1 = max(0, int(center_y - crop_height // 2))
        crop_x2 = min(image.width, crop_x1 + crop_width)
        crop_y2 = min(image.height, crop_y1 + crop_height)

        print(f"   크롭 영역: ({crop_x1}, {crop_y1}) - ({crop_x2}, {crop_y2})")

        # 이미지 크롭
        cropped_image = image.crop((crop_x1, crop_y1, crop_x2, crop_y2))

        # 크롭된 이미지에서 실 위치 계산
        room_x_in_crop = img_x - crop_x1
        room_y_in_crop = img_y - crop_y1
        room_x1_in_crop = img_x1 - crop_x1
        room_y1_in_crop = img_y1 - crop_y1

        # 크롭된 이미지에 빨간색 박스 그리기
        draw = ImageDraw.Draw(cropped_image)
        draw.rectangle(
            [
                room_x_in_crop - 5,
                room_y_in_crop - 5,
                room_x1_in_crop + 5,
                room_y1_in_crop + 5,
            ],
            outline="red",
            width=3,
        )
        draw.text(
            (room_x1_in_crop + 10, room_y_in_crop - 20), f"{room_name}", fill="red"
        )

        # 디버그 이미지 저장 (PDF 타입별로 다른 이름)
        os.makedirs("data/drawings", exist_ok=True)
        debug_filename = f"data/drawings/debug_cropped_{pdf_type}_{room_name}.png"
        cropped_image.save(debug_filename)
        print(f"   디버그 이미지 저장: {debug_filename}")

        return cropped_image

    def encode_image_to_base64(self, image: Image.Image) -> str:
        """PIL 이미지를 base64로 인코딩"""
        buffer = io.BytesIO()
        image.save(buffer, format="PNG")
        img_bytes = buffer.getvalue()
        return base64.b64encode(img_bytes).decode("utf-8")

    async def analyze_document_with_di(self, file_path: str) -> Dict:
        """Azure Document Intelligence로 문서 분석"""
        try:
            with open(file_path, "rb") as f:
                file_content = f.read()

            # 파일 확장자에 따라 content_type 설정
            if file_path.lower().endswith(".pdf"):
                content_type = "application/pdf"
            elif file_path.lower().endswith(".png"):
                content_type = "image/png"
            elif file_path.lower().endswith(".jpg") or file_path.lower().endswith(
                ".jpeg"
            ):
                content_type = "image/jpeg"
            else:
                content_type = "application/octet-stream"

            poller = self.di_client.begin_analyze_document(
                "prebuilt-layout", file_content, content_type=content_type
            )
            result = poller.result()
            return result
        except Exception as e:
            print(f"DI 분석 오류: {e}")
            return None

    async def process_pdf_with_pdfplumber(self, pdf_path: str) -> str:
        """pdfplumber를 사용하여 PDF에서 텍스트와 테이블 추출"""
        try:
            print(f"pdfplumber로 PDF 분석 중: {pdf_path}")

            with pdfplumber.open(pdf_path) as pdf:
                all_text = ""
                all_tables = []

                for page_num, page in enumerate(pdf.pages):
                    # 텍스트 추출
                    page_text = page.extract_text()
                    if page_text:
                        all_text += f"\n=== 페이지 {page_num + 1} ===\n"
                        all_text += page_text

                    # 테이블 추출
                    tables = page.extract_tables()
                    if tables:
                        for table_num, table in enumerate(tables):
                            table_data = {
                                "page": page_num + 1,
                                "table": table_num + 1,
                                "data": table,
                            }
                            all_tables.append(table_data)

                print(f"pdfplumber 텍스트 추출 완료: {len(all_text)} 문자")
                print(f"pdfplumber 테이블 추출 완료: {len(all_tables)}개 테이블")

                # 텍스트와 테이블 결합
                combined_content = self._combine_pdfplumber_text_and_tables(
                    all_text, all_tables
                )
                return combined_content

        except Exception as e:
            print(f"pdfplumber 텍스트 추출 중 오류: {e}")
            return ""

    def _combine_pdfplumber_text_and_tables(self, content: str, tables: list) -> str:
        """pdfplumber로 추출한 텍스트와 테이블 정보를 결합"""
        combined = content

        if tables:
            combined += "\n\n=== pdfplumber 테이블 정보 ===\n"
            for i, table_data in enumerate(tables):
                combined += f"\n테이블 {i + 1} (페이지 {table_data['page']}):\n"
                for row in table_data["data"]:
                    if row:
                        combined += " | ".join([cell or "" for cell in row]) + "\n"

            # 테이블 검색을 위한 추가 정보
            combined += "\n\n=== pdfplumber 테이블 검색 ===\n"
            for table_data in tables:
                for row in table_data["data"]:
                    if row:
                        combined += " ".join([cell or "" for cell in row]) + "\n"

        return combined

    async def upload_file_to_blob(
        self, file_path: str, file_extension: str = None
    ) -> str:
        """로컬 파일을 Azure Blob Storage에 업로드하고 전체 경로 반환"""
        try:
            print(f"Azure Blob Storage에 파일 업로드 중: {file_path}")

            # 파일 확장자 결정
            if not file_extension:
                file_extension = os.path.splitext(file_path)[1].lower()
                if not file_extension:
                    file_extension = ".bin"  # 기본 확장자

            # 랜덤 파일명 생성
            random_filename = f"{uuid.uuid4()}{file_extension}"

            # Blob 클라이언트 생성
            blob_client = self.blob_service_client.get_blob_client(
                container=self.container_name, blob=random_filename
            )

            # 파일 업로드
            with open(file_path, "rb") as data:
                blob_client.upload_blob(data, overwrite=True)

            # 전체 Blob URL 생성
            blob_url = f"https://{self.storage_account_name}.blob.core.windows.net/{self.container_name}/{random_filename}"

            print(f"   업로드 완료: {blob_url}")
            return blob_url

        except Exception as e:
            print(f"   Blob 업로드 오류: {e}")
            return None

    async def upload_bytes_to_blob(
        self, file_bytes: bytes, file_extension: str = ".bin"
    ) -> str:
        """바이트 데이터를 Azure Blob Storage에 업로드하고 전체 경로 반환"""
        try:
            print("Azure Blob Storage에 바이트 데이터 업로드 중...")

            # 랜덤 파일명 생성
            random_filename = f"{uuid.uuid4()}{file_extension}"

            # Blob 클라이언트 생성
            blob_client = self.blob_service_client.get_blob_client(
                container=self.container_name, blob=random_filename
            )

            # 바이트 데이터 업로드
            blob_client.upload_blob(file_bytes, overwrite=True)

            # 전체 Blob URL 생성
            blob_url = f"https://{self.storage_account_name}.blob.core.windows.net/{self.container_name}/{random_filename}"

            print(f"   업로드 완료: {blob_url}")
            return blob_url

        except Exception as e:
            print(f"   Blob 업로드 오류: {e}")
            return None

    async def upload_image_to_blob(
        self, image: Image.Image, file_extension: str = ".png"
    ) -> str:
        """PIL 이미지를 Azure Blob Storage에 업로드하고 전체 경로 반환"""
        try:
            print("Azure Blob Storage에 이미지 업로드 중...")

            # 이미지를 바이트로 변환
            buffer = io.BytesIO()
            image.save(
                buffer, format=file_extension[1:].upper()
            )  # 확장자에서 포맷 추출
            file_bytes = buffer.getvalue()

            # 바이트 데이터 업로드
            return await self.upload_bytes_to_blob(file_bytes, file_extension)

        except Exception as e:
            print(f"   이미지 Blob 업로드 오류: {e}")
            return None
