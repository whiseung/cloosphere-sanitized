# Video Edit Command

녹화된 데모 비디오를 편집합니다. 중복 프레임 자동 제거 후 사용자 지시에 따라 편집 효과를 적용합니다.

## 사용법

```
/video_edit /tmp/playwright-videos/recording.webm 로그인 부분 제거하고 응답 영역 확대해줘
/video_edit /tmp/playwright-videos/demo.webm 비밀번호 블러 처리하고 fade in/out 넣어줘
/video_edit /tmp/playwright-videos/flow.webm 중복 프레임만 제거해줘
```

첫 번째 인자로 비디오 파일 경로, 이후에 편집 지시사항을 전달합니다.

ARGUMENTS: $ARGUMENTS

## 사용 가능한 MCP 도구

### 기본 편집
| 도구 | 설명 | 주요 파라미터 |
|------|------|-------------|
| `video_info` | 비디오 메타데이터 조회 | input |
| `video_dedupe` | 중복/정적 프레임 자동 제거 | input, threshold(low/medium/high) |
| `video_trim` | 구간 잘라내기 | input, start, end |
| `video_speed` | 속도 조절 | input, speed(0.5=슬로모, 2=2배속) |
| `video_frame` | 프레임 추출 / 정지 클립 생성 | input, time, duration |

### 크기/변환
| 도구 | 설명 | 주요 파라미터 |
|------|------|-------------|
| `video_crop` | 영역 크롭 + 확대 | input, x, y, width, height, scale_width, scale_height |
| `video_resize` | 해상도 변경 | input, width, height |
| `video_convert` | 포맷 변환 | input, format(mp4/webm/gif/mov), quality |
| `video_concat` | 여러 클립 합치기 | inputs[], output |

### 효과
| 도구 | 설명 | 주요 파라미터 |
|------|------|-------------|
| `video_fade` | 페이드 인/아웃 (검은 화면 전환) | input, fade_in, fade_out |
| `video_highlight` | 특정 영역에 테두리 강조 | input, x, y, width, height, color, thickness, start_time, end_time |
| `video_blur` | 특정 영역 블러 (민감 정보 가리기) | input, x, y, width, height, strength, start_time, end_time |
| `video_spotlight` | 특정 영역만 밝게, 나머지 어둡게 | input, x, y, width, height, darkness, start_time, end_time |
| `video_text_overlay` | 텍스트 오버레이 | input, text, x, y, fontsize, fontcolor, bg_color, start_time, end_time |

### 고급 효과 (FFmpeg 직접 사용)
| 효과 | 설명 | 구현 |
|------|------|------|
| **Smooth Zoom (zoompan)** | 정지 프레임에서 부드럽게 확대 | `video_frame`으로 프레임 추출 → FFmpeg `zoompan` 필터 → `video_concat`으로 합치기 |
| **Crossfade** | 두 클립 간 디졸브 전환 | FFmpeg `xfade` 필터 |

## 실행 단계

### 1단계: 입력 분석

인자에서 **비디오 파일 경로**와 **편집 지시사항**을 분리합니다.

```
파일 경로: 첫 번째 인자 (공백 포함 가능, .webm/.mp4/.mov 등)
편집 지시: 파일 경로 이후의 텍스트
```

### 2단계: 비디오 정보 확인

```
video_info → 원본 메타데이터 (길이, 해상도, 코덱) 확인
```

### 3단계: 중복 프레임 제거 (항상 수행)

```
video_dedupe(input, threshold="medium") → 정적 대기 시간 자동 제거
```

결과를 보고하고, 타임스탬프별 프레임을 추출하여 내용을 확인합니다.

### 4단계: 1초 간격 전체 프레임 스캔 + 타임라인 맵 생성

dedupe된 비디오의 **1초 간격으로 전체 프레임을 추출**하여 타임라인 맵을 만듭니다.

**4.1: 프레임 추출**
```
1. video_info로 총 길이(duration) 확인
2. 0초부터 1초 간격으로 video_frame 추출 (병렬 호출 가능)
3. 추출된 모든 프레임을 Read tool로 시각 확인
```

**4.2: 타임라인 맵 작성**

