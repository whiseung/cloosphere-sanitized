# 상품·매장 KG — 테스트 질문 체크리스트

> **KG**: 상품·매장 KG (`a0d15e66-670a-4a19-8ed0-3212fa818fd8`)
> **글로서리**: 상품·매장 용어사전 (20개 비즈니스 용어 + 50개 상품 dimension entity, 44개 동의어)
> **DB**: 제조사 DW Snowflake (14테이블, 117컬럼)
> **KB**: 상품·매장 업무 지식 (4문서: 상품마스터관리, 매장운영관리, 상품매장_매출분석, 상품_가격전략)
> **현황**: 251노드(term 64, column 117, doc_entity 53, table 14, concept 3), 331엣지

### 실제 DB 데이터 현황
| 테이블 | 행 수 | 특이사항 |
|--------|-------|---------|
| DIM_PRODUCT | 50 | 상품1~50, 브랜드0~4 (각 10개), 전부 식품/BOX, IS_COLD_CHAIN 전부 'N' |
| DIM_STORE | 20 | 매장1~20, 전부 오프라인매장/서울 |
| FACT_SALES_ORDER_ITEM | 1,000 | **STORE_KEY 전부 NULL** (매장 JOIN 불가) |
| FACT_RETURN | 1,000 | |
| FACT_SHIPMENT | 1,000 | |
| FACT_INVENTORY_DAILY | 1,000 | |
| 총매출 | 16,692,838 | 순매출 15,074,908 / 이익 4,522,947 / 할인 1,617,930 |

### KG 엣지 현황
| 엣지 타입 | 수 | 비고 |
|-----------|-----|------|
| belongs_to | 117 | column→table |
| related_to | 102 | LLM 추출 교차 연결 |
| synonym_of | 88 | 양방향 동의어 |
| broader_than | 20 | concept→term |
| depends_on | 3 | |
| uses | 1 | |
| **maps_to** | **0** | 미큐레이션 — resolve_term이 컬럼 매핑 불가 |
| **foreign_key** | **0** | AGE에 FK 없음 — find_related_tables 불가 |

---

## 1. 용어 해소 + 컨텍스트 탐색

> `kg_resolve_term`은 maps_to 엣지가 없어 항상 "(no mappings curated yet)" 반환.
> 에이전트가 `kg_explore_context`로 fallback하여 용어 설명에서 컬럼 정보를 추출하는지가 핵심.

| # | 질문 | 예상 도구 호출 | 예상 답변 (정답) |
|---|------|---------------|-----------------|
| 1-1 | "단가가 어떤 컬럼이야?" | `kg_resolve_term("단가")` → no mappings → `kg_explore_context("단가")` | **DIM_PRODUCT.UNIT_PRICE** (용어 desc: "상품 1개의 판매 가격. DIM_PRODUCT.UNIT_PRICE 컬럼에 기록된다") |
| 1-2 | "판매가 컬럼 알려줘" | `kg_resolve_term("판매가")` → 동의어 매칭 → no mappings → `kg_explore_context("단가")` | **DIM_PRODUCT.UNIT_PRICE** (판매가 = 정가 = 단가의 동의어) |
| 1-3 | "매입가는 DB에서 어떤 컬럼이지?" | `kg_resolve_term("매입가")` → 동의어 "원가" → `kg_explore_context("원가")` | **DIM_PRODUCT.UNIT_COST** (원가 desc: "DIM_PRODUCT.UNIT_COST 컬럼에 저장된다") |
| 1-4 | "마진율을 구하려면 어떤 컬럼을 봐야 해?" | `kg_resolve_term("마진율")` → 동의어 "이익률" → `kg_explore_context("이익률")` | **PROFIT_AMT / GROSS_SALES_AMT × 100** (이익률 desc: "PROFIT_AMOUNT / TOTAL_AMOUNT × 100") |
| 1-5 | "냉장상품은 어떻게 구분해?" | `kg_resolve_term("냉장상품")` → `kg_explore_context("냉장상품")` | **DIM_PRODUCT.IS_COLD_CHAIN** 컬럼 (현재 데이터에서는 전부 'N') |
| 1-6 | "Cold Chain Product 컬럼이 뭐야?" | `kg_resolve_term("Cold Chain Product")` → 영문 동의어 "냉장상품" | **DIM_PRODUCT.IS_COLD_CHAIN** |
| 1-7 | "SKU가 뭐야?" | `kg_explore_context("SKU")` | **DIM_PRODUCT.PRODUCT_ID** (desc: "Stock Keeping Unit. 재고 관리의 최소 단위") |
| 1-8 | "매장별매출은 어떻게 구해?" | `kg_explore_context("매장별매출")` | **FACT_SALES_ORDER_ITEM을 STORE_KEY 기준으로 집계** (단, 현재 STORE_KEY가 NULL) |

