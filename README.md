# ApplicationTest

Indi Store의 저장소 연동, APK 다운로드, 검증 및 설치를 확인하는 작은 Android 테스트 앱입니다.

- 패키지: `dev.indi.applicationtest`
- 버전: `1.0.1` (`versionCode=2`)
- Android 8.0(API 26) 이상, compile/target SDK 36
- 네트워크·사진·계정 권한 없음
- 화면에서 버전·패키지를 확인하고 **실행 확인** 버튼을 누를 수 있습니다.

## 빌드

Java 17 이상과 Android SDK 36을 설치한 뒤:

```sh
./gradlew assembleRelease lintRelease
```

Windows는 `gradlew.bat assembleRelease lintRelease`를 사용합니다.
APK는 `app/build/outputs/apk/release/app-release.apk`에 생성됩니다.

이 저장소는 **연동 테스트 전용**입니다. release 빌드도 개발용 debug 인증서로 서명합니다. 정식 앱 배포용 서명으로 사용하지 마세요. 동일 앱의 업데이트 테스트는 같은 키를 유지하고 versionCode를 올려야 합니다.

## 스토어 등록

릴리스에는 빌드한 APK와 실제 APK에서 추출한 `store-manifest.json`을 함께 올립니다. `store-metadata.json`은 앱 표시 정보이며, 패키지·버전·크기·SHA-256·인증서 지문은 APK 검사로 생성합니다.

```sh
mkdir -p release
cp app/build/outputs/apk/release/app-release.apk release/ApplicationTest-1.0.1.apk
python scripts/store_manifest.py --apk release/ApplicationTest-1.0.1.apk --metadata store-metadata.json --output release/store-manifest.json
```

manifest 생성 시 `ANDROID_HOME`이 실제 Android SDK 경로를 가리켜야 합니다.

Indi Store 관리자에서 `AIProject-k/ApplicationTest`를 **연동**하면 동기화 대상이 됩니다. **비활성화**는 연동을 유지하면서 관리자 기본 목록과 스토어 앱 목록에서 숨깁니다. 비활성 항목 보기에서 다시 활성화할 수 있습니다.