프레임을 보면서 아래 형식의 타임라인 맵을 작성합니다:
```
| 시간 | 화면 내용 | 분류 |
|------|----------|------|
| 0s | 빈 화면 / 로딩 | TRIM (제거) |
| 1s | 로그인 폼 | TRIM (제거) |
| 2s | Knowledge 목록 | KEEP |
| 3s | KB 생성 폼 타이핑 | KEEP + ZOOM |
| ... | ... | ... |
| 15s | 스피너 회전 (업로드 대기) | SKIP (잘라내기) |
| 16s | 스피너 회전 (동일) | SKIP |
| 20s | 업로드 완료 (Summary) | KEEP |
```

**분류 기준:**
- **KEEP**: 의미 있는 화면 → 유지
- **KEEP + ZOOM**: 입력/결과 영역 → 유지 + 줌인 효과
- **TRIM**: 로그인, 빈 화면 등 → 앞뒤 잘라내기
- **SKIP**: 대기/로딩 구간 → 중간 잘라내기
- **SPEED**: 로딩이지만 진행 상태 표시 → 배속 처리
- **ERROR**: 에러 화면, 사이드바 노출 등 → 재녹화 판단

**4.3: 이상 패턴 자동 감지**

| 이상 패턴 | 감지 방법 | 조치 |
|-----------|----------|------|
| 연속 3+초 동일 화면 | 연속 프레임이 거의 같은 내용 | SKIP 또는 SPEED |
| 빈/흰 화면 | 내용 없는 프레임 | TRIM |
| "Backend Required" | 에러 텍스트 | **FAIL — 재녹화 필요** |
| 사이드바 열림 | 좌측에 채팅 히스토리 | **WARN — 확인 필요** |
| 모델 2개 표시 | 상단에 두 줄 모델명 | **WARN — 편집으로 해결 불가** |
| 토스트/모달 잔존 | 예상치 못한 오버레이 | WARN |
| 로딩 스피너 | "Generating...", 스켈레톤 바 | SKIP 또는 SPEED |

**4.4: 검증 판정**
- **PASS**: ERROR 없음 → 타임라인 맵 기반으로 편집 진행
- **FAIL**: ERROR 발견 → 사용자에게 재녹화 요청
- 타임라인 맵에 SKIP/TRIM이 있으면 → 해당 구간 자동 편집 계획 수립

**중요**: 프레임을 직접 확인하지 않고 blind 편집하지 말 것.

### 4.3단계: 페이지 전환 시 최소 체류 시간 확보

새로운 페이지나 화면이 나타날 때, 시청자가 어떤 페이지인지 인지할 수 있도록 **1초 동안** 해당 화면을 유지해야 합니다.

**감지 방법**: 프레임 확인 시 이전 프레임과 레이아웃이 완전히 달라진 경우 (페이지 전환)
- URL 변경, 사이드바 구성 변경, 전체 레이아웃 변경 등

**처리 방법**: 페이지 전환 직후 프레임이 1초 미만이면 정지 프레임을 삽입하여 **1초** 확보:
```bash
# 전환 직후 프레임 추출
ffmpeg -y -i input.webm -vf "select=gte(t\,{전환시점})" -frames:v 1 page_frame.png
# 1초 정지 클립 생성
ffmpeg -y -loop 1 -i page_frame.png -t 1.0 -c:v libvpx -b:v 2M -r 25 -an page_hold.webm
```

### 4.4단계: 입력 영역 자연스러운 확대 (zoompan 트랜지션)

워크스페이스/관리자 페이지에서 **텍스트 입력이 진행되는 구간**은 해당 영역을 2x 확대(crop+scale)하여 보여줍니다. **채팅 입력도 포함합니다.**

**확대 구현 방법** (반드시 zoompan 트랜지션 사용):
1. 확대 시작 직전 프레임을 추출
2. zoompan으로 0.3초 부드러운 줌인 트랜지션 클립 생성
3. 확대된 콘텐츠 구간을 crop+scale로 생성
4. 세그먼트 순서: [일반 구간] → [줌인 트랜지션 0.3s] → [확대된 구간] → [일반 구간]

