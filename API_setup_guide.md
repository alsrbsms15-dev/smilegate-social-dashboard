# 소셜 대시보드 API 연동 가이드
**Smilegate 콘텐츠마케팅팀 · 게임 공식 SNS 지표 대시보드**

이 문서는 대시보드에 실시간 팔로워/구독자 수와 게시물 지표를 연동하기 위해 각 플랫폼에서 준비해야 할 자격 증명을 정리한 것입니다. 마케터 본인이 직접 발급할 수 있는 것도 있고, **공식 채널 운영팀(채널 소유 권한을 가진 담당자) 또는 IT/개발팀 협조가 필요한 것**도 있어 항목별로 명시했습니다.

---

## 한눈에 보기

| 플랫폼 | 팔로워/구독자 수 | 최근 게시물 | 참여도(좋아요·댓글) | 비용 | 채널 소유 권한 필요? |
|---|---|---|---|---|---|
| YouTube | O (공개) | O (공개) | O (공개) | 무료 (10,000 units/일) | X — API 키만 있으면 됨 |
| X (Twitter) | O | 제한적 | 제한적 | **유료 (Basic $200/월부터)** | X — 앱 등록만 하면 됨 |
| Instagram | O | O | O | 무료 | **O — 비즈니스 계정 + FB 페이지 연결** |
| Facebook | O | O | O | 무료 | **O — 페이지 Admin 권한** |
| Discord | O (서버 멤버 수) | X (봇 필요) | X (봇 필요) | 무료 | **봇 초대 권한 필요** |

> 가장 **간단한 것부터**: YouTube → Facebook → Instagram → Discord → X 순으로 진행하시는 걸 추천드립니다. X는 비용 승인이 필요하니 가장 마지막.

---

## 1. YouTube Data API v3

**얻을 수 있는 값**: 구독자 수, 총 조회수, 영상 개수, 각 영상 제목/조회수/좋아요/댓글 수.

### 필요한 것
- Google Cloud 프로젝트 (본인 계정으로 생성 가능)
- YouTube Data API v3 활성화
- API Key 1개

### 발급 절차 (약 10분)
1. https://console.cloud.google.com 접속 → 프로젝트 생성 (예: `smilegate-sns-dashboard`)
2. 왼쪽 메뉴 → **APIs & Services → Library** → "YouTube Data API v3" 검색 → **Enable**
3. **Credentials → Create Credentials → API Key** 클릭
4. 발급된 키를 복사 → 보안을 위해 **HTTP referrer 제한** 설정 권장
5. (선택) **Quotas** 페이지에서 일일 한도 확인 — 기본 10,000 units/일, 팔로워 조회 호출당 1 unit 정도라 충분

### 제가 받아야 할 것
```
YT_API_KEY = ***
```
에픽세븐 2개 + CZN 1개 + Lord Nine 2개 = 총 5개 채널 조회해도 일일 한도의 1% 미만입니다.

---

## 2. X (구 Twitter) API v2

**얻을 수 있는 값**: 팔로워 수, 팔로잉 수, 총 트윗 수, 최근 트윗 및 좋아요/리포스트 수.

### 중요: 유료화된 플랫폼
- 2023년부터 **모든 API 접근이 유료**입니다.
- **Basic 티어**: $200/월 (읽기 10,000 트윗/월, 계정 정보 조회 포함)
- **Pro 티어**: $5,000/월 (필요하지 않음)
- Free 티어는 **쓰기 전용**이라 팔로워 조회 불가.

### 필요한 것
- X 개발자 계정
- Basic 이상 구독
- App 생성 후 **Bearer Token** 1개

### 발급 절차
1. https://developer.x.com 접속 → 개발자 계정 신청 (본인 X 계정으로)
2. **Subscribe to Basic** — 법인 카드 등록 필요
3. Dashboard → Projects & Apps → Create App (예: `smilegate-dashboard`)
4. App 상세 → **Keys and Tokens** → Bearer Token 생성 → 복사
5. User lookup endpoint(`GET /2/users/by/username/:username`) 사용 가능한지 확인

