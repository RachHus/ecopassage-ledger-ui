# -*- coding: utf-8 -*-
"""생태통로 입력 UI용 도로속성 자동매칭 API — 레퍼런스 구현.

  실행:  python road_match_server.py [포트]        (기본 8765)
  화면:  http://127.0.0.1:8765/

  GET /api/road-link/match?lat=<위도>&lon=<경도>&radius=<반경m, 기본 100>
    → {"ok":true,"count":n,"candidates":[{표준 컬럼명: 값, ...}, ...]}
      후보가 0건이면 count=0 → UI가 수동입력 모드로 전환한다.

  ▣ 웹 이식 시 유의점
    - 본 구현은 파이썬 표준 라이브러리만 사용한다(GPKG = SQLite + rtree + WKB BLOB).
      PostGIS·GeoServer가 있는 환경이라면 아래 SQL 한 줄로 대체 가능:
        SELECT ... FROM moct_link
         WHERE ST_DWithin(geom, ST_Transform(ST_SetSRID(ST_Point(:lon,:lat),4326),5186), :radius)
         ORDER BY ST_Distance(...) LIMIT 5
    - 응답 필드명은 표준 테이블 TB_ECRD의 물리 컬럼명과 1:1로 맞춰 두었다.
      UI는 받은 값을 그대로 입력칸에 채우기만 하면 된다.
    - 표준노드링크의 결측 대체문자 '-'는 서버에서 NULL로 정규화한다(BR-15).
    - 왕복차로수 = LANES(편도) × 2 도 서버에서 산출한다(BR-13).
"""
import json
import os
import sys
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import roadmatch as RM

HERE = os.path.dirname(os.path.abspath(__file__))
UP = os.path.dirname(HERE)
# 이 폴더 → 상위 폴더 순으로 입력 UI 파일을 찾는다.
# (배포 저장소에서는 상위 폴더의 index.html, 산출물 폴더에서는 생태통로_입력UI_*.html)
_CANDS = [os.path.join(d, n) for d in (HERE, UP)
          for n in ('index.html', '생태통로_입력UI_20260731.html', '생태통로_입력UI_20260729.html', 'ui.html')]
UI_FILE = next((p for p in _CANDS if os.path.exists(p)), _CANDS[0])

# 표준노드링크 ROAD_RANK → 도로등급구분코드(CD02) : 값 자체가 동일하여 그대로 승계.
# 표준노드링크의 ROAD_TYPE(일반/고가/지하/교량/터널)은 2026-07-31 지시로 활용하지 않는다.
GRD_NM = {'101': '고속국도', '102': '도시고속국도', '103': '일반국도', '104': '특별·광역시도',
          '105': '국가지원지방도', '106': '지방도', '107': '시·군도', '108': '기타'}


def nz(v):
    """표준노드링크 결측 대체문자 '-' 및 빈 문자열 → None (BR-15)."""
    if v is None:
        return None
    s = str(v).strip()
    return None if s in ('', '-') else s


def to_standard(rec):
    """매칭 결과 1건 → 표준 테이블 TB_ECRD 컬럼명 기준 딕셔너리."""
    rank = nz(rec.get('ROAD_RANK'))
    lanes = rec.get('LANES')
    return {
        'ROAD_LINK_ID': nz(rec.get('LINK_ID')),
        'ROAD_GRD_SE_CD': rank,
        'ROAD_GRD_SE_NM': GRD_NM.get(rank, ''),
        'ROAD_RTE_NO': nz(rec.get('ROAD_NO')),
        'ROAD_NM': nz(rec.get('ROAD_NAME')),
        'BTWYS_LANE_CNT': (lanes * 2) if isinstance(lanes, int) else None,
        'ROAD_ATRB_SRC_SE_CD': 'RSLK',
        'ROAD_ATRB_CRTR_YMD': nz(rec.get('UPDATEDATE')),
        '_dist_m': rec.get('dist_m'),
        '_max_spd': rec.get('MAX_SPD'),
        '_road_use': rec.get('ROAD_USE'),
    }


class Handler(BaseHTTPRequestHandler):
    def _send(self, code, body, ctype='application/json; charset=utf-8'):
        data = body if isinstance(body, bytes) else body.encode('utf-8')
        self.send_response(code)
        self.send_header('Content-Type', ctype)
        self.send_header('Content-Length', str(len(data)))
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Cache-Control', 'no-store')
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        u = urlparse(self.path)
        if u.path in ('/', '/index.html'):
            if not os.path.exists(UI_FILE):
                return self._send(404, '입력 UI 파일을 찾을 수 없습니다: ' + UI_FILE,
                                  'text/plain; charset=utf-8')
            with open(UI_FILE, 'rb') as f:
                return self._send(200, f.read(), 'text/html; charset=utf-8')

        if u.path == '/api/road-link/match':
            q = parse_qs(u.query)
            try:
                lat = float(q.get('lat', [''])[0])
                lon = float(q.get('lon', [''])[0])
            except ValueError:
                return self._send(400, json.dumps(
                    {'ok': False, 'error': '위도·경도를 숫자로 전달하세요'}, ensure_ascii=False))
            if not (33.0 <= lat <= 39.0 and 124.0 <= lon <= 132.0):   # BR-10
                return self._send(400, json.dumps(
                    {'ok': False, 'error': '대한민국 좌표 범위(위도 33~39, 경도 124~132)를 벗어났습니다'},
                    ensure_ascii=False))
            try:
                radius = min(500.0, max(10.0, float(q.get('radius', ['100'])[0])))
            except ValueError:
                radius = 100.0
            hits = RM.match(lat, lon, radius_m=radius, limit=5)
            out = [to_standard(h) for h in hits]
            return self._send(200, json.dumps(
                {'ok': True, 'count': len(out), 'radius_m': radius, 'candidates': out},
                ensure_ascii=False))

        return self._send(404, json.dumps({'ok': False, 'error': 'not found'}, ensure_ascii=False))

    def log_message(self, fmt, *args):
        sys.stderr.write('  %s\n' % (fmt % args))


if __name__ == '__main__':
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8765
    if not os.path.exists(RM.GPKG):
        print('[경고] 표준노드링크 파일을 찾을 수 없습니다:', RM.GPKG)
        print('       roadmatch.py 의 GPKG 경로를 수정하세요.')
    srv = ThreadingHTTPServer(('127.0.0.1', port), Handler)
    print(f'도로속성 매칭 API 기동 → http://127.0.0.1:{port}/')
    print(f'  자료: {RM.GPKG}')
    print('  종료: Ctrl+C')
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print('\n종료')