**zoompan 줌인 트랜지션 생성 (0.3초, 8프레임):**
```bash
# frame.png = 확대 시작 직전의 전체 화면 프레임
# TARGET_X, TARGET_Y = crop 오프셋 (확대 영역의 좌상단 좌표)
# 2x 줌인:
ffmpeg -y -loop 1 -i frame.png \
  -filter_complex "zoompan=z='min(1+on*0.125,2)':x='TARGET_X*min(on/8.0,1)':y='TARGET_Y*min(on/8.0,1)':d=8:fps=25:s=1440x900" \
  -t 0.32 -c:v libvpx -b:v 2M -r 25 -an zoom_in.webm

# 1.5x 줌인 (모달 등 넓은 영역용):
ffmpeg -y -loop 1 -i frame.png \
  -filter_complex "zoompan=z='min(1+on*0.0625,1.5)':x='TARGET_X*min(on/8.0,1)':y='TARGET_Y*min(on/8.0,1)':d=8:fps=25:s=1440x900" \
  -t 0.32 -c:v libvpx -b:v 2M -r 25 -an zoom_in.webm
```

**확대된 콘텐츠 구간 생성:**
```bash
# 1440x900 비디오에서 2x 줌 = 720x450 크롭 → 1440x900 스케일
ffmpeg -y -i input.webm -ss {시작} -t {길이} \
  -vf "crop=720:450:{TARGET_X}:{TARGET_Y},scale=1440:900" \
  -c:v libvpx -b:v 2M -r 25 -an zoomed_content.webm
```

**주의**: 줌인 트랜지션 없이 바로 크롭하면 화면이 잘린 것처럼 보임 → 반드시 zoompan 트랜지션을 앞에 삽입

### 4.45단계: 중요 UI 요소 체류 시간 확보

dedupe 후 **빠르게 지나가는 중요한 UI 인터랙션** (버튼 클릭, 드롭다운 선택, 토글 전환 등)은 정지 프레임을 삽입하여 시청자가 인지할 수 있도록 합니다.

**감지 기준**: UI 상태 변경이 1초 미만으로 표시되는 경우
- 버튼 선택/해제 (예: PII Type 선택, Strategy 변경)
- 토글 스위치 전환
- 드롭다운 선택 결과

**처리 방법**: 변경 후 상태를 보여주는 프레임을 추출하여 1.5~2초 정지 클립 생성 + 확대:
```bash
ffmpeg -y -loop 1 -i state_frame.png -t 2.0 \
  -vf "crop=720:450:{x}:{y},scale=1440:900" \
  -c:v libvpx -b:v 2M -r 25 -an state_hold.webm
```

### 4.5단계: 로딩/프로그레스바 구간 배속 처리

`video_dedupe`는 완전히 정적인 프레임만 제거합니다. 하지만 채팅 응답의 **프로그레스바, 스켈레톤 로딩, 스피너** 등은 매 프레임 미세하게 변하기 때문에 dedupe로 제거되지 않습니다.

**감지 방법**: 프레임 확인 시 아래 패턴이 보이면 로딩 구간:
- "Generating final answer...", "Preparing context...", "Starting Agent..." 등 상태 텍스트
- 스켈레톤 로딩 바 (회색 막대가 깜빡이는 영역)
- 스피너 아이콘이 돌아가는 화면
- 화면 레이아웃은 동일하지만 프로그레스바만 움직이는 구간

**처리 방법** (우선순위 순):
1. **잘라내기 (우선)**: 대기 화면이 시청자에게 의미 없으면 완전히 제거. 앞뒤 프레임이 자연스럽게 이어지면 가장 깔끔함.
2. **배속 처리 (차선)**: 진행 상태가 변하는 대기(업로드 프로그레스, 파일 하나씩 완료 등)는 4배속으로 압축.
```
1. 로딩 시작/끝 시점 파악 (프레임 확인으로)
2. 비디오를 3등분:
   - Part A: 로딩 전 (정상 속도)
   - Part B: 로딩 구간 (4배속)
   - Part C: 로딩 후 (정상 속도)
3. 각 파트를 FFmpeg로 처리:
```
```bash
# Part A: 정상
ffmpeg -y -ss 0 -to {로딩시작} -i input.webm -c:v libvpx -b:v 1M -r 25 -an partA.webm

# Part B: 4배속 (로딩 구간)
ffmpeg -y -ss {로딩시작} -to {로딩끝} -i input.webm -filter:v "setpts=0.25*PTS" -c:v libvpx -b:v 1M -r 25 -an partB.webm

# Part C: 정상
ffmpeg -y -ss {로딩끝} -i input.webm -c:v libvpx -b:v 1M -r 25 -an partC.webm
```
```
4. video_concat([partA, partB, partC]) → 합치기
```

