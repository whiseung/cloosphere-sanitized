# Cloosphere Code Interpreter - Jupyter Environment

데이터 분석 프로젝트의 코드 인터프리터 실행 환경.

## 빌드 & 실행

```bash
# 빌드
docker build -t cloosphere-jupyter ./docker/jupyter

# 실행
docker run -d --name jupyter \
  -p 8888:8888 \
  -e JUPYTER_TOKEN=your-secret-token \
  cloosphere-jupyter
```

## Azure 배포 (ACI)

```bash
# ACR에 푸시
az acr build --registry <acr-name> --image cloosphere-jupyter:latest ./docker/jupyter

# ACI 실행
az container create \
  --resource-group <rg> \
  --name jupyter-cloosphere \
  --image <acr-name>.azurecr.io/cloosphere-jupyter:latest \
  --ports 8888 \
  --environment-variables JUPYTER_TOKEN=<secret-token> \
  --cpu 2 --memory 4 \
  --dns-name-label jupyter-cloosphere
```

## Cloosphere 설정

관리자 > 설정 > 코드 실행:
- **엔진**: Jupyter
- **URL**: `http://jupyter:8888` (Docker 네트워크) 또는 `http://<host>:8888`
- **인증**: Token
- **토큰**: 위에서 설정한 `JUPYTER_TOKEN` 값

## 포함 패키지

| 패키지 | 용도 |
|--------|------|
| pandas | 데이터 분석 |
| numpy | 수치 연산 |
| scipy | 과학 계산 |
| scikit-learn | 머신러닝 |
| matplotlib | 차트 (fallback) |
| seaborn | 통계 시각화 (fallback) |
| plotly | 인터랙티브 차트 (기본) |
| openpyxl | Excel 읽기/쓰기 |
| xlrd | 구버전 xls 읽기 |