---

## 2. 컨텍스트 탐색 (kg_explore_context)

| # | 질문 | 예상 도구 호출 | 예상 답변 (정답) |
|---|------|---------------|-----------------|
| 2-1 | "브랜드에 대해 알려줘" | `kg_explore_context("브랜드")` | term "브랜드" — DIM_PRODUCT.BRAND_NAME. 동의어: Brand, 제조사. 관련: 브랜드별 마진 분석, PB, 매출이익, 이익률. concept "상품" 하위. |
| 2-2 | "DIM_STORE 테이블 구조 알려줘" | `kg_explore_context("DIM_STORE")` | **6컬럼**: STORE_KEY(NUMBER), STORE_ID(TEXT), STORE_NAME(TEXT), STORE_TYPE(TEXT), REGION_NAME(TEXT), CITY_NAME(TEXT). 관련: FACT_SALES_ORDER_ITEM, DIM_PRODUCT |
| 2-3 | "카테고리 체계가 어떻게 돼?" | `kg_explore_context("카테고리")` | **3단계**: DIM_PRODUCT.CATEGORY_LV1, CATEGORY_LV2, CATEGORY_LV3. 동의어: Category, 상품분류. 관련 doc_entity: CATEGORY_LV1~3, 상품팀 |
| 2-4 | "상품회전율이란?" | `kg_explore_context("상품회전율")` | **매출원가 / 평균재고금액**. 동의어: Inventory Turnover, 재고회전율. concept "KPI" 하위. |
| 2-5 | "DIM_PRODUCT 테이블은 뭐랑 연결돼 있어?" | `kg_explore_context("DIM_PRODUCT")` | related_to: **FACT_SALES_ORDER_ITEM, FACT_RETURN, FACT_INVENTORY_DAILY, FACT_SHIPMENT, DIM_STORE**. 11개 컬럼 소속. |
| 2-6 | "FACT_SALES_ORDER_ITEM 구조 알려줘" | `kg_explore_context("FACT_SALES_ORDER_ITEM")` | **15컬럼**: ORDER_ITEM_KEY, ORDER_ID, ORDER_LINE_NO, ORDER_DATE_KEY, CUSTOMER_KEY, PRODUCT_KEY, STORE_KEY, CHANNEL_KEY, PROMOTION_KEY, ORDER_QTY, GROSS_SALES_AMT, NET_SALES_AMT, DISCOUNT_AMT, COST_AMT, PROFIT_AMT |

---

## 3. 시맨틱 검색 (kg_search_concepts)

| # | 질문 | 예상 도구 호출 | 예상 답변 (정답) |
|---|------|---------------|-----------------|
| 3-1 | "재고 관련 용어 뭐가 있어?" | `kg_search_concepts("재고")` | 상품회전율, FACT_INVENTORY_DAILY, 과잉재고 리스크 등 |
| 3-2 | "가격이랑 관련된 것들 찾아줘" | `kg_search_concepts("가격")` | 단가(UNIT_PRICE), 원가(UNIT_COST), 실판매가, Volume Discount 등 |
| 3-3 | "물류 배송 관련 테이블 찾아줘" | `kg_search_concepts("물류 배송", node_types=["table"])` | FACT_SHIPMENT, DIM_CARRIER, DIM_WAREHOUSE |
| 3-4 | "KPI 관련 항목들 보여줘" | `kg_search_concepts("KPI 지표")` | concept "KPI", 매출이익, 이익률, 상품회전율 |

---

## 4. 이웃 탐색 (kg_neighbors)

> search_concepts로 node_id를 먼저 확보한 후 사용.

| # | 질문 | 예상 도구 호출 | 예상 답변 (정답) |
|---|------|---------------|-----------------|
| 4-1 | "'상품' 카테고리에 속한 용어 전부 알려줘" | `kg_search_concepts("상품")` → concept "상품" ID 확보 → `kg_neighbors(id, hops=1, edge_types=["broader_than"])` | **9건**: SKU, 카테고리, 원가, 상품키, 브랜드, 냉장상품, 단가, 패키지유형, 상품명 |
| 4-2 | "'매장' 개념의 하위 용어들은?" | concept "매장" → `kg_neighbors(...)` | **8건**: 직영점, 매장유형, 매장지역, 가맹점, 매장명, 매장키, 매장별매출, 점포수 |
| 4-3 | "단가의 동의어 뭐가 있어?" | term "단가" → `kg_neighbors(id, edge_types=["synonym_of"])` | **3개**: Unit Price, 판매가, 정가 |
| 4-4 | "KPI에는 뭐가 있어?" | concept "KPI" → `kg_neighbors(...)` | **3건**: 매출이익, 이익률, 상품회전율 |

---

## 5. 데이터 조회 (kg_explore_context → kg_fetch_data)

> explore_context로 스키마 파악 → fetch_data로 실제 SQL 실행.

| # | 질문 | 예상 도구 호출 | 예상 정답 (실제 DB 결과) |
|---|------|---------------|------------------------|
| 5-1 | "브랜드별 매출 보여줘" | `kg_explore_context("브랜드")` → `kg_fetch_data("SELECT p.BRAND_NAME, SUM(f.GROSS_SALES_AMT) ... GROUP BY ... ORDER BY ... DESC")` | **브랜드4: 4,039,880 / 브랜드0: 3,336,020 / 브랜드2: 3,239,173 / 브랜드1: 3,192,674 / 브랜드3: 2,885,091** |
| 5-2 | "브랜드별 이익률 비교해줘" | `kg_explore_context("이익률")` → `kg_fetch_data("SELECT BRAND_NAME, SUM(PROFIT_AMT)/SUM(GROSS_SALES_AMT)*100 ...")` | 브랜드별 이익률 % (대략 27% 내외) |
| 5-3 | "상품 몇 개야?" | `kg_fetch_data("SELECT COUNT(*) FROM DIM_PRODUCT")` | **50개** |
| 5-4 | "매장 몇 개야?" | `kg_fetch_data("SELECT COUNT(*) FROM DIM_STORE")` | **20개** |
| 5-5 | "총매출 합계 알려줘" | `kg_explore_context("총매출")` 또는 `kg_explore_context("매출이익")` → `kg_fetch_data("SELECT SUM(GROSS_SALES_AMT) FROM FACT_SALES_ORDER_ITEM")` | **16,692,838** |
| 5-6 | "할인 합계 얼마야?" | `kg_fetch_data("SELECT SUM(DISCOUNT_AMT) FROM FACT_SALES_ORDER_ITEM")` | **1,617,930** |
| 5-7 | "가장 비싼 상품 TOP 5" | `kg_explore_context("단가")` → `kg_fetch_data("SELECT PRODUCT_NAME, UNIT_PRICE FROM DIM_PRODUCT ORDER BY UNIT_PRICE DESC LIMIT 5")` | 상품별 UNIT_PRICE 상위 5개 |
| 5-8 | "프로모션 유형별 건수" | `kg_explore_context("DIM_PROMOTION")` → `kg_fetch_data("SELECT PROMOTION_TYPE, COUNT(*) FROM DIM_PROMOTION GROUP BY PROMOTION_TYPE")` | **시즌행사 8, 쿠폰 8, 묶음할인 3, 없음 1** |
| 5-9 | "창고별 온도존 현황 알려줘" | `kg_explore_context("DIM_WAREHOUSE")` → `kg_fetch_data("SELECT TEMP_ZONE, COUNT(*) FROM DIM_WAREHOUSE GROUP BY TEMP_ZONE")` | 냉동/상온 분포 |

---

## 6. 문서 검색 (kg_fetch_document)

> 규정, 정책, 업무 가이드라인 질문은 fetch_document로 원문 청크 반환.

