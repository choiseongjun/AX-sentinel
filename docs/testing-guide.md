# AX Sentinel 실행 및 테스트 가이드

이 문서는 LocalStack EKS에 배포된 AX Sentinel을 실행하고 전체 업무 흐름을
검증하는 절차를 설명한다. 기본 접속 주소는
<http://localhost:8081>이다.

## LocalStack EKS Keycloak 로그인

`http://localhost:8081`을 열고 `Keycloak로 로그인`을 누른다. Keycloak
로그인 화면에서 다음 로컬 개발 계정을 사용한다. 비밀번호는 Git에 저장하지
않고 `.local/keycloak-credentials.json`에 무작위로 생성한다.

| 역할 | 아이디 | 자격 증명 파일 필드 | 주요 시험 |
| --- | --- | --- | --- |
| 시스템 관리자 | `admin` | `systemAdminPassword` | 전체 메뉴와 관리 기능, 첫 로그인 TOTP 등록 |
| 운영 관리자 | `manager` | `managerPassword` | AI 분석과 조치안 승인·반려 |
| 현장 작업자 | `worker` | `workerPassword` | 작업 체크리스트·증빙·복구 완료 |

```powershell
Get-Content .local\keycloak-credentials.json
```

좌측 하단 사용자 카드를 누르면 Keycloak 로그아웃을 거쳐 다른 역할로 다시
로그인할 수 있다. 로컬 계정과 비밀번호는 개발 전용이며 운영 환경에서
사용하지 않는다.

## 1. 사전 상태 확인

PowerShell에서 프로젝트 디렉터리로 이동한다.

```powershell
Set-Location C:\pj\AXSentinel

docker info
kubectl get deployments -n ax-sentinel
kubectl get pods -n ax-sentinel
```

모든 Deployment의 `READY`가 `1/1`이고 Pod가 `Running`이면 정상이다.

서비스가 내려가 있다면 다음 명령으로 LocalStack EKS에 다시 배포한다.

```powershell
.\scripts\local-eks.ps1 Deploy
```

## 2. 웹 기반 전체 업무 흐름

### 운영 관리자

1. <http://localhost:8081>에 접속한다.
2. `Keycloak로 로그인`을 누르고 `manager` 계정으로 로그인한다.
3. `장애 관리`에서 `가상 이상 발생`을 누른다.
4. 생성된 장애의 상세 화면으로 이동한다.
5. `AI 원인 분석 실행`을 누른다.
6. 위험도, 신뢰도, 원인 후보, 근거, 권장 조치와 분석 감사 정보를 확인한다.
7. `전문가 검토함`에서 담당자를 배정하고 검토 메모를 등록한다.
8. 장애 상세에서 조치안을 승인하거나 수정 후 승인한다.
9. `작업 티켓`에 체크리스트가 생성되었는지 확인한다.

분석 감사 정보에는 AI 제공자, 모델 ID, 프롬프트 버전과 해시, RAG 제공자,
검색 문서 버전, Guardrail 결과, 요청 ID와 토큰 사용량이 포함된다.

### 현장 작업자

1. 로그아웃 후 `현장 작업자`로 다시 로그인한다.
2. `작업 티켓`에서 모든 체크리스트를 선택한다.
3. 현장 증적 이미지를 첨부한다.
4. 현장 메모와 실제 장애 원인을 입력한다.
5. AI 원인 정확도와 조치안 유용성을 평가한다.
6. `시험 가동 후 정상 복구 확인`을 선택한다.
7. `작업 완료 등록`을 누른다.

체크리스트, 증적 이미지, 실제 원인 또는 복구 확인이 누락되면 완료 요청이
거부되는 것이 정상이다.

## 3. 실시간 센서 데이터 실행

다음 프로세스는 1초마다 센서값을 전송하며 약 20%의 확률로 임계값 초과값을
생성한다.

```powershell
Set-Location C:\pj\AXSentinel

.\scripts\telemetry-producer.ps1 `
  -Endpoint "http://localhost:8081/api/v1/telemetry" `
  -IntervalMilliseconds 1000
```

웹의 `실시간 데이터` 화면에서 WebSocket 연결, 센서값 갱신, 로그 추가와
이상 상태를 확인한다. 전송을 중단하려면 해당 PowerShell에서 `Ctrl+C`를
누른다.