**참고**: 배속 배율은 구간 길이에 따라 조절. 2초 미만이면 생략, 2~5초면 3배속, 5초 이상이면 4~6배속.

### 5단계: 사용자 지시 적용

사용자가 구체적인 편집 지시를 제공하면 해당 지시를 따릅니다.

**편집 지시가 없거나 "알아서 해줘"인 경우**, 아래 기본 편집을 모두 수행합니다:
1. 중복 프레임 제거 (dedupe)
2. 로딩 구간이 남아있으면 → 4배속 처리 (4.5단계)
3. 의미 없는 앞/뒤 구간 트림 (빈 화면, 로그인 등)
4. 입력 영역 줌인 + zoompan 트랜지션 (4.4단계)
5. 페이지 전환 최소 1초 체류 (4.3단계)
6. 빠르게 지나가는 UI 요소 체류 시간 확보 (4.45단계)
7. 자막 SRT 생성 + 번인 (5.5단계)
8. MP4 변환

**편집 지시 해석 가이드:**
- "XX 부분 제거" → trim으로 해당 구간 제거
- "XX 확대", "XX 줌인" → crop+scale + zoompan 트랜지션 (반드시 부드러운 전환)
- "XX 강조" → video_spotlight (나머지 어둡게) 또는 video_highlight (테두리)
- "XX 블러", "XX 가리기" → video_blur
- "빨리감기", "배속" → video_speed
- "페이드" → video_fade
- "텍스트 추가", "자막" → SRT 파일 생성 + FFmpeg subtitles 필터

### 5.5단계: 자막 워크플로우

자막은 **ASS 파일로 분리**하여 키워드 컬러 강조 + 페이드 전환을 지원합니다.

#### ASS 파일 생성
1. 세그먼트별 duration을 `ffprobe`로 확인하여 누적 시간 계산
2. 각 구간에 맞는 자막 텍스트 작성 (핵심 키워드에 컬러 태그 적용)
3. ASS 파일 저장: `/tmp/playwright-videos/{영상명}.ass`

**자막 텍스트 스타일 가이드:**
- **랜딩페이지/마케팅용**: 기능 설명이 아닌 **특장점/가치 중심** 작성
  - BAD: "가드레일 생성 - 이름 및 설명 입력"
  - GOOD: "다양한 {\c&H00FFFF&}규칙 기반 가드레일{\c&HFFFFFF&}을 손쉽게 생성할 수 있습니다"
- **가이드/튜토리얼용**: 단계별 조작 설명
- **내부 데모용**: 기능명 + 간단한 설명

**키워드 컬러 태그:**
- `{\c&H00FFFF&}키워드{\c&HFFFFFF&}` — 노란색 (기능명, 주요 개념)
- `{\c&H5050FF&}키워드{\c&HFFFFFF&}` — 빨간 계열 (경고, 차단 등)

#### ASS 파일 템플릿
```ass
[Script Info]
Title: Demo Subtitle
ScriptType: v4.00+
PlayResX: 1440
PlayResY: 900

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Default,NanumGothic Bold,30,&H00FFFFFF,&H000000FF,&H00000000,&H00000000,1,0,0,0,100,100,0.5,0,1,0,1,2,20,20,10,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
Dialogue: 0,0:00:00.00,0:00:05.00,Default,,0,0,0,,{\fad(250,250)}자막 텍스트 {\c&H00FFFF&}키워드 강조{\c&HFFFFFF&} 예시
```

