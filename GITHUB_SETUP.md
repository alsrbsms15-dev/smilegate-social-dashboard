# GitHub Pages 자동 배포 세팅 가이드

매일 오전 8시(KST) GitHub 서버에서 자동으로 데이터를 긁어와 대시보드 HTML을 갱신하고, 팀 전체가 고정 URL로 볼 수 있게 만드는 세팅입니다. 본인 PC와 완전 분리됩니다.

**예상 소요 시간: 20~30분** (대부분 클릭 작업)

---

## 0. 준비물

- GitHub 계정 (없으면 https://github.com/signup 에서 1분 가입)
- Git for Windows (https://git-scm.com/download/win) — 기본값으로 설치 OK
- 이 폴더(`Claude Tasks`)의 파일들

## 1. GitHub에 새 리포지토리 만들기

1. https://github.com/new 접속
2. 다음과 같이 입력:
   - **Repository name**: `smilegate-social-dashboard`
   - **Public/Private**: **Public** 선택 ✅ (GitHub Pages 무료 티어는 public만 지원)
   - **Initialize this repository with**: 체크박스 모두 **해제** (README, .gitignore, license 모두 안 함)
3. 하단 **Create repository** 클릭
4. 다음 화면에 나오는 **HTTPS URL**을 복사해두세요. 예: `https://github.com/your-username/smilegate-social-dashboard.git`

## 2. 로컬 폴더를 git 리포지토리로 초기화

명령 프롬프트 열고:

```
cd "Documents\Claude Tasks"
git init -b main
git add .
git commit -m "initial commit"
git remote add origin https://github.com/your-username/smilegate-social-dashboard.git
git push -u origin main
```

**주의사항:**
- `your-username` 부분을 본인 GitHub 사용자명으로 치환하세요
- 처음 push할 때 GitHub 로그인 창이 뜨면 브라우저 인증 진행
- `smilegate-sns-credentials.yaml`은 `.gitignore`에 등록되어 있어 **자동으로 제외**됩니다 (API 키 안전)
- 에러 나면 `git config --global user.email "alsrbsms15@gmail.com"` 먼저 실행

## 3. GitHub Secrets에 API 키 등록

API 키는 코드에 넣으면 안 되니까, GitHub의 암호화 저장소에 저장합니다.

1. 방금 만든 리포 페이지에서 상단 **Settings** 탭 클릭
2. 왼쪽 메뉴 **Secrets and variables** → **Actions**
3. 우측 상단 초록색 **New repository secret** 버튼
4. 다음을 입력:
   - **Name**: `YOUTUBE_API_KEY`
   - **Secret**: `AIzaSyDHKlbzsEg0QAFLM6Ef7XtJOPx3E4RX7FA`
5. **Add secret** 클릭

나중에 X, Meta 크레덴셜 받으면 동일 방식으로 `X_BEARER_TOKEN`, `META_SYSTEM_TOKEN`을 추가하시면 돼요.

## 4. GitHub Pages 활성화

1. 리포 **Settings** 탭 → 왼쪽 **Pages**
2. **Source**: "Deploy from a branch" 선택
3. **Branch**: `main` / `/ (root)` / **Save**
4. 1~2분 기다리면 페이지 상단에 초록색 박스로 URL이 뜹니다:
   ```
   Your site is live at https://your-username.github.io/smilegate-social-dashboard/
   ```

## 5. 첫 실행 테스트

스케쥴(cron) 대기하지 말고 즉시 수동 실행해서 동작 확인하세요.

1. 리포 **Actions** 탭
2. 왼쪽 **Refresh Smilegate Social Dashboard** 워크플로우 클릭
3. 우측 **Run workflow** → **Run workflow** 버튼
4. 20~40초 후 초록 체크 ✅가 뜨면 성공
5. 4단계에서 나온 URL 열어서 실제 숫자가 표시되는지 확인

## 6. 팀 공유

4단계의 URL (`https://your-username.github.io/smilegate-social-dashboard/`)을 Slack/Confluence/Notion/팀 메일에 뿌리면 끝. 매일 오전 8시(KST) 자동 갱신되고, 팀원들은 그냥 페이지 새로고침만 하면 됩니다.

Confluence/Notion에 iframe으로도 박을 수 있어요:
```html
<iframe src="https://your-username.github.io/smilegate-social-dashboard/"
        width="100%" height="2400" frameborder="0"></iframe>
```

---

## 자주 묻는 질문

**Q. Windows Task Scheduler는 이제 끄나요?**
→ 네, 꺼도 됩니다. 굳이 본인 PC에서도 돌릴 이유 없어요. 스케쥴러 → 작업 **사용 안 함**으로 바꾸시면 됩니다. (수동 검증용으로는 남겨두셔도 됨)

**Q. 내 API 키가 GitHub에 노출되는 거 아닌가요?**
→ 아뇨. Secrets는 암호화 저장되어 본인조차 다시 읽을 수 없고, 로그에서도 자동 마스킹됩니다. `.gitignore`에 의해 크레덴셜 YAML 파일도 애초에 업로드되지 않고요.

**Q. 팀원이 숫자가 하루 지난 값인 걸 어떻게 알죠?**
→ 대시보드 상단에 "Updated YYYY-MM-DD" 뱃지가 있어서 마지막 갱신일 표시됩니다.

**Q. 매일 8시인데 9시, 10시까지 안 갱신되면?**
→ GitHub Actions cron은 무료 티어 특성상 5~30분 지연될 수 있어요. 급할 땐 Actions 탭에서 **Run workflow** 수동 버튼 누르면 즉시 실행.

**Q. 나중에 X/Meta API 들어오면?**
→ Secrets에 토큰만 추가하면 스크립트가 자동으로 그 플랫폼도 갱신합니다 (fetch_social_stats.py에 연동 로직 추가는 별도 필요).