백그라운드 실행이 필요하면 다음 명령을 사용한다.

```powershell
$producer = Start-Process powershell `
  -WindowStyle Hidden `
  -PassThru `
  -ArgumentList @(
    "-NoProfile",
    "-ExecutionPolicy", "Bypass",
    "-File", "C:\pj\AXSentinel\scripts\telemetry-producer.ps1",
    "-Endpoint", "http://localhost:8081/api/v1/telemetry",
    "-IntervalMilliseconds", "1000"
  )

$producer.Id
```

백그라운드 프로세스 중지는 출력된 PID를 사용한다.

```powershell
Stop-Process -Id <PID>
```

## 4. AI 정답 데이터셋 평가

`manager` 또는 `admin`으로 로그인한 뒤 웹의 `문서 관리`에서
`samples/documents/bearing-maintenance.md`를 등록한다. 이어 `AI 운영 지표`
화면에서 정답 데이터셋과 평가 실행 기능을 확인한다.
Ollama 분석은 생성형 모델을 사용하므로 원인 후보 정확도는 실행마다 달라질
수 있다. 문서 검색 적중률과 해결 시간 감소율은 같은 데이터셋에서 반복
검증할 수 있다. 결정론적인 회귀 검사가 필요하면 `AI_PROVIDER=mock`으로
전환한다.

## 5. Kafka 이벤트 흐름 확인

LocalStack EKS에서는 센서·장애·분석·문서·승인·작업·피드백 상태 변화가
Kafka로 발행된다. 가장 빠른 확인 방법은 AX Sentinel 좌측 메뉴의
`Kafka 관리`를 누르는 것이다. 새 탭에서 다음 자격 증명으로 로그인한다.

| 항목 | 값 |
| --- | --- |
| 주소 | <http://localhost:8081/kafka-ui> |
| 사용자명 | `admin` |
| 비밀번호 | `.local/keycloak-credentials.json`의 `kafkaUiPassword` |

`Topics`에서는 메시지 수, partition, offset과 payload를 보고, `Consumers`에서는
`ax-sentinel-event-worker-v1`의 lag를 확인한다. 실패 이벤트는
`Topics → ax.events.dlq.v1 → Messages`에서 확인한다.

CLI로 확인하려면 먼저 broker와 토픽을 조회한다.

```powershell
kubectl get statefulset kafka -n ax-sentinel

kubectl exec -n ax-sentinel kafka-0 -- `
  /opt/kafka/bin/kafka-topics.sh `
  --bootstrap-server kafka:9092 `
  --list
```

웹에서 `실시간 데이터 → 데모 스트림 시작`을 3초 정도 실행한 뒤 중지하거나
`장애 관리 → 가상 이상 발생`을 누른다. Consumer의 offset과 lag를 확인한다.

```powershell
kubectl exec -n ax-sentinel kafka-0 -- `
  /opt/kafka/bin/kafka-consumer-groups.sh `
  --bootstrap-server kafka:9092 `
  --describe `
  --group ax-sentinel-event-worker-v1 `
  --offsets
```

`CURRENT-OFFSET`이 증가하고 `LAG`가 `0`이면 Event Worker가 메시지를
처리하고 commit한 상태다. 처리 이력은 `axsentinel-events` DynamoDB
테이블에 `event_id`, `event_type`, `topic`, `partition`, `offset`,
`producer`, `correlation_id`와 함께 저장된다.

### DLQ 동작 시험

다음처럼 envelope schema가 잘못된 JSON을 넣으면 Event Worker가 같은 offset을
3회 처리한 뒤 `ax.events.dlq.v1`로 격리하고 원본 offset을 commit한다.

```powershell
$invalidEvent = '{"unexpected":"payload","test_id":"manual-dlq-check"}'
$invalidEvent | kubectl exec -i -n ax-sentinel kafka-0 -- `
  /opt/kafka/bin/kafka-console-producer.sh `
  --bootstrap-server kafka:9092 `
  --topic ax.audit.events.v1
```

Kafka UI의 DLQ 메시지에는 `source_topic`, `source_partition`,
`source_offset`, `original_value`, `error_type`, `error_message`,
`attempts=3`이 표시된다.

## 6. 자동화 테스트

```powershell
Set-Location C:\pj\AXSentinel

.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe -m ruff check .
npm --prefix web run build
```

정상 기준:

- Python 테스트 전체 통과
- Ruff 결과 `All checks passed!`
- React/Vite 프로덕션 빌드 성공

## 7. 인증과 API 보안 확인

```powershell
$base = "http://localhost:8081"

# 인증 없는 업무 API는 401이어야 한다.
try { Invoke-WebRequest "$base/api/v1/incidents" -UseBasicParsing }
catch { $_.Exception.Response.StatusCode.value__ }

# public web client의 Password Grant는 400이어야 한다.
$body = "grant_type=password&client_id=ax-sentinel-web&username=manager&password=invalid"
try {
  Invoke-WebRequest `
    -Method Post `
    -Uri "$base/keycloak/realms/ax-sentinel/protocol/openid-connect/token" `
    -ContentType "application/x-www-form-urlencoded" `
    -Body $body `
    -UseBasicParsing
} catch { $_.Exception.Response.StatusCode.value__ }
```

인증된 전체 API 흐름은 웹에서 Authorization Code + PKCE로 로그인해
시험한다. Password Grant는 의도적으로 비활성화되어 있으므로 비밀번호로
CLI access token을 직접 발급하지 않는다.

## 8. 실제 AWS Cognito·Bedrock 시험

LocalStack EKS의 기본 AI는 호스트 Ollama이며 인증은 Keycloak이 담당한다.
실제 AWS Cognito와 Bedrock은 유효한 개발용 AWS 자격 증명과 Terraform
출력값을 현재 PowerShell 세션에 설정한 후 실행한다.

```powershell
Remove-Item Env:AWS_ENDPOINT_URL -ErrorAction SilentlyContinue
$env:COGNITO_USER_POOL_ID = "<user-pool-id>"
$env:COGNITO_CLIENT_ID = "<client-id>"
$env:BEDROCK_MODEL_ID = "<model-or-inference-profile-id>"
$env:BEDROCK_KNOWLEDGE_BASE_ID = "<knowledge-base-id>"
$env:BEDROCK_DATA_SOURCE_ID = "<data-source-id>"

.\.venv\Scripts\python.exe scripts/aws-integration-check.py
.\.venv\Scripts\python.exe scripts/aws-integration-check.py --invoke
```

`--invoke`는 실제 Bedrock 호출 비용이 발생한다. 테스트 사용자 로그인을 함께
검증하려면 `COGNITO_TEST_USERNAME`과 `COGNITO_TEST_PASSWORD`를 현재 셸에만
설정한다. 비밀번호와 토큰은 저장소에 기록하지 않는다.

## 9. Ollama 상태 확인

```powershell
ollama --version
ollama list
Invoke-RestMethod http://localhost:11434/api/tags
```

기본 모델이 없으면 다음 명령으로 설치한다.

```powershell
ollama pull hoangquan456/qwen3-nothink:4b
```

LocalStack EKS의 AI Pod에서 호스트 Ollama 연결을 확인한다.

```powershell
kubectl exec -n ax-sentinel deployment/ai-analysis-service -- `
  python -c "import urllib.request; print(urllib.request.urlopen('http://host.docker.internal:11434/api/tags').status)"
```

장애 분석 결과의 `분석 감사 정보`에 제공자 `ollama`, 모델
`hoangquan456/qwen3-nothink:4b`가 표시되면 정상이다.

## 10. 문제 해결

### Windows PowerShell 5.1에서 한글 응답이 깨지는 경우

Windows PowerShell 5.1의 `Invoke-RestMethod`는 `charset`이 없는 JSON 응답을
UTF-8이 아닌 문자셋으로 해석할 수 있다. 웹 화면에서는 정상이며, API 응답의
한국어를 다음 요청에 그대로 다시 보내는 자동화는 PowerShell 7(`pwsh`) 또는
UTF-8을 명시적으로 처리하는 Python/curl 클라이언트를 사용한다.

```powershell
kubectl logs -n ax-sentinel deployment/ai-analysis-service --tail=100
kubectl logs -n ax-sentinel deployment/incident-service --tail=100
kubectl logs -n ax-sentinel deployment/work-order-service --tail=100
kubectl logs -n ax-sentinel deployment/web --tail=100
```

웹이 열리지 않으면 Ingress와 서비스 상태를 확인한다.

```powershell
kubectl get ingress,service -n ax-sentinel
Invoke-WebRequest http://localhost:8081 -UseBasicParsing
```