#### 자막 번인 (ASS → 비디오)
```bash
# 한글 폰트 필요: apt-get install -y fonts-nanum
# 하단 반투명 바(50px) + ASS 자막 오버레이
ffmpeg -y -i concat_nosub.webm \
  -vf "drawbox=x=0:y=ih-50:w=iw:h=50:color=black@0.65:t=fill,ass=subtitle.ass" \
  -c:v libvpx -b:v 2M -r 25 -an output_with_sub.webm
```

**스타일 사양:**
- 폰트: NanumGothic Bold, 30pt
- 하단 반투명 바: 높이 50px, 검정 65% 불투명
- MarginV: 10 (바 내 수직 중앙 정렬)
- 페이드 전환: 250ms in/out (`{\fad(250,250)}`)
- 키워드 강조: 시안(노란) 컬러 `{\c&H00FFFF&}`

**중요**: 자막 번인 전의 원본(`concat_nosub.webm`)은 반드시 보존. 자막 수정 시 이 파일에서 다시 번인.

### 5.7단계: 줌아웃 트랜지션 (선택)

줌인된 구간이 끝나고 일반 화면으로 돌아갈 때, 줌아웃 트랜지션을 추가하면 더 자연스럽습니다.

```bash
# 줌아웃: 확대된 상태에서 일반 상태로 (2x → 1x)
ffmpeg -y -loop 1 -i zoomed_last_frame.png \
  -filter_complex "zoompan=z='max(2-on*0.125,1)':x='TARGET_X*max(1-on/8.0,0)':y='TARGET_Y*max(1-on/8.0,0)':d=8:fps=25:s=1440x900" \
  -t 0.32 -c:v libvpx -b:v 2M -r 25 -an zoom_out.webm
```

줌아웃은 선택 사항이며, 줌인보다 시각적 중요도가 낮아 생략해도 됩니다.

### 6단계: 클립 합치기

여러 클립을 만들었다면 합칩니다.

**중요**: `video_concat`은 동일 코덱/해상도가 필요합니다. 코덱이 다르면 FFmpeg로 재인코딩 후 합칩니다:
```bash
ffmpeg -y -i clip.webm -c:v libvpx -b:v 1M -r 25 -s 1440x900 -an clip_enc.webm
```

**concat 결과물 명명 규칙:**
- `concat_nosub.webm` — 자막 없는 원본 (보존)
- `{영상명}_final.webm` — 자막 포함 최종본

### 6.5단계: 최종 영상 검증

편집 완료된 영상을 **1초 간격 프레임 추출**로 최종 검증합니다.

**검증 항목:**

| 항목 | 확인 방법 | 실패 시 |
|------|----------|--------|
| 첫 프레임 | 로그인/빈 화면이 아닌 시나리오 시작 화면인지 | 앞 트림 추가 |
| 마지막 프레임 | 의미 있는 결과 화면인지 (빈 화면/에러 아닌지) | 뒤 트림 추가 |
| 이어붙인 지점 | 컷 전후 프레임이 자연스럽게 연결되는지 | 정지 프레임 삽입 |
| 에러 화면 없음 | 모든 프레임에 "Backend Required" 등 에러 없는지 | 재녹화 요청 |
| 대기 구간 잔존 | 연속 3+초 동일 화면이 남아있지 않은지 | 추가 SKIP 처리 |
| 자막 가독성 | 하단 바 + 자막이 내용을 가리지 않는지 | 자막 타이밍/위치 조정 |
| 총 길이 적정성 | 시나리오 예상 시간의 ±50% 이내인지 | 추가 편집 필요 여부 판단 |

**검증 프로세스:**
```
1. video_info → 최종 영상 길이 확인
2. 1초 간격으로 video_frame 추출 (병렬)
3. Read tool로 전체 프레임 시각 확인
4. 위 표의 검증 항목 체크
5. 문제 발견 시 → 해당 구간 재편집
6. 문제 없으면 → PASS → 포맷 변환
```

### 7단계: 포맷 변환 및 결과 보고

```
video_convert(format="mp4", quality="high") → MP4 변환
```

**최종 산출물 목록:**
| 파일 | 용도 |
|------|------|
| `{영상명}_final.webm` | 최종 WebM (자막 포함) |
| `{영상명}_final.mp4` | 최종 MP4 (자막 포함) |
| `{영상명}.srt` | 자막 파일 (수정 가능) |
| `concat_nosub.webm` | 자막 없는 원본 (자막 재번인용) |

