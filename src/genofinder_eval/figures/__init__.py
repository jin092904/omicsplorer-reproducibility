"""manuscript paper-ready figure 생성 (matplotlib + seaborn).

모든 figure 산출물:
    - 300dpi PDF (vector) + 300dpi PNG (raster)
    - 폰트: 본문 9pt / 라벨 10pt / 제목 11pt, sans-serif
    - colorblind-safe palette (`seaborn.color_palette("colorblind")`)
    - caption 은 별도 `.txt` 로 저장 (manuscript 삽입 시점에 정확한 수치 cite)
"""
