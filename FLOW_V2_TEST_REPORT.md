# Agent Flow V2 — 종합 E2E 검증 리포트

검증 시각: 2026-04-04
대상 플로우: 10개 (AI 자동 생성)

---

## 1. 고객 문의 부서 분류 및 전문가 답변 플로우
- **ID**: `auto-5027d54a`
- **노드**: 8개 | **엣지**: 10개

### 노드 구성
| ID | Type | Label | Config 요약 |
|---|---|---|---|
| start | flowInput | 문의 접수 |  |
| blocked_word_guard | guardrail | 금칙어 차단 | resourceId=12336abc-d269-49ee-b74e-f9203a1740be |
| dept_router | router | 부서 분류 | routes=['sales', 'tech', 'general'] |
| block_message | transform | 차단 안내 | template=입력하신 문의에는 처리할 수 없는 금칙어가 포함되어 있습니다. 금칙어를 제거한 뒤 다시 문... |
| sales_expert | model | 영업 전문가 답변 | model=gpt-5.4, prompt=당신은 영업 부서 전문 상담원입니다. 고객 문의를 읽고 영업 관점에서 정확하고 친절하게 답... |
| tech_expert | model | 기술 전문가 답변 | model=gpt-5.4, prompt=당신은 기술 부서 전문 상담원입니다. 고객 문의를 읽고 기술 지원 관점에서 정확하고 친절하... |
| general_expert | model | 일반 문의 답변 | model=gpt-5.4, prompt=당신은 일반 고객문의 전문 상담원입니다. 고객 문의를 읽고 일반 안내 관점에서 정확하고 친... |
| end | flowOutput | 응답 전송 |  |

### 엣지 연결
| Source | Handle | Target |
|---|---|---|
| start | output | blocked_word_guard |
| blocked_word_guard | pass | dept_router |
| blocked_word_guard | block | block_message |
| dept_router | sales | sales_expert |
| dept_router | tech | tech_expert |
| dept_router | general | general_expert |
| sales_expert | output | end |
| tech_expert | output | end |
| general_expert | output | end |
| block_message | output | end |

### 검증 체크리스트
| 항목 | 결과 | 상세 |
|---|---|---|
| Input 노드 존재 | ✅ | {'start'} |
| Output 노드 존재 | ✅ | {'end'} |
| 모든 노드 incoming 연결 | ✅ | OK |
| 모든 노드 outgoing 연결 | ✅ | OK |
| Guardrail 'blocked_word_guard' pass/block | ✅ | pass=True, block=True |
| Router 'dept_router' 모든 라우트 연결 | ✅ | routes={'tech', 'general', 'sales'}, handles={'tech', 'general', 'sales'} |
| Model 'sales_expert' 프롬프트 | ✅ | model=gpt-5.4, len=156 |
| Model 'tech_expert' 프롬프트 | ✅ | model=gpt-5.4, len=152 |
| Model 'general_expert' 프롬프트 | ✅ | model=gpt-5.4, len=150 |
| Guardrail 'blocked_word_guard' 리소스 | ✅ | resourceId=12336abc-d269-49ee-b74e-f9203a1740be |

### 실행 테스트
| 입력 | 결과 | 응답 요약 |
|---|---|---|
| 기본 테스트 | ❌ | HTTP Error 400: Bad Request |