```markdown
## 편집 결과

| 항목 | 원본 | 편집 후 |
|------|------|---------|
| 길이 | Xs | Ys |
| 크기 | X MB | Y MB |
| 포맷 | WebM | WebM + MP4 |

### 적용된 편집
1. (적용한 편집 단계 요약)

### 파일
- WebM: `/tmp/playwright-videos/xxx_final.webm`
- MP4: `/tmp/playwright-videos/xxx_final.mp4`
- 자막: `/tmp/playwright-videos/xxx.srt`
```

## 주의사항

1. **항상 프레임을 보면서 편집** — blind 편집 금지, 매 단계 `video_frame` + `Read`로 확인
2. **원본 보존** — 원본 파일은 절대 덮어쓰지 않음, 항상 새 파일로 출력
3. **중간 파일 정리** — 편집 완료 후 임시 클립 파일 삭제. 단, **자막 없는 concat 원본(concat_nosub.webm)은 보존**하여 자막 재번인이 가능하도록 함
4. **코덱 통일** — concat 전 모든 클립을 동일 코덱(libvpx)으로 재인코딩
5. **zoompan은 정지 이미지 전용** — 동영상 구간 줌인은 `video_crop`, 정지 프레임 줌인은 zoompan
6. **편집 지시가 없으면** — dedupe + 로딩 배속만 수행하고 결과 보고
7. **비디오 저장 경로** — `/tmp/playwright-videos/`에 저장
8. **페이지 전환 시 최소 1초 체류** — 새 페이지가 나타나면 시청자 인지를 위해 최소 1초 유지
9. **입력 영역은 반드시 줌인** — 관리자/워크스페이스에서 텍스트 입력 시 해당 영역을 crop+scale로 확대하여 가독성 확보
10. **줌인 시 반드시 zoompan 트랜지션** — 줌인/줌아웃이 갑자기 발생하면 화면이 잘린 것처럼 보임. 0.3초 zoompan 트랜지션을 삽입하여 자연스러운 전환 구현
11. **자막은 SRT 파일로 분리** — 자막 텍스트를 별도 `.srt` 파일로 생성하여 향후 수정 가능하도록 함. 랜딩페이지용 영상의 자막은 기능 설명이 아닌 **특장점/가치 중심**으로 작성

## 트러블슈팅 (알려진 함정)

### 1. video_trim이 부정확한 위치에서 자름
`video_trim`은 내부적으로 `-c copy`를 사용하여 키프레임 단위로만 자릅니다. WebM은 키프레임 간격이 넓어서 지정한 시간보다 몇 초 앞/뒤에서 잘릴 수 있습니다.

**해결**: 정확한 트리밍이 필요하면 MCP 대신 FFmpeg로 직접 재인코딩:
```bash
ffmpeg -y -ss {start} -to {end} -i input.webm -c:v libvpx -b:v 1M -r 25 -an output.webm
```

### 2. video_frame 추출 실패 (빈 출력)
trim된 파일이나 짧은 파일에서 `-ss`가 파일 끝을 넘어가면 빈 파일이 생성됩니다.

**해결**: filter 기반 추출 사용:
```bash
ffmpeg -y -i input.webm -vf "select=gte(t\,{시간})" -frames:v 1 output.png
```

### 3. video_concat 실패 (코덱/해상도 불일치)
서로 다른 방식으로 생성된 클립(zoompan, trim, speed 등)은 코덱/해상도/fps가 다를 수 있습니다.

**해결**: concat 전 모든 클립을 통일:
```bash
ffmpeg -y -i clip.webm -c:v libvpx -b:v 1M -r 25 -s 1440x900 -an clip_enc.webm
```

### 4. dedupe 후에도 로딩 구간이 남음
프로그레스바/스피너가 프레임마다 미세하게 변하면 `mpdecimate`가 제거하지 못합니다.

**해결**: 4.5단계의 로딩 구간 배속 처리를 반드시 수행. 프레임 확인 시 "Generating...", "Preparing...", 스켈레톤 바가 보이면 해당 구간을 4배속으로 압축.
