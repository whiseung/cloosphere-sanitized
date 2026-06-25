> Last Updated: 2026-04-08

# OpenWebUI 설정/데이터 저장 처리 흐름 정리

## 공통 관점 정리

* **Frontend (Svelte)**
  사용자 액션(저장/추가 버튼) → 화면 단 함수 호출
* **Frontend API Layer (TS)**
  REST API 호출만 담당 (비즈니스 로직 없음)
* **Backend Router (FastAPI)**
  요청 수신 → Model 또는 Config 객체 호출
* **DB 저장 방식**

  * 확장 모듈(extension): Model 메서드에서 직접 저장
  * 설정(Config): `request.app.state.config`에 값 할당 시 자동 저장


---
<br /><br />

## 예시 #1. 지식 기반 생성 흐름

### 1️⃣ 프론트엔드 (UI)

**파일**

```
/src/lib/components/workspace/Knowledge/CreateKnowledgeBase.svelte
```

**동작**

* 지식 기반 등록 화면에서 **저장(submit)** 클릭
* `createNewKnowledge()` 함수 호출

---

### 2️⃣ 프론트엔드 API 호출

**파일**

```
/src/lib/apis/knowledge/index.ts
```

**동작**

* `createNewKnowledge()` 내부에서 백엔드 호출
* 호출 URL:

```ts
${WEBUI_API_BASE_URL}/knowledge/create
```

---

### 3️⃣ 백엔드 Router

**파일**

```
/backend/open_webui/routers/knowledge.py
```

**동작**

```python
Knowledges.insert_new_knowledge(user.id, form_data)
```

* 사용자 ID + 입력 데이터 전달

---

### 4️⃣ DB 저장 (Model)

**파일**

```
/backend/open_webui/models/knowledge.py
```

**동작**

* `insert_new_knowledge()` 내부에서
* ORM을 통해 **직접 DB INSERT 수행**

✅ **명시적 DB 저장 방식 (일반 데이터 패턴)**

---

<br /><br />


## 예시 #2. 관리자 패널 → 설정 → 일반 설정 저장 흐름

### 1️⃣ 프론트엔드 (UI)

**파일**

```
/src/lib/components/admin/Settings/General.svelte
```

**동작**

* 관리자 패널 → 설정 → 일반 화면
* 저장 버튼 클릭 시 `updateAdminConfig()` 호출

---

### 2️⃣ 프론트엔드 API 호출

**파일**

```
/src/lib/apis/index.ts
```

**동작**

* 호출 URL:

```ts
${WEBUI_API_BASE_URL}/auths/admin/config
```

---

### 3️⃣ 백엔드 Router

**파일**

```
/backend/open_webui/routers/auths.py
```

**동작 핵심**

```python
request.app.state.config.<속성> = 값
```

---

### 4️⃣ 자동 저장 메커니즘

설정 값 할당 시 내부적으로 다음이 **자동 호출**됨:

```
AppConfig.__setattr__()
  ↓
PersistentConfig.save()
  ↓
DB 저장
```

✅ **Config 기반 자동 영속화 패턴**

* Router에서 별도 save 호출 없음
* config 객체에 값 할당 = DB 저장

---

<br /><br />

## 예시 #3. 관리자 설정 – OpenAI 연결 추가 흐름

### 1️⃣ 프론트엔드 (UI 구조)

**관리자 - 설정 - 연결 화면(부모 페이지)**  에서 `'+' 연결 추가` 버튼 클릭 시
```
/src/lib/components/admin/Settings/Connections.svelte
```
**연결 추가 모달(자식 페이지)** 활성화되고, 저장 버튼 클릭 시 
```
/src/lib/components/AddConnectionModal.svelte
```
부모페이지의 
```svelte
<AddConnectionModal
  bind:show={showAddOpenAIConnectionModal}
  onSubmit={addOpenAIConnectionHandler}
/>
```
가 호출되고 `updateOpenAIHandler()` 함수가 호출되고, <br />`updateOpenAIConfig()` 함수가 최종 호출 됨


---

### 2️⃣ 모달 저장 처리

**파일**

```
/src/lib/components/AddConnectionModal.svelte
```

**동작 흐름**

1. 모달에서 저장 클릭
2. `onSubmit` 이벤트 발생
3. 부모 컴포넌트의 `addOpenAIConnectionHandler()` 호출
4. 내부에서

   * `updateOpenAIHandler()`
   * `updateOpenAIConfig()` 순으로 호출

---

### 3️⃣ 프론트엔드 API 호출

**파일**

```
/src/lib/apis/openai/index.ts
```

**호출 URL**

```ts
${OPENAI_API_BASE_URL}/config/update
```

---

### 4️⃣ 백엔드 Router

**파일**

```
/backend/open_webui/routers/openai.py
```

**동작**

```python
request.app.state.config.<openai 관련 속성> = 값
```

---

### 5️⃣ 자동 DB 저장

예시 #2와 동일:

```
AppConfig.__setattr__()
  ↓
PersistentConfig.save()
  ↓
DB 저장
```

✅ **Config 기반 자동 영속화 (OpenAI 설정)**

---

<br /><br />

## 패턴 요약 

| 구분                 | 저장 방식             | 특징     |
| ------------------ | ----------------- | ------ |
| Knowledge / Database | Model에서 직접 INSERT | 명시적 저장 |
| 관리자 설정           | Config 객체 할당      | 자동 저장  |