### 제가 받아야 할 것
```
X_BEARER_TOKEN = ***
```

### 권장 사항
- **비용 승인이 필요한 항목**이라 팀장님/재무 보고 먼저 권장드립니다.
- 대안: Basic 가입 전까지는 **수동 입력 모드**로 운영 (주 1회 마케터가 직접 숫자 갱신) → 연말에 연간 $2,400 vs 수동 운영 비용 비교 후 결정.

---

## 3. Instagram Graph API

**얻을 수 있는 값**: 팔로워 수, 팔로잉 수, 미디어 개수, 각 게시물 좋아요/댓글/도달/임프레션.

### 까다로운 점: 비즈니스 계정 + Facebook 페이지 연결 필수
- 개인 계정으로는 API 접근 **불가**.
- Instagram 계정이 **Business** 또는 **Creator** 계정이어야 함.
- 해당 Instagram 계정이 **공식 Facebook 페이지에 연결**되어 있어야 함.

### 필요한 것
- Meta for Developers 계정 (본인 FB 계정으로 생성 가능)
- App 생성 (Business type)
- **Instagram Graph API** 권한 추가
- **Page Access Token** (각 게임 FB 페이지 Admin 권한을 가진 분이 승인해야 함)
- `instagram_basic`, `instagram_manage_insights`, `pages_read_engagement` 권한

### 발급 절차
1. https://developers.facebook.com 접속 → Create App → Type: **Business**
2. App Dashboard → Add Product → **Instagram Graph API** 추가
3. **System User** 생성 (장기 토큰 발급용) — Business Manager 필요
4. Business Manager → System User → Generate Token →
   - 토큰 타입: Long-lived
   - 권한: `instagram_basic`, `instagram_manage_insights`, `pages_show_list`, `pages_read_engagement`
5. **Epic Seven Global / CZN / Lord Nine 각 페이지** 에 System User를 Admin/Analyst로 추가해야 함 → 각 페이지 운영팀에 요청

### 제가 받아야 할 것
```
META_APP_ID        = ***
META_APP_SECRET    = ***
META_SYSTEM_TOKEN  = ***         (Long-lived system user token)
IG_BUSINESS_IDS = {
  epic7:   '<ig_business_id>',
  czn:     '<ig_business_id>',
  l9:      '<ig_business_id>'     (※ Lord Nine Instagram 확인 필요 — 아래 참조)
}
```

### ⚠️ 정책 주의
- Instagram API 토큰은 **60일마다 자동 만료**되며, System User 토큰만 "never expires"로 설정 가능. 반드시 System User 경로로 발급해야 재발급 수고가 없습니다.

---

## 4. Facebook Graph API

**얻을 수 있는 값**: 페이지 팔로워 수, 좋아요 수, 최근 포스트 및 인게이지먼트.

Instagram과 **동일한 Meta 앱 하나로** 처리 가능합니다 (권장).

### 필요한 것
- 위 3번에서 만든 Meta App
- 각 페이지의 **Page Access Token** 또는 System User Token
- `pages_read_engagement`, `pages_show_list` 권한

### 발급 절차
Instagram과 동일. System User Token 하나로 FB 페이지 + IG Business 모두 조회 가능합니다.

### 제가 받아야 할 것
```
FB_PAGE_IDS = {
  'epic7-global': '<page_id>',
  'epic7-kr':     '<page_id>',
  'czn':          '<page_id>',
  'l9-kr':        '<page_id>',
  'l9-sea':       '<page_id>'
}
```
(이 ID는 각 페이지 Admin이 페이지 Settings → About → Page ID에서 확인 가능)

---

## 5. Discord

**얻을 수 있는 값**: 서버 멤버 수(온라인/전체), 채널 목록. 공지 수, 참여도는 봇 설치해야 가능.

### 간단 옵션 (권장): Server Widget
- 서버 설정에서 **Widget** 만 활성화하면 API 키 없이 `GET https://discord.com/api/guilds/{guild_id}/widget.json` 로 온라인 멤버 수와 초대 링크 조회 가능.
- 단점: **총 멤버 수는 안 나옴**, 온라인 멤버만 표시됩니다.