### AI 대화 이력 (Human-in-the-Loop)
| Turn | Role | Content |
|---|---|---|
| 1 | user | 고객 문의를 gpt-5.4로 영업/기술/일반 3개 부서로 분류하는 라우터 플로우. 각 부서별 gpt-5.4 전문가 모델이 답변. 가드레일은 금칙어 차단(ID: 12336abc-d2 |
| 2 | assistant | 플로우 생성이 완료되었습니다.

구성 요약:
- 시작: 고객 문의 접수
- 가드레일: 금칙어 차단 `12336abc-d269-49ee-b74e-f9203a1740be`
- 라우터: |

---

## 2. 종합 고객 지원 플로우
- **ID**: `auto-fab88916`
- **노드**: 9개 | **엣지**: 10개

### 노드 구성
| ID | Type | Label | Config 요약 |
|---|---|---|---|
| start | flowInput | 고객 문의 접수 |  |
| pii_guard | guardrail | 개인정보보호 검사 | resourceId=8deec695-a624-4bdf-a901-f8a0656ac9a2 |
| term_lookup | glossary | 용어 조회 | resourceId=a1b4693e-f495-4b8c-af5d-5cbc70f475b1 |
| biztech_classifier | model | 기술/비즈니스 분류 | model=gpt-5.4, prompt=당신은 고객 문의를 분류하는 분류기입니다. 입력된 문의와 용어 조회 결과를 바탕으로 문의가... |
| is_technical | condition | 기술 문의 여부 | contains: technical |
| tech_expert | model | 기술 전문가 답변 | model=gpt-5.4, prompt=당신은 기술 고객지원 전문가입니다. 고객 문의 원문과 용어 조회 결과를 참고하여 정확하고 ... |
| business_agent | agent | 비즈니스 답변 | resourceId=cloosphere-1774431907026 |
| blocked_notice | transform | 차단 안내 | template=입력 내용에 개인정보 또는 민감정보가 포함되어 있어 요청을 바로 처리할 수 없습니다.
개인... |
| end | flowOutput | 고객 응답 |  |

### 엣지 연결
| Source | Handle | Target |
|---|---|---|
| start | output | pii_guard |
| pii_guard | pass | term_lookup |
| term_lookup | output | biztech_classifier |
| biztech_classifier | output | is_technical |
| is_technical | true | tech_expert |
| is_technical | false | business_agent |
| pii_guard | block | blocked_notice |
| tech_expert | output | end |
| business_agent | output | end |
| blocked_notice | output | end |

### 검증 체크리스트
| 항목 | 결과 | 상세 |
|---|---|---|
| Input 노드 존재 | ✅ | {'start'} |
| Output 노드 존재 | ✅ | {'end'} |
| 모든 노드 incoming 연결 | ✅ | OK |
| 모든 노드 outgoing 연결 | ✅ | OK |
| Guardrail 'pii_guard' pass/block | ✅ | pass=True, block=True |
| Condition 'is_technical' true/false | ✅ | true=True, false=True |
| Model 'biztech_classifier' 프롬프트 | ✅ | model=gpt-5.4, len=142 |
| Model 'tech_expert' 프롬프트 | ✅ | model=gpt-5.4, len=128 |
| Agent 'business_agent' 리소스 | ✅ | resourceId=cloosphere-1774431907026 |
| Guardrail 'pii_guard' 리소스 | ✅ | resourceId=8deec695-a624-4bdf-a901-f8a0656ac9a2 |
| Glossary 'term_lookup' 리소스 | ✅ | resourceId=a1b4693e-f495-4b8c-af5d-5cbc70f475b1 |

### 실행 테스트
| 입력 | 결과 | 응답 요약 |
|---|---|---|
| 기술 질의: K8s 환경에서 서비스 장애가 발생했습니다... | ✅ | 안녕하세요. 무엇을 기술적으로 도와드릴까요?

문제를 빠르게 해결할 수 있도록 아래 정보를 보내주세요:
- 제품/서비스명
- 발생한 증상 또는 ... |

### AI 대화 이력 (Human-in-the-Loop)
| Turn | Role | Content |
|---|---|---|
| 1 | user | 종합 고객 지원 플로우. 1)개인정보보호 가드레일(8deec695-a624-4bdf-a901-f8a0656ac9a2)로 PII검사. 2)ClooSphere 용어집(a1b4693e |
| 2 | assistant | 완료했습니다.  
플로우명: **종합 고객 지원 플로우**

구성:
1. **고객 문의 접수**
2. **개인정보보호 검사** (`8deec695-a624-4bdf-a901-f8a |

---

## 3. 사내 규정 상담 플로우
- **ID**: `auto-18e0ed98`
- **노드**: 8개 | **엣지**: 10개

### 노드 구성
| ID | Type | Label | Config 요약 |
|---|---|---|---|
| start | flowInput | 상담 접수 |  |
| blocked_word_guard | guardrail | 금칙어 필터 | resourceId=bf4e8030-7f11-445c-bc62-204a0984a3b5 |
| topic_router | router | 상담 유형 분류 | routes=['hr', 'it', 'general'] |
| blocked_notice | transform | 차단 안내 | template=입력 내용에 부적절한 표현이 포함되어 있어 상담을 진행할 수 없습니다. 표현을 수정한 뒤 ... |
| hr_agent | agent | HR 상담 에이전트 | resourceId=hr-agentgpt52test |
| it_expert | model | IT 전문가 | model=gpt-5.4, prompt=당신은 사내 IT 전문 상담사입니다. 사용자의 질문을 분석하여 IT 인프라, 계정, 보안,... |
| general_agent | agent | 일반 상담 | resourceId=cloocusgeneralmodel |
| end | flowOutput | 상담 응답 |  |

### 엣지 연결
| Source | Handle | Target |
|---|---|---|
| start | output | blocked_word_guard |
| blocked_word_guard | pass | topic_router |
| blocked_word_guard | block | blocked_notice |
| topic_router | hr | hr_agent |
| topic_router | it | it_expert |
| topic_router | general | general_agent |
| blocked_notice | output | end |
| hr_agent | output | end |
| it_expert | output | end |
| general_agent | output | end |

### 검증 체크리스트
| 항목 | 결과 | 상세 |
|---|---|---|
| Input 노드 존재 | ✅ | {'start'} |
| Output 노드 존재 | ✅ | {'end'} |
| 모든 노드 incoming 연결 | ✅ | OK |
| 모든 노드 outgoing 연결 | ✅ | OK |
| Guardrail 'blocked_word_guard' pass/block | ✅ | pass=True, block=True |
| Router 'topic_router' 모든 라우트 연결 | ✅ | routes={'general', 'hr', 'it'}, handles={'general', 'hr', 'it'} |
| Model 'it_expert' 프롬프트 | ✅ | model=gpt-5.4, len=193 |
| Agent 'hr_agent' 리소스 | ✅ | resourceId=hr-agentgpt52test |
| Agent 'general_agent' 리소스 | ✅ | resourceId=cloocusgeneralmodel |
| Guardrail 'blocked_word_guard' 리소스 | ✅ | resourceId=bf4e8030-7f11-445c-bc62-204a0984a3b5 |

### 실행 테스트
| 입력 | 결과 | 응답 요약 |
|---|---|---|
| IT 질의: 사내 VPN 접속 방법을 알려주세요... | ✅ | 사내 VPN 접속 방법은 회사마다 다르지만, 일반적으로 아래 순서로 진행합니다.

### 1. 준비사항 확인
- 회사에서 제공한 **VPN 주소... |

### AI 대화 이력 (Human-in-the-Loop)
| Turn | Role | Content |
|---|---|---|
| 1 | user | 사내 규정 상담 플로우. 금칙어 필터 가드레일(bf4e8030-7f11-445c-bc62-204a0984a3b5) 사용. 통과후 gpt-5.4로 HR/IT/일반 분류. 라우터로 3 |
| 2 | assistant | 완료했습니다.

구성된 플로우:
- 시작: 상담 접수
- 가드레일: 금칙어 필터 `bf4e8030-7f11-445c-bc62-204a0984a3b5`
  - 통과 → 상담 유형 분 |

---

## 4. 다관점 분석 플로우
- **ID**: `auto-0349fef1`
- **노드**: 6개 | **엣지**: 7개

### 노드 구성
| ID | Type | Label | Config 요약 |
|---|---|---|---|
| start | flowInput | 입력 |  |
| tech_view | model | 기술관점 | model=gpt-5.4, prompt=사용자 입력을 기술 관점에서만 분석하세요. 1-2문장으로 간결하게 답변하세요.... |
| biz_view | model | 비즈니스관점 | model=gpt-5.4, prompt=사용자 입력을 비즈니스 관점에서만 분석하세요. 1-2문장으로 간결하게 답변하세요.... |
| user_view | model | 사용자관점 | model=gpt-5.4, prompt=사용자 입력을 사용자 관점에서만 분석하세요. 1-2문장으로 간결하게 답변하세요.... |
| merge_views | merge | 관점취합 | type=template |
| end | flowOutput | 출력 |  |

### 엣지 연결
| Source | Handle | Target |
|---|---|---|
| start | output | tech_view |
| start | output | biz_view |
| start | output | user_view |
| tech_view | output | merge_views |
| biz_view | output | merge_views |
| user_view | output | merge_views |
| merge_views | output | end |

### 검증 체크리스트
| 항목 | 결과 | 상세 |
|---|---|---|
| Input 노드 존재 | ✅ | {'start'} |
| Output 노드 존재 | ✅ | {'end'} |
| 모든 노드 incoming 연결 | ✅ | OK |
| 모든 노드 outgoing 연결 | ✅ | OK |
| Model 'tech_view' 프롬프트 | ✅ | model=gpt-5.4, len=43 |
| Model 'biz_view' 프롬프트 | ✅ | model=gpt-5.4, len=45 |
| Model 'user_view' 프롬프트 | ✅ | model=gpt-5.4, len=44 |

### 실행 테스트
| 입력 | 결과 | 응답 요약 |
|---|---|---|
| 병렬 분석: AI 챗봇 도입의 장단점은?... | ✅ | 기술=장점: 24/7 자동응대, 응답 속도 향상, 운영비 절감, 대량 문의 처리와 데이터 기반 개선이 가능합니다.  
단점: 복잡한 문의 대응 ... |

### AI 대화 이력 (Human-in-the-Loop)
| Turn | Role | Content |
|---|---|---|
| 1 | user | 다관점 분석 플로우. 입력을 3개 gpt-5.4 모델에 동시에 보내서 기술관점, 비즈니스관점, 사용자관점으로 각각 1-2문장 답변 후 머지노드로 취합. 머지 템플릿: 기술={{기술 |
| 2 | assistant | 다관점 분석 플로우를 생성했습니다.

구성:
- 입력
- 기술관점: gpt-5.4
- 비즈니스관점: gpt-5.4
- 사용자관점: gpt-5.4
- 관점취합: merge templ |

---

## 5. 해상운송 상담 플로우
- **ID**: `auto-3b12f6b7`
- **노드**: 6개 | **엣지**: 6개

### 노드 구성
| ID | Type | Label | Config 요약 |
|---|---|---|---|
| start | flowInput | 상담 접수 |  |
| privacy_guard | guardrail | 개인정보보호 | resourceId=8deec695-a624-4bdf-a901-f8a0656ac9a2 |
| shipping_glossary | glossary | 해상운송 용어 조회 | resourceId=5ecabdf0-02f2-47e6-a5ce-734063de4d62 |
| shipping_agent | agent | 해상운송 상담 에이전트 | resourceId=hwan-test-agent-v1-1774572008581 |
| blocked_message | transform | 차단 안내 | template=요청에 개인정보 또는 민감정보가 포함되어 있어 처리할 수 없습니다. 개인정보를 제거한 뒤 ... |
| end | flowOutput | 상담 응답 |  |

### 엣지 연결
| Source | Handle | Target |
|---|---|---|
| start | output | privacy_guard |
| privacy_guard | pass | shipping_glossary |
| shipping_glossary | output | shipping_agent |
| privacy_guard | block | blocked_message |
| shipping_agent | output | end |
| blocked_message | output | end |

### 검증 체크리스트
| 항목 | 결과 | 상세 |
|---|---|---|
| Input 노드 존재 | ✅ | {'start'} |
| Output 노드 존재 | ✅ | {'end'} |
| 모든 노드 incoming 연결 | ✅ | OK |
| 모든 노드 outgoing 연결 | ✅ | OK |
| Guardrail 'privacy_guard' pass/block | ✅ | pass=True, block=True |
| Agent 'shipping_agent' 리소스 | ✅ | resourceId=hwan-test-agent-v1-1774572008581 |
| Guardrail 'privacy_guard' 리소스 | ✅ | resourceId=8deec695-a624-4bdf-a901-f8a0656ac9a2 |
| Glossary 'shipping_glossary' 리소스 | ✅ | resourceId=5ecabdf0-02f2-47e6-a5ce-734063de4d62 |

### 실행 테스트
| 입력 | 결과 | 응답 요약 |
|---|---|---|
| 상담: 해상운송에서 B/L 서류 처리 방법을 알려주세요... | ✅ | 해상운송에서 **B/L(선하증권, Bill of Lading)**은 제시해주신 용어 설명처럼 **화물의 소유권을 증명**하고, **배서(Endo... |

### AI 대화 이력 (Human-in-the-Loop)
| Turn | Role | Content |
|---|---|---|
| 1 | user | 해상운송 상담 플로우. 개인정보보호 가드레일(8deec695-a624-4bdf-a901-f8a0656ac9a2) 통과 후, 해상운송 용어사전(5ecabdf0-02f2-47e6-a5 |
| 2 | assistant | 해상운송 상담 플로우를 생성했습니다.

구성:
1. 상담 접수
2. 개인정보보호 가드레일
   - 통과: 해상운송 용어 조회 → 해상운송 상담 에이전트 → 상담 응답
   - 차단 |

---

## 6. 다국어 상담 플로우
- **ID**: `auto-3d74090e`
- **노드**: 6개 | **엣지**: 7개

### 노드 구성
| ID | Type | Label | Config 요약 |
|---|---|---|---|
| start | flowInput | 상담 입력 |  |
| lang_router | router | 언어 감지 라우터 | routes=['ko', 'en', 'other'] |
| ko_reply | model | 한국어 응답 생성 | model=gpt-5.4, prompt=사용자의 입력이 한국어로 들어오면, 항상 자연스럽고 정중한 한국어로 답변하세요. 불필요하게... |
| en_reply | model | 영어 응답 생성 | model=gpt-5.4, prompt=If the user's input is in English, always respond ... |
| other_msg | transform | 기타 언어 안내 | template=죄송합니다. 현재는 한국어와 영어 상담만 지원합니다. 한국어 또는 영어로 다시 입력해 주세... |
| end | flowOutput | 상담 응답 |  |

### 엣지 연결
| Source | Handle | Target |
|---|---|---|
| start | output | lang_router |
| lang_router | ko | ko_reply |
| lang_router | en | en_reply |
| lang_router | other | other_msg |
| ko_reply | output | end |
| en_reply | output | end |
| other_msg | output | end |

### 검증 체크리스트
| 항목 | 결과 | 상세 |
|---|---|---|
| Input 노드 존재 | ✅ | {'start'} |
| Output 노드 존재 | ✅ | {'end'} |
| 모든 노드 incoming 연결 | ✅ | OK |
| 모든 노드 outgoing 연결 | ✅ | OK |
| Router 'lang_router' 모든 라우트 연결 | ✅ | routes={'en', 'ko', 'other'}, handles={'en', 'ko', 'other'} |
| Model 'ko_reply' 프롬프트 | ✅ | model=gpt-5.4, len=65 |
| Model 'en_reply' 프롬프트 | ✅ | model=gpt-5.4, len=136 |

### 실행 테스트
| 입력 | 결과 | 응답 요약 |
|---|---|---|
| 한국어: 안녕하세요 도움이 필요합니다... | ✅ | 죄송합니다. 현재는 한국어와 영어 상담만 지원합니다. 한국어 또는 영어로 다시 입력해 주세요.... |
| 영어: Hello I need help please... | ✅ | 죄송합니다. 현재는 한국어와 영어 상담만 지원합니다. 한국어 또는 영어로 다시 입력해 주세요.... |

### AI 대화 이력 (Human-in-the-Loop)
| Turn | Role | Content |
|---|---|---|
| 1 | user | 다국어 상담 플로우. 라우터로 한국어(한글포함)/영어(영문만)/기타 3개 언어 감지. 한국어는 gpt-5.4로 한국어 답변, 영어는 gpt-5.4로 영어답변, 기타는 안내메시지 출 |
| 2 | assistant | 완료했습니다.

구성된 플로우:
- 입력
- 언어 감지 라우터
  - 한국어(한글 포함) → `gpt-5.4` 한국어 응답
  - 영어(영문만) → `gpt-5.4` 영어 응답
  |

---

## 7. 감정분석 응답 플로우
- **ID**: `auto-6b309dfb`
- **노드**: 6개 | **엣지**: 6개

### 노드 구성
| ID | Type | Label | Config 요약 |
|---|---|---|---|
| start | flowInput | 입력 |  |
| sentiment_classifier | model | 감정 분류기 | model=gpt-5.4, prompt=사용자 입력의 감정을 POSITIVE 또는 NEGATIVE 중 하나로만 분류하세요. 다른 ... |
| is_positive | condition | 긍정 여부 확인 | contains: POSITIVE |
| positive_response | model | 긍정 응답 생성 | model=gpt-5.4, prompt=사용자 입력이 긍정적인 경우에 응답합니다. 감사의 표현을 포함하고, 사용자가 더 도움이 될... |
| negative_response | model | 부정 응답 생성 | model=gpt-5.4, prompt=사용자 입력이 부정적인 경우에 응답합니다. 먼저 사과의 표현을 하고, 문제 해결을 위한 구... |
| end | flowOutput | 출력 |  |

### 엣지 연결
| Source | Handle | Target |
|---|---|---|
| start | output | sentiment_classifier |
| sentiment_classifier | output | is_positive |
| is_positive | true | positive_response |
| is_positive | false | negative_response |
| positive_response | output | end |
| negative_response | output | end |

### 검증 체크리스트
| 항목 | 결과 | 상세 |
|---|---|---|
| Input 노드 존재 | ✅ | {'start'} |
| Output 노드 존재 | ✅ | {'end'} |
| 모든 노드 incoming 연결 | ✅ | OK |
| 모든 노드 outgoing 연결 | ✅ | OK |
| Condition 'is_positive' true/false | ✅ | true=True, false=True |
| Model 'sentiment_classifier' 프롬프트 | ✅ | model=gpt-5.4, len=72 |
| Model 'positive_response' 프롬프트 | ✅ | model=gpt-5.4, len=99 |
| Model 'negative_response' 프롬프트 | ✅ | model=gpt-5.4, len=94 |

### 실행 테스트
| 입력 | 결과 | 응답 요약 |
|---|---|---|
| 긍정 입력: 정말 좋은 서비스입니다 감사합니다... | ✅ | 좋아요, 감사합니다! 😊  
이 흐름이면 잘 진행되고 있는 것 같아요.

다음으로는  
- 지금 상태를 한 번 간단히 정리해보거나  
- 바로 ... |
| 부정 입력: 서비스가 너무 불편합니다... | ✅ | 불편을 드려 죄송합니다. 어떤 점이 마음에 들지 않으셨는지 알려주시면 바로 확인해 도와드리겠습니다. 원하시면 문제 상황을 짧게 설명해 주세요. ... |

### AI 대화 이력 (Human-in-the-Loop)
| Turn | Role | Content |
|---|---|---|
| 1 | user | 감정분석 플로우. gpt-5.4로 입력을 POSITIVE/NEGATIVE로 분류. 조건노드로 POSITIVE 포함 여부 확인. 긍정이면 감사+추천 응답 모델, 부정이면 사과+해결  |
| 2 | assistant | 감정분석 플로우를 생성했습니다.

구성:
- 입력
- 감정 분류기: gpt-5.4로 `POSITIVE` / `NEGATIVE` 분류
- 조건 노드: `POSITIVE` 포함 여부  |

---

## 8. IT 기술 상담 플로우
- **ID**: `auto-a05658cd`
- **노드**: 4개 | **엣지**: 3개

### 노드 구성
| ID | Type | Label | Config 요약 |
|---|---|---|---|
| start | flowInput | 질문 접수 |  |
| it_glossary | glossary | IT 용어 조회 | resourceId=d1c9ffc2-8e61-4d65-9ca8-7248160ac384 |
| it_expert_answer | model | IT 전문 답변 | model=gpt-5.4, prompt=IT 전문가로서 용어 참조를 활용하여 답변.... |
| end | flowOutput | 응답 전송 |  |

### 엣지 연결
| Source | Handle | Target |
|---|---|---|
| start | output | it_glossary |
| it_glossary | output | it_expert_answer |
| it_expert_answer | output | end |

### 검증 체크리스트
| 항목 | 결과 | 상세 |
|---|---|---|
| Input 노드 존재 | ✅ | {'start'} |
| Output 노드 존재 | ✅ | {'end'} |
| 모든 노드 incoming 연결 | ✅ | OK |
| 모든 노드 outgoing 연결 | ✅ | OK |
| Model 'it_expert_answer' 프롬프트 | ✅ | model=gpt-5.4, len=24 |
| Glossary 'it_glossary' 리소스 | ✅ | resourceId=d1c9ffc2-8e61-4d65-9ca8-7248160ac384 |

### 실행 테스트
| 입력 | 결과 | 응답 요약 |
|---|---|---|
| 용어 포함: CI/CD 파이프라인에서 DevOps 전략을 알려주세요... | ✅ | CI/CD 파이프라인에서의 **DevOps 전략**은, 개발과 운영을 통합하는 **DevOps** 문화 및 방법론을 기반으로 **CI/CD(지속... |

### AI 대화 이력 (Human-in-the-Loop)
| Turn | Role | Content |
|---|---|---|
| 1 | user | IT 기술 상담 플로우. IT 용어사전(d1c9ffc2-8e61-4d65-9ca8-7248160ac384)으로 용어 조회한 후, gpt-5.4 모델이 용어 참조를 활용해 전문적으로 |
| 2 | assistant | IT 기술 상담 플로우를 생성했습니다.

구성:
- 질문 접수
- IT 용어 조회
- IT 전문 답변
- 응답 전송

설계 내용:
- `IT 용어사전 (d1c9ffc2-8e61-4 |

---

## 9. HR 문의 긴급응대 플로우
- **ID**: `auto-24266fbc`
- **노드**: 7개 | **엣지**: 8개

### 노드 구성
| ID | Type | Label | Config 요약 |
|---|---|---|---|
| start | flowInput | HR 문의 접수 |  |
| blocked_words_guard | guardrail | 금칙어 차단 | resourceId=12336abc-d269-49ee-b74e-f9203a1740be |
| urgent_check | condition | 긴급 여부 판별 | regex: 급|즉시|지금|긴급 |
| blocked_message | transform | 차단 안내 | template=입력 내용에 금칙어가 포함되어 요청을 처리할 수 없습니다. 내용을 수정한 뒤 다시 문의해주... |
| quick_reply | model | 긴급 빠른답변 | model=gpt-5.4, prompt=당신은 HR 문의를 신속히 1차 응대하는 담당자입니다. 사용자의 문의가 긴급한 경우, 핵심... |
| hr_detailed_answer | agent | HR 상세답변 | resourceId=hr-agentgpt52test |
| end | flowOutput | 응답 전달 |  |

### 엣지 연결
| Source | Handle | Target |
|---|---|---|
| start | output | blocked_words_guard |
| blocked_words_guard | pass | urgent_check |
| blocked_words_guard | block | blocked_message |
| urgent_check | true | quick_reply |
| urgent_check | false | hr_detailed_answer |
| blocked_message | output | end |
| quick_reply | output | end |
| hr_detailed_answer | output | end |

### 검증 체크리스트
| 항목 | 결과 | 상세 |
|---|---|---|
| Input 노드 존재 | ✅ | {'start'} |
| Output 노드 존재 | ✅ | {'end'} |
| 모든 노드 incoming 연결 | ✅ | OK |
| 모든 노드 outgoing 연결 | ✅ | OK |
| Guardrail 'blocked_words_guard' pass/block | ✅ | pass=True, block=True |
| Condition 'urgent_check' true/false | ✅ | true=True, false=True |
| Model 'quick_reply' 프롬프트 | ✅ | model=gpt-5.4, len=137 |
| Agent 'hr_detailed_answer' 리소스 | ✅ | resourceId=hr-agentgpt52test |
| Guardrail 'blocked_words_guard' 리소스 | ✅ | resourceId=12336abc-d269-49ee-b74e-f9203a1740be |

### 실행 테스트
| 입력 | 결과 | 응답 요약 |
|---|---|---|
| 긴급: 급하게 연차를 지금 바로 신청해야 합니다... | ✅ | 지금 바로 연차가 필요하시면 이렇게 진행하세요.

1. **우선 팀장/관리자에게 즉시 구두·메신저로 알리기**
   - “개인 사정으로 오늘 연... |

### AI 대화 이력 (Human-in-the-Loop)
| Turn | Role | Content |
|---|---|---|
| 1 | user | HR 문의 플로우. 금칙어 차단 가드레일(12336abc-d269-49ee-b74e-f9203a1740be) 사용. 통과후 조건노드로 긴급 여부 판별(급,즉시,지금,긴급 포함 시) |
| 2 | assistant | 플로우 생성이 완료되었습니다.

구성 요약:
- 시작: HR 문의 접수
- 가드레일: 금칙어 차단 (`12336abc-d269-49ee-b74e-f9203a1740be`)
- 조건 |

---

## 10. PII 검사 후 답변/차단 안내 플로우
- **ID**: `auto-293421b3`
- **노드**: 5개 | **엣지**: 5개

### 노드 구성
| ID | Type | Label | Config 요약 |
|---|---|---|---|
| start | flowInput | 입력 |  |
| pii_guard | guardrail | 개인정보보호 검사 | resourceId=8deec695-a624-4bdf-a901-f8a0656ac9a2 |
| answer_model | model | 답변 생성 | model=gpt-5.4, prompt=한국어로 친절하게 답변하세요.... |
| block_message | transform | 차단 안내 | template=입력 내용에 개인정보 또는 민감정보가 포함되어 있어 요청을 처리할 수 없습니다. 개인정보를... |
| end | flowOutput | 출력 |  |

### 엣지 연결
| Source | Handle | Target |
|---|---|---|
| start | output | pii_guard |
| pii_guard | pass | answer_model |
| pii_guard | block | block_message |
| answer_model | output | end |
| block_message | output | end |

### 검증 체크리스트
| 항목 | 결과 | 상세 |
|---|---|---|
| Input 노드 존재 | ✅ | {'start'} |
| Output 노드 존재 | ✅ | {'end'} |
| 모든 노드 incoming 연결 | ✅ | OK |
| 모든 노드 outgoing 연결 | ✅ | OK |
| Guardrail 'pii_guard' pass/block | ✅ | pass=True, block=True |
| Model 'answer_model' 프롬프트 | ✅ | model=gpt-5.4, len=16 |
| Guardrail 'pii_guard' 리소스 | ✅ | resourceId=8deec695-a624-4bdf-a901-f8a0656ac9a2 |

### 실행 테스트
| 입력 | 결과 | 응답 요약 |
|---|---|---|
| 일반 질문: 안녕하세요 도움이 필요합니다... | ✅ | 안녕하세요! 물론 도와드릴게요.  
무엇이 필요하신가요? 편하게 말씀해 주세요.... |
| PII 차단: admin@test.com으로 보내주세요... | ✅ | 어떤 내용을 그 이메일로 보내드리면 될까요?

원하시면 제가
- 이메일 제목
- 본문 내용
- 정중한 표현으로 다듬기

까지 바로 작성해드릴게요... |

### AI 대화 이력 (Human-in-the-Loop)
| Turn | Role | Content |
|---|---|---|
| 1 | user | 가드레일(개인정보보호, ID: 8deec695-a624-4bdf-a901-f8a0656ac9a2)로 PII 검사 후 통과하면 gpt-5.4 모델로 답변, 차단시 안내메시지 출력하는 |
| 2 | assistant | 플로우 생성이 완료되었습니다.

구성:
- 입력
- 개인정보보호 검사 `8deec695-a624-4bdf-a901-f8a0656ac9a2`
  - 통과 → `gpt-5.4` 답변  |

---

## 종합 결과

| # | 플로우 | 노드 | 연결 | 실행 | 프롬프트 | 리소스 |
|---|--------|------|------|------|----------|--------|
| 1 | 고객 문의 부서 분류 및 전문가 답변 플로우 | 8N 10E | ✅ | ✅ | ✅ | ✅ |
| 2 | 종합 고객 지원 플로우 | 9N 10E | ✅ | ✅ | ✅ | ✅ |
| 3 | 사내 규정 상담 플로우 | 8N 10E | ✅ | ✅ | ✅ | ✅ |
| 4 | 다관점 분석 플로우 | 6N 7E | ✅ | ✅ | ✅ | ✅ |
| 5 | 해상운송 상담 플로우 | 6N 6E | ✅ | ✅ | ✅ | ✅ |
| 6 | 다국어 상담 플로우 | 6N 7E | ✅ | ✅ | ✅ | ✅ |
| 7 | 감정분석 응답 플로우 | 6N 6E | ✅ | ✅ | ✅ | ✅ |
| 8 | IT 기술 상담 플로우 | 4N 3E | ✅ | ✅ | ✅ | ✅ |
| 9 | HR 문의 긴급응대 플로우 | 7N 8E | ✅ | ✅ | ✅ | ✅ |
| 10 | PII 검사 후 답변/차단 안내 플로우 | 5N 5E | ✅ | ✅ | ✅ | ✅ |