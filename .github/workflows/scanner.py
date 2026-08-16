name: Daily Crypto 4H Scanner

on:
  schedule:
    # 00:05, 08:05, 16:05 UTC = 07:05, 15:05, 23:05 น. (เวลาไทย - หลบคิวชน)
    - cron: '5 0,8,16 * * *'
  workflow_dispatch:

jobs:
  scan:
    runs-on: ubuntu-latest
    steps:
      - name: ดึงโค้ดโปรเจกต์
        uses: actions/checkout@v4

      - name: ติดตั้ง Python
        uses: actions/setup-python@v5
        with:
          python-version: '3.10'

      - name: ติดตั้งไลบรารีที่จำเป็น
        run: |
          pip install requests pandas numpy

      - name: รันบอทสแกนและส่งผล
        run: |
          python scanner.py
