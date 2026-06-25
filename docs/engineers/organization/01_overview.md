# 조직 관리 기능 상세

## 기능 설명

조직 관리 기능은 외부 IdP(Identity Provider)의 조직 구조를 Cloosphere에 동기화하여, 조직 단위(Organizational Unit) 기반의 접근 제어를 가능하게 합니다.

## 사용 시나리오

### 시나리오 1: 부서별 지식 베이스 접근 제어

```
회사 조직 구조:
├── 개발팀
│   ├── 백엔드팀
│   └── 프론트엔드팀
├── 기획팀
└── 마케팅팀
```

- 개발팀 전용 기술 문서 지식 베이스 → `개발팀` 조직 단위에 읽기 권한
- 백엔드팀, 프론트엔드팀도 상위 조직 단위인 `개발팀`의 권한을 상속받아 접근 가능

### 시나리오 2: OAuth 로그인 시 자동 부서 배치

1. 사용자 A가 Microsoft 계정으로 로그인
2. Microsoft Graph API에서 사용자의 `department` 필드 조회 (예: "개발팀")
3. Cloosphere에 등록된 조직 단위 중 "개발팀" 찾기
4. 사용자 A를 해당 조직 단위의 멤버로 자동 추가
5. 사용자 A는 즉시 개발팀에 할당된 리소스에 접근 가능

### 시나리오 3: 그룹 + 조직 단위 혼합 사용

| 구분 | 그룹 | 조직 단위 |
|------|------|----------|
| 관리 방식 | 수동 (관리자가 사용자 추가) | 자동 (IdP 동기화) |
| 구조 | 평면 (계층 없음) | 계층 (상속 지원) |
| 용도 | 프로젝트별, 역할별 | 부서별, 조직별 |

**예시**:
- "AI 프로젝트" 그룹 + "개발팀" 조직 단위 모두에 읽기 권한
- 개발팀 소속이 아니어도 AI 프로젝트 그룹 멤버면 접근 가능

## 동기화 방식

### 1. 수동 동기화 (관리자 페이지)

관리자가 직접 동기화 버튼을 클릭하여 IdP에서 조직 구조를 가져옵니다.

**지원 Provider:**

| Provider | 설명 | 데이터 소스 |
|----------|------|------------|
| **JSON** | JSON 데이터 직접 입력 | 수동 입력 |
| **MS Graph** | Microsoft Entra ID | Administrative Units, Groups, Departments |

**MS Graph 동기화 옵션:**

| 옵션 | 설명 | 사용 케이스 |
|------|------|------------|
| Administrative Units | Entra ID 관리 단위 | Azure Portal에서 관리 단위 구성한 경우 |
| Security Groups | 보안 그룹 → 조직 단위 변환 | 그룹 기반 조직 관리 |
| Departments | 사용자 프로필의 부서 필드 추출 | **가장 일반적** (권장) |

### 2. 자동 동기화 (OAuth 로그인)

사용자가 Microsoft OAuth로 로그인할 때 자동으로 조직 단위에 배치됩니다.

```
환경 변수: ENABLE_OAUTH_ORG_UNIT_MANAGEMENT=true (기본값)
```

**동작 방식:**
1. Microsoft OAuth 로그인 완료
2. Graph API `/me` 엔드포인트에서 `department` 필드 조회
3. 기존 조직 단위 중 이름이 일치하는 단위 검색
4. 사용자를 해당 조직 단위의 `member_ids`에 추가
5. 같은 조직 내 다른 단위에서는 자동 제거 (부서 이동 반영)

## 권한 체크 로직

### 접근 권한 확인 순서

```python
def has_access(user, resource, permission="read"):
    # 1. 관리자는 항상 접근 가능
    if user.role == "admin":
        return True

    # 2. 리소스가 public이면 모두 접근 가능
    if resource.access_control is None:
        return True

    # 3. 그룹 기반 체크
    user_groups = get_user_groups(user.id)
    allowed_groups = resource.access_control[permission]["group_ids"]
    if any(g in allowed_groups for g in user_groups):
        return True

    # 4. 조직 단위 기반 체크 (상속 포함)
    user_org_units = get_user_org_units_with_ancestors(user)
    allowed_org_units = resource.access_control[permission]["org_unit_ids"]
    if any(ou in allowed_org_units for ou in user_org_units):
        return True

    return False
```

### 권한 상속

상위 조직 단위에 부여된 권한은 모든 하위 조직 단위에 자동 상속됩니다.

```
조직 구조:
├── 개발팀 (지식 베이스 A 읽기 권한)
│   ├── 백엔드팀
│   └── 프론트엔드팀

결과:
- 개발팀 멤버 → 지식 베이스 A 접근 가능
- 백엔드팀 멤버 → 지식 베이스 A 접근 가능 (상속)
- 프론트엔드팀 멤버 → 지식 베이스 A 접근 가능 (상속)
```

## 지원 리소스

조직 단위 기반 접근 제어를 지원하는 리소스:

| 리소스 | 모델 | 권한 유형 |
|--------|------|----------|
| Knowledge (지식) | `Knowledges` | read, write |
| Tool Connections (도구) | `ToolConnections` | read, write |
| Prompts (프롬프트) | `Prompts` | read, write |
| Models (모델) | `Models` | read, write |
| Database (데이터베이스) | `DbSpheres` | read, write |
| Glossary (용어집) | `Glossaries` | read, write |

## 제한 사항

1. **조직 단위 생성**: 현재 동기화를 통해서만 생성 가능 (수동 생성 UI 미제공)
2. **멀티 조직**: 한 사용자가 여러 조직에 속할 수 있음 (테넌트 분리는 미지원)
3. **실시간 동기화**: 조직 구조 변경 시 재동기화 필요 (WebHook 미지원)