### 풀 옵션: 봇 설치
- 총 멤버 수, 역할별 분포, 메시지 지표까지 원하면 봇 필요.
- 각 Discord 서버 관리자가 봇을 **초대**해야 함 (`Manage Server` 권한).

### 발급 절차 (풀 옵션 기준)
1. https://discord.com/developers/applications 접속 → New Application (예: `smilegate-dashboard`)
2. Bot 탭 → Add Bot → **Token** 복사 (1회만 표시)
3. OAuth2 → URL Generator → Scopes: `bot` / Permissions: `View Channels`, `Read Message History`
4. 생성된 URL을 각 서버 관리자에게 보내 **초대 승인** 받기
5. 봇 초대되면 Gateway 로 접속해 Guild member count 조회 가능

### 제가 받아야 할 것
```
DISCORD_BOT_TOKEN = ***
DISCORD_GUILD_IDS = {
  'epic7':  '<guild_id>',
  'czn':    '<guild_id>',
  'l9-sea': '<guild_id>'
}
```

> Discord는 **Widget 옵션부터 시작**해서 온라인 멤버 수만 먼저 띄우고, 마케팅 리포트 용도로 총 멤버 수가 꼭 필요해지면 봇 설치로 업그레이드하는 걸 추천드립니다.

---

## 6. 확인이 필요한 채널 (Lord Nine)

공개 검색으로 찾지 못한 채널이 있습니다. 내부 운영팀에 확인 부탁드립니다.

| 게임 | 플랫폼 | 현황 |
|---|---|---|
| Lord Nine | X (Twitter) | 공식 계정 URL 미확인 — 내부 채널 담당자에게 문의 필요 |
| Lord Nine | Instagram | 공식 계정 URL 미확인 — 내부 채널 담당자에게 문의 필요 |

(에픽세븐과 CZN은 5개 플랫폼 모두 공식 계정을 확인했습니다.)

---

## 다음 단계 제안

1. **이번 주**: 제가 받아야 할 것 항목을 정리해서 IT/운영팀에 API 키 발급 요청
   - YouTube만 먼저 발급해도 구독자 수 데이터는 즉시 연동 가능
2. **다음 주**: Meta(Facebook + Instagram) 앱 하나로 묶어서 승인 요청
   - 각 페이지 Admin 승인이 병목 — 대략 3~5영업일
3. **2주 내**: Discord Widget 활성화 요청 (서버 관리자가 1분이면 가능)
4. **X API는 유료 승인 후**: Basic 티어 구독 결제 완료되면 연동
5. **Lord Nine X/IG 확인** 후 대시보드에 추가

키가 확보되는 플랫폼부터 순차적으로 대시보드에 연동해드릴 수 있습니다. 받은 자격 증명은 **아티팩트 내 암호화 스토리지**에 저장해서 다음 열람 시 자동으로 라이브 데이터가 반영되도록 작업하겠습니다.

---

## 키 전달 시 형식 예시

나중에 키를 공유해주실 때 아래 형식으로 한 번에 주시면 바로 연동 작업 들어갈 수 있습니다.

```yaml
# smilegate-sns-credentials.yaml
youtube:
  api_key: "AIza..."
x:
  bearer_token: "AAAAAAAA..."
meta:
  app_id: "1234567890"
  app_secret: "..."
  system_token: "EAA..."
  pages:
    epic7_global: "page_id_here"
    epic7_kr: "page_id_here"
    czn: "page_id_here"
    l9_kr: "page_id_here"
    l9_sea: "page_id_here"
  instagram_business:
    epic7_global: "ig_id_here"
    czn: "ig_id_here"
    # l9: 계정 확인 후 추가
discord:
  bot_token: "..."
  guilds:
    epic7: "..."
    czn: "..."
    l9_sea: "..."
```

> **보안 주의**: 이 파일을 이메일/Slack 본문에 그대로 붙여넣지 마시고, 비밀번호 관리 서비스(1Password 등) 또는 사내 시크릿 저장소를 이용해주세요.
