# 제3자 구성 요소 / Third-party components

TONE ROOM 코드는 MIT 라이선스입니다. 배포하는 앱(.app/.dmg)에는 아래 구성 요소가 함께 들어갑니다.

| 구성 요소 | 용도 | 라이선스 | 출처 |
|---|---|---|---|
| FFmpeg 7.1 (imageio-ffmpeg 패키지의 정적 빌드) | 영상 디코딩·인코딩 | **GPL v2+** (libx264·libx265 포함 빌드) | https://ffmpeg.org · https://github.com/imageio/imageio-ffmpeg |
| OpenCV (opencv-python-headless) | 프레임 보정 연산 | Apache 2.0 | https://github.com/opencv/opencv-python |
| NumPy | 배열 연산 | BSD-3-Clause | https://numpy.org |
| FastAPI · Starlette · Uvicorn · Pydantic | 로컬 서버 | MIT / BSD-3-Clause | https://fastapi.tiangolo.com |
| pywebview | 앱 창 | BSD-3-Clause | https://github.com/r0x0r/pywebview |
| Next.js · React | 화면 | MIT | https://nextjs.org |
| Tailwind CSS · shadcn/ui · Base UI · Framer Motion · lucide | 화면 구성 요소 | MIT / ISC | 각 프로젝트 저장소 |
| JetBrains Mono | 글꼴 | OFL 1.1 | https://github.com/JetBrains/JetBrainsMono |
| Python | 런타임 | PSF License | https://python.org |

FFmpeg는 GPL로 배포되는 빌드라, 이를 포함한 앱 배포본 전체에 GPL 조건이 함께 적용됩니다. FFmpeg 소스는 위 출처에서 받을 수 있습니다.
