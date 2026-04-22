# 소셜 대시보드 자동화 스크립트

`fetch_social_stats.py` — 매일 아침 YouTube/X/Instagram/Facebook/Discord의 공식 채널 지표를 가져와 `latest-dashboard.html`을 최신 숫자로 갱신합니다. **본인 PC에서 실행**하므로 Cowork 샌드박스의 네트워크 제약을 받지 않습니다.

## 한 번만 하면 되는 세팅 (약 10분)

### 1. Python 설치 확인

명령 프롬프트(`Win + R` → `cmd`)를 열고:

```
python --version
```

`Python 3.9` 이상이 나오면 OK. 없으면 https://www.python.org/downloads/ 에서 설치 (설치할 때 "Add Python to PATH" 체크박스 반드시 켜세요).

### 2. 의존성 설치

명령 프롬프트에서:

```
pip install pyyaml
```

`Successfully installed PyYAML-...` 메시지가 나오면 완료.

### 3. 한 번 수동 실행해서 잘 작동하는지 확인

```
cd "Claude Tasks\automation"
python fetch_social_stats.py
```

정상이면 다음과 비슷하게 출력됩니다:

```
[10:30:12] YouTube: API key loaded — fetching 5 channels
[10:30:13]   ✓ epic7/@EpicSeven → 823,000 subs
[10:30:14]   ✓ epic7/@EpicSevenKR → 145,000 subs
...
[10:30:20] Done. 5 live channels, 0 errors, 4 platforms pending.
[10:30:20] Total combined live followers: 1,234,567
```

스크립트가 끝나면 같은 폴더 상위에 있는 `latest-dashboard.html`이 실제 숫자로 갱신됩니다. 더블클릭해서 브라우저로 열어 확인해보세요.

### 4. Windows Task Scheduler로 매일 자동 실행 걸기

1. `Win + S` → "작업 스케줄러" 또는 "Task Scheduler" 검색 → 실행
2. 오른쪽 **"기본 작업 만들기..." (Create Basic Task...)** 클릭
3. 이름: `Smilegate Social Dashboard Refresh`
4. 트리거: **매일 (Daily)** → 오전 **8:00** (또는 확인 시간대 직전)
5. 작업: **프로그램 시작 (Start a program)**
6. 프로그램: `python` (또는 `pythonw.exe` 전체 경로 — 창 안 뜨게 하려면 이걸 쓰세요)
7. 인수 추가: `fetch_social_stats.py`
8. 시작 위치 (**중요**): 이 README가 있는 `automation` 폴더의 전체 경로. 예:
   `C:\Users\minkyuk\Documents\Claude Tasks\automation`
9. 완료 후 **속성** 열어서:
   - "사용자의 로그온 여부에 관계없이 실행" 체크 (PC 켜져 있기만 하면 됨)
   - "가장 높은 수준의 권한으로 실행" 체크
   - "조건" 탭 → "컴퓨터를 AC 전원으로 사용할 때만 이 작업 시작" **체크 해제** (노트북인 경우)

### 5. (팀 공유용) `latest-dashboard.html` 링크 뿌리기

이 폴더가 OneDrive/Google Drive 등에 동기화되는 폴더라면, 팀원들에게 `latest-dashboard.html` 의 공유 링크를 주면 매일 오전 8시에 자동 갱신된 대시보드를 볼 수 있습니다. Confluence/Notion에 iframe으로 임베드해도 됩니다.

---

## 무엇이 어떻게 되는지

- **읽는 파일**: `../smilegate-sns-credentials.yaml`
- **쓰는 파일**:
  - `../dashboard-snapshots/YYYY-MM-DD.json` — 당일 원본 데이터
  - `../dashboard-snapshots/YYYY-MM-DD.html` — 당일 스냅샷 HTML (히스토리 보관)
  - `../dashboard-snapshots/history.json` — 90일 롤링 추이 기록
  - `../latest-dashboard.html` — **항상 최신 상태**인 공유용 파일

## 플랫폼별 상태

| 플랫폼 | 현재 | 자격 증명 추가되면 |
|---|---|---|
| YouTube | ✓ 연동됨 (구독자/조회수/영상수/최근영상) | — |
| X | 대기 | bearer_token 추가 시 바로 작동 |
| Facebook | 대기 | meta.system_token + pages 추가 시 바로 작동 |
| Instagram | 대기 | meta.system_token + instagram_business 추가 시 바로 작동 |
| Discord | 대기 | bot_token + guilds 추가 시 바로 작동 |

새 플랫폼 API 키가 들어오는 대로 Claude에게 말씀주시면 스크립트에 연동 로직을 추가해드립니다 (현재는 YouTube 파트만 구현되어 있고 나머지는 스텁 상태).

## 문제가 생겼을 때

- `ModuleNotFoundError: No module named 'yaml'` → `pip install pyyaml` 다시 실행
- `HTTP 403: The request cannot be completed because you have exceeded your quota` → YouTube API 일일 할당량 초과. 구글 클라우드 콘솔에서 할당량 확인 (5개 채널 기준 하루 10회 호출해도 0.5%라 거의 발생 불가)
- `HTTP 400: API key not valid` → 키가 잘못됐거나 YouTube Data API v3이 활성화되지 않음. 클라우드 콘솔에서 확인
- 작업 스케줄러에서 실행했는데 대시보드가 갱신 안 됨 → 작업 스케줄러 "기록" 탭 확인 → 작업 상태/마지막 실행 결과 보기
- 그 외 → JSON 스냅샷 파일의 `apiErrors` 필드에 실패 사유가 찍힙니다
