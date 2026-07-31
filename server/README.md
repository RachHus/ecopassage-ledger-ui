# 도로속성 자동매칭 API — 실행 안내

입력 UI(`생태통로_입력UI_20260729.html`)에서 **위경도 → 횡단 도로 자동 조회**를 쓰려면
이 폴더의 매칭 서버를 먼저 실행합니다. 외부 라이브러리는 필요 없습니다(파이썬 표준 라이브러리만 사용).

## 실행

```
python road_match_server.py
```

띄운 뒤 브라우저에서 **http://127.0.0.1:8765/** 로 접속하면 입력 UI가 열립니다.
(포트를 바꾸려면 `python road_match_server.py 9000` 처럼 인자로 줍니다.)

서버를 실행하지 않아도 UI는 열리지만, 도로 항목은 **수동입력**으로만 작성됩니다.

## 구성

| 파일 | 역할 |
|---|---|
| `roadmatch.py` | 매칭 엔진. 위경도(WGS84) → EPSG:5186 변환, GeoPackage R-tree 후보 추출, 지오메트리 파싱, 점-선분 최단거리 |
| `road_match_server.py` | HTTP API + 입력 UI 서빙 |

## 표준노드링크 파일 경로

`roadmatch.py` 첫머리의 `GPKG` 상수가 가리킵니다. 기본값:

```
C:\Users\User\Desktop\승인반출\표준용어\데이터 표준\3. Standard_table\link_new.gpkg
```

자료를 다른 곳에 두었거나 갱신본으로 바꾸려면 이 한 줄만 수정하면 됩니다.

## API 규격

```
GET /api/road-link/match?lat=<위도>&lon=<경도>&radius=<반경m, 기본 100>
```

응답:

```json
{"ok": true, "count": 1, "radius_m": 100.0,
 "candidates": [{
   "ROAD_LINK_ID": "1850139200", "ROAD_GRD_SE_CD": "104", "ROAD_GRD_SE_NM": "특별·광역시도",
   "ROAD_RTE_NO": null, "ROAD_NM": "청사로", "BTWYS_LANE_CNT": 4,
   "ROAD_ATRB_SRC_SE_CD": "RSLK", "ROAD_ATRB_CRTR_YMD": "20250512",
   "_dist_m": 25.07, "_max_spd": 50, "_road_use": "0"}]}
```

- 응답 키는 표준 테이블 `TB_ECRD`의 물리 컬럼명과 1:1로 맞춰 두었습니다. UI는 받은 값을 그대로 채우기만 합니다.
- 밑줄로 시작하는 키(`_dist_m` 등)는 화면 표시용이며 저장 대상이 아닙니다.
- `count: 0` 이면 해당 위치에 도로 공간정보가 없다는 뜻이므로 UI가 수동입력으로 전환합니다.
- 서버에서 미리 처리하는 것: 결측 대체문자 `'-'` → `null`(BR-15), 왕복차로수 = 편도차로수 × 2(BR-13).
- 표준노드링크의 `ROAD_TYPE`(일반/고가/지하/교량/터널)은 **응답에 포함하지 않습니다.**
  2026-07-31 지시로 도로 구분은 `ROAD_RANK`(도로등급) 하나만 활용합니다(D-20).

## 웹 이식 시

PostGIS 환경이라면 매칭 로직을 다음 질의로 대체할 수 있습니다.

```sql
SELECT link_id, road_rank, road_no, road_name, lanes, updatedate,
       ST_Distance(geom, p.g) AS dist_m
  FROM moct_link,
       LATERAL (SELECT ST_Transform(ST_SetSRID(ST_Point(:lon, :lat), 4326), 5186)) AS p(g)
 WHERE ST_DWithin(geom, p.g, :radius)
 ORDER BY dist_m
 LIMIT 5;
```

응답 가공 규칙(`'-'` → null, 차로수 ×2)은 그대로 옮기면 됩니다.

## 좌표계에 관한 주의

배포된 GeoPackage에는 좌표계가 `Undefined (GDAL 99999)`로 기록되어 있어 파일만으로는 확정할 수 없습니다.
좌표 범위와 실지점 대조로 **EPSG:5186 (Korea 2000 / 중부원점 2010)** 임을 확인했습니다.

- 서울시청 앞(37.5663, 126.9779) → 세종대로 59.3m
- 광화문(37.5720, 126.9769) → 세종대로 21.9m
- 정부대전청사(36.3600, 127.3845) → 청사로 25.1m
- 링크 정점 → 위경도 → 재매칭 왕복검증 4건 전부 오차 0.00m

향후 표준노드링크 갱신본을 받았을 때 좌표가 어긋나면 이 대조를 다시 해 보고,
필요하면 `roadmatch.py`의 투영 상수(`LAT0`, `LON0`, `FE`, `FN`)를 조정하십시오.