| # | 질문 | 예상 도구 호출 | 예상 답변 (정답 — KB 원문 기반) |
|---|------|---------------|-------------------------------|
| 6-1 | "냉장상품 관리 규정이 어떻게 돼?" | `kg_fetch_document("냉장상품 관리 규정")` | IS_COLD_CHAIN=TRUE 상품은 콜드체인 물류 적용, TEMP_ZONE 적합 창고에만 보관 (01_상품마스터관리.md) |
| 6-2 | "브랜드별 마진 분석 방법은?" | `kg_fetch_document("브랜드별 마진 분석")` | 고마진 → 프리미엄 진열/직영점 배치, 저마진 → 볼륨 판매/번들, PB → 원가 통제 (04_상품_가격전략.md) |
| 6-3 | "매장유형별 가격 정책 알려줘" | `kg_fetch_document("매장유형별 가격 정책")` | 직영점: 정가+멤버십할인, 가맹점: 자체 프로모션 허용, 아울렛: 30~70% 할인, 백화점: 정가/소폭할인 (04_상품_가격전략.md) |
| 6-4 | "PB 상품이 뭐야?" | `kg_explore_context("PB")` → `kg_fetch_document("PB Private Brand")` | PB(Private Brand) = 자사 브랜드 상품. 별도 구분 관리, 원가 통제 가능하여 경쟁력 있는 가격 설정 |
| 6-5 | "카테고리 변경 절차가 어떻게 돼?" | `kg_fetch_document("카테고리 변경 절차")` | 반드시 **상품팀 승인** 필요, 변경 이력 관리 (01_상품마스터관리.md) |
| 6-6 | "상품회전율이 낮은 매장은 어떻게 해?" | `kg_fetch_document("상품회전율 매장")` | 과잉재고 리스크, **MD(머천다이저) 개입** 필요 (03_상품매장_매출분석.md) |

---

## 7. 복합 질의 (Multi-tool Workflow)

| # | 질문 | 예상 도구 호출 순서 | 예상 정답 |
|---|------|-------------------|----------|
| 7-1 | "브랜드별 매출이익 TOP 3과, 마진 분석 방법도 알려줘" | ① `kg_explore_context("매출이익")` → PROFIT_AMT 파악 ② `kg_fetch_data("SELECT BRAND_NAME, SUM(PROFIT_AMT) ... TOP 3")` ③ `kg_fetch_document("브랜드별 마진 분석")` | 데이터: 브랜드4 > 브랜드0 > 브랜드2 순 이익 + 문서: 고마진/저마진 전략 설명 |
| 7-2 | "카테고리 체계 설명해주고 카테고리별 상품 수도 알려줘" | ① `kg_explore_context("카테고리")` → LV1/LV2/LV3 구조 파악 ② `kg_fetch_data("SELECT CATEGORY_LV1, COUNT(*) ...")` | 3단계 분류 설명 + 실제: 식품 50개 (현재 1개 카테고리만 존재) |
| 7-3 | "단가가 높은 상품 5개 보여주고, 가격 전략도 설명해줘" | ① `kg_explore_context("단가")` → UNIT_PRICE ② `kg_fetch_data("SELECT PRODUCT_NAME, UNIT_PRICE ... ORDER BY UNIT_PRICE DESC LIMIT 5")` ③ `kg_fetch_document("가격 전략")` | TOP 5 상품 목록 + 매장유형별 가격 정책 문서 |
| 7-4 | "프로모션 유형별 매출 합계 알려줘" | ① `kg_explore_context("DIM_PROMOTION")` → PROMOTION_KEY, PROMOTION_TYPE ② `kg_fetch_data("SELECT pr.PROMOTION_TYPE, SUM(f.GROSS_SALES_AMT) FROM FACT_SALES_ORDER_ITEM f JOIN DIM_PROMOTION pr ON f.PROMOTION_KEY = pr.PROMOTION_KEY GROUP BY pr.PROMOTION_TYPE")` | 프로모션 유형별 매출 합계 |
| 7-5 | "원가가 단가보다 높은 상품 있어?" | ① `kg_explore_context("원가")` + `kg_explore_context("단가")` → UNIT_COST, UNIT_PRICE ② `kg_fetch_data("SELECT PRODUCT_NAME, UNIT_PRICE, UNIT_COST FROM DIM_PRODUCT WHERE UNIT_COST > UNIT_PRICE")` | 역마진 상품 목록 (있으면 목록, 없으면 "없다") |

---

## 8. 동의어 해소 테스트

> 동의어로 질문했을 때 원래 용어를 경유하여 올바른 컬럼/정보에 도달하는지.

