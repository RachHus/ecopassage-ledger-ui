# -*- coding: utf-8 -*-
"""GitHub Pages 배포용 오프라인 데모 데이터 생성.

표준노드링크 원본(575MB)은 배포할 수 없으므로, 데모 지점 주변의 링크만 잘라내
브라우저에서 동일한 매칭 연산을 돌릴 수 있는 작은 JSON으로 만든다.
좌표는 EPSG:5186 평면좌표(m)로 저장하고, 조회 지점만 브라우저에서 변환한다.
"""
import io
import json
import sys

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
sys.path.insert(0, '.')
import roadmatch as RM

# (이름, 위도, 경도, 수집반경m) — 검토자가 눌러 볼 수 있는 지점
POINTS = [
    ('정부대전청사 (특별·광역시도)', 36.3600, 127.3845, 400),
    ('광화문 (일반국도)', 37.5720, 126.9769, 400),
    ('서해안고속도로 (고속국도 · 노선 15)', 37.242063, 126.880808, 500),
    ('지리산 자락 (도로 없음 — 수동입력 시연)', 35.3370, 127.7300, 0),
]

links, seen = [], set()
for nm, lat, lon, rad in POINTS:
    if rad == 0:
        continue
    for rec in RM.match(lat, lon, radius_m=rad, limit=400, with_geom=True):
        lid = rec.get('LINK_ID')
        if lid in seen:
            continue
        seen.add(lid)
        # 지오메트리를 좌표쌍 배열로 (소수 1자리 = 10cm 정밀도면 충분)
        parts = [[[round(x, 1), round(y, 1)] for x, y in g] for g in rec['_geom']]
        links.append({
            'id': lid, 'rank': rec.get('ROAD_RANK'), 'no': rec.get('ROAD_NO'),
            'name': rec.get('ROAD_NAME'), 'lanes': rec.get('LANES'),
            'spd': rec.get('MAX_SPD'), 'upd': rec.get('UPDATEDATE'),
            'g': parts,
        })

out = {
    'note': '표준노드링크(link_new.gpkg)에서 데모 지점 주변만 잘라낸 부분집합. EPSG:5186 평면좌표(m).',
    'points': [{'nm': n, 'lat': la, 'lon': lo} for n, la, lo, _ in POINTS],
    'links': links,
}
txt = json.dumps(out, ensure_ascii=False, separators=(',', ':'))
open('demo_links.json', 'w', encoding='utf-8').write(txt)
print(f'링크 {len(links)}건 / {len(txt) / 1024:.0f} KB → demo_links.json')
for nm, la, lo, rad in POINTS:
    hits = RM.match(la, lo, radius_m=100, limit=3) if rad else []
    print(f'  {nm}: 반경 100m 내 {len(hits)}건' + (f' — 최근접 {hits[0].get("ROAD_NAME")} {hits[0]["dist_m"]}m' if hits else ''))