| # | 질문 (동의어 사용) | 해소 경로 | 최종 정답 |
|---|-------------------|----------|----------|
| 8-1 | "제조사별 매출 보여줘" | 제조사 → 브랜드 → BRAND_NAME | `SELECT BRAND_NAME, SUM(GROSS_SALES_AMT) ...` |
| 8-2 | "상품분류별 원가 평균" | 상품분류 → 카테고리 → CATEGORY_LV1 | `SELECT CATEGORY_LV1, AVG(UNIT_COST) ...` |
| 8-3 | "점포유형이 뭐가 있어?" | 점포유형 → 매장유형 → STORE_TYPE | `SELECT DISTINCT STORE_TYPE FROM DIM_STORE` → **오프라인매장** (1종) |
| 8-4 | "매출총이익 합계" | 매출총이익 → 매출이익 → PROFIT_AMT | `SELECT SUM(PROFIT_AMT) FROM FACT_SALES_ORDER_ITEM` → **4,522,947** |
| 8-5 | "포장형태별 상품 수" | 포장형태 → 패키지유형 → PACKAGE_TYPE | `SELECT PACKAGE_TYPE, COUNT(*) ...` → **BOX: 50** |
| 8-6 | "Gross Profit 계산법은?" | Gross Profit → 매출이익 | TOTAL_AMOUNT - COST_AMOUNT (용어 설명 기반) |
| 8-7 | "Inventory Turnover가 뭐야?" | Inventory Turnover → 상품회전율 | 매출원가 / 평균재고금액 |
| 8-8 | "점포매출 보여줘" | 점포매출 → 매장별매출 | FACT_SALES_ORDER_ITEM을 STORE_KEY로 집계 (단, STORE_KEY NULL) |

---

## 9. Edge Case / 네거티브 테스트

| # | 질문 | 예상 동작 | 예상 답변 |
|---|------|----------|----------|
| 9-1 | "고객등급별 매출 보여줘" | KG에 고객 관련 용어 없음. explore_context로 DIM_CUSTOMER 테이블 발견 가능 → MEMBER_GRADE 컬럼은 있지만 **FACT_SALES의 STORE_KEY가 NULL이므로 JOIN 어려울 수 있음** | DIM_CUSTOMER.MEMBER_GRADE 컬럼 존재는 알려주되, CUSTOMER_KEY 기반 JOIN 시도 |
| 9-2 | "상품을 삭제해줘" | `kg_fetch_data("DELETE FROM ...")` 시도 | **"Only SELECT queries are allowed."** 에러 |
| 9-3 | "없는용어XYZ" | `kg_resolve_term("없는용어XYZ")` | **"No term matching ... found in knowledge graph(s)."** |
| 9-4 | "DIM_PRODUCT 전체 데이터 보여줘" | `kg_fetch_data("SELECT * FROM DIM_PRODUCT")` | LIMIT 100 자동 주입, 50행 반환 (50 < 100이므로 전부 반환) |
| 9-5 | "매장별 매출을 보여줘" (STORE_KEY NULL 상황) | explore_context → STORE_KEY로 JOIN 시도 → **결과 0행** | 에이전트가 "매장 키가 NULL이라 조인 결과가 없다"고 안내해야 함 |

---

## 10. 도구 미작동 확인 (현재 제한사항)

> 현재 KG에 maps_to, foreign_key 엣지가 없어 일부 도구가 제한적.

| 도구 | 현재 상태 | 대안 |
|------|----------|------|
| `kg_resolve_term` | 항상 "no mappings curated yet" | `kg_explore_context`로 용어 설명에서 컬럼 정보 추출 |
| `kg_find_related_tables` | 항상 "not found" (FK 엣지 없음) | `kg_explore_context`로 related_to 엣지 기반 관련 테이블 확인 |
| `kg_fetch_data` | 정상 (Snowflake 접속 OK) | — |
| `kg_fetch_document` | 정상 (Azure Search 접속 OK) | — |
| `kg_explore_context` | 정상 (AGE Cypher) | — |
| `kg_search_concepts` | 정상 (벡터 검색) | — |
| `kg_neighbors` | 정상 (AGE Cypher) | — |

---

## 평가 기준

| 항목 | 설명 | 가중치 |
|------|------|--------|
| **도구 선택** | 질문 유형에 맞는 올바른 도구를 호출했는가? | ★★★ |
| **동의어 해소** | 동의어로 질문해도 원래 용어/컬럼으로 정확히 매핑했는가? | ★★★ |
| **SQL 정확성** | 올바른 테이블/컬럼명, JOIN 조건, WHERE 필터를 사용했는가? | ★★★ |
| **워크플로우 준수** | explore_context → fetch_data 순서를 지켰는가? (SQL만 보여주지 않고 실행) | ★★ |
| **fallback 능력** | resolve_term 실패 시 explore_context로 적절히 전환했는가? | ★★ |
| **문서 vs 데이터 구분** | 규정/정책 → fetch_document, 수치 → fetch_data 구분 | ★★ |
| **에러 핸들링** | NULL 데이터, 0행 결과 등 예외 상황을 사용자에게 명확히 설명했는가? | ★ |
