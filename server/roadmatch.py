# -*- coding: utf-8 -*-
"""표준노드링크(link_new.gpkg / moct_link) 위경도 → 도로속성 매칭 엔진.
   외부 의존성 없음(파이썬 표준 라이브러리만). GPKG = SQLite + rtree + WKB BLOB.
   좌표계: EPSG:5186 (Korea 2000 / Central Belt 2010, GRS80 TM)  ※ 본 파일에서 실측 검증됨
"""
import math
import sqlite3
import struct

GPKG = r'C:\Users\User\Desktop\승인반출\표준용어\데이터 표준\3. Standard_table\link_new.gpkg'

# ── EPSG:5186 파라미터 (GRS80 / 중부원점 2010) ───────────────────────────
A = 6378137.0
F = 1 / 298.257222101
LAT0 = math.radians(38.0)
LON0 = math.radians(127.0)
K0 = 1.0
FE = 200000.0
FN = 600000.0

E2 = F * (2 - F)
EP2 = E2 / (1 - E2)


def _meridian_arc(lat):
    """자오선 호장(적도~lat)."""
    e2, e4, e6 = E2, E2 * E2, E2 * E2 * E2
    a0 = 1 - e2 / 4 - 3 * e4 / 64 - 5 * e6 / 256
    a2 = 3.0 / 8 * (e2 + e4 / 4 + 15 * e6 / 128)
    a4 = 15.0 / 256 * (e4 + 3 * e6 / 4)
    a6 = 35.0 / 3072 * e6
    return A * (a0 * lat - a2 * math.sin(2 * lat) + a4 * math.sin(4 * lat) - a6 * math.sin(6 * lat))


def to_tm(lat_deg, lon_deg):
    """WGS84 위경도(도) → EPSG:5186 평면좌표(m). Krüger 급수(6차)."""
    lat, lon = math.radians(lat_deg), math.radians(lon_deg)
    sin_l, cos_l, tan_l = math.sin(lat), math.cos(lat), math.tan(lat)
    n = A / math.sqrt(1 - E2 * sin_l * sin_l)
    t = tan_l * tan_l
    c = EP2 * cos_l * cos_l
    a_ = (lon - LON0) * cos_l
    m = _meridian_arc(lat)
    m0 = _meridian_arc(LAT0)

    x = K0 * n * (a_ + (1 - t + c) * a_ ** 3 / 6
                  + (5 - 18 * t + t * t + 72 * c - 58 * EP2) * a_ ** 5 / 120) + FE
    y = K0 * (m - m0 + n * tan_l * (a_ * a_ / 2
              + (5 - t + 9 * c + 4 * c * c) * a_ ** 4 / 24
              + (61 - 58 * t + t * t + 600 * c - 330 * EP2) * a_ ** 6 / 720)) + FN
    return x, y


def to_wgs(x, y):
    """EPSG:5186 평면좌표(m) → WGS84 위경도(도). 검증용 역변환."""
    m = (y - FN) / K0 + _meridian_arc(LAT0)
    e1 = (1 - math.sqrt(1 - E2)) / (1 + math.sqrt(1 - E2))
    mu = m / (A * (1 - E2 / 4 - 3 * E2 ** 2 / 64 - 5 * E2 ** 3 / 256))
    p1 = (mu + (3 * e1 / 2 - 27 * e1 ** 3 / 32) * math.sin(2 * mu)
          + (21 * e1 ** 2 / 16 - 55 * e1 ** 4 / 32) * math.sin(4 * mu)
          + (151 * e1 ** 3 / 96) * math.sin(6 * mu))
    sin_p, cos_p, tan_p = math.sin(p1), math.cos(p1), math.tan(p1)
    c1 = EP2 * cos_p ** 2
    t1 = tan_p ** 2
    n1 = A / math.sqrt(1 - E2 * sin_p ** 2)
    r1 = A * (1 - E2) / (1 - E2 * sin_p ** 2) ** 1.5
    d = (x - FE) / (n1 * K0)
    lat = p1 - (n1 * tan_p / r1) * (d * d / 2
          - (5 + 3 * t1 + 10 * c1 - 4 * c1 * c1 - 9 * EP2) * d ** 4 / 24
          + (61 + 90 * t1 + 298 * c1 + 45 * t1 * t1 - 252 * EP2 - 3 * c1 * c1) * d ** 6 / 720)
    lon = LON0 + (d - (1 + 2 * t1 + c1) * d ** 3 / 6
          + (5 - 2 * c1 + 28 * t1 - 3 * c1 * c1 + 8 * EP2 + 24 * t1 * t1) * d ** 5 / 120) / cos_p
    return math.degrees(lat), math.degrees(lon)


# ── GPKG 지오메트리 BLOB 파서 ────────────────────────────────────────────
def parse_gpkg_geom(blob):
    """GPKG BLOB → [[(x,y), ...], ...] (라인스트링 목록)."""
    if not blob or blob[:2] != b'GP':
        return []
    flags = blob[3]
    env_ind = (flags >> 1) & 0x07
    env_len = {0: 0, 1: 32, 2: 48, 3: 48, 4: 64}.get(env_ind, 0)
    off = 8 + env_len
    return _wkb(blob, off)[0]


def _wkb(buf, off):
    endian = '<' if buf[off] == 1 else '>'
    off += 1
    (gtype,) = struct.unpack_from(endian + 'I', buf, off)
    off += 4
    base = gtype % 1000            # 2=LineString, 5=MultiLineString
    dims = 2 + (1 if 1000 <= gtype < 2000 or gtype >= 3000 else 0) + (1 if gtype >= 2000 else 0)
    lines = []
    if base == 2:
        (npt,) = struct.unpack_from(endian + 'I', buf, off)
        off += 4
        pts = []
        for _ in range(npt):
            x, y = struct.unpack_from(endian + 'dd', buf, off)
            off += 8 * dims
            pts.append((x, y))
        lines.append(pts)
    elif base == 5:
        (ng,) = struct.unpack_from(endian + 'I', buf, off)
        off += 4
        for _ in range(ng):
            sub, off = _wkb(buf, off)
            lines.extend(sub)
    return lines, off


def _seg_dist(px, py, x1, y1, x2, y2):
    dx, dy = x2 - x1, y2 - y1
    if dx == 0 and dy == 0:
        return math.hypot(px - x1, py - y1)
    t = max(0.0, min(1.0, ((px - x1) * dx + (py - y1) * dy) / (dx * dx + dy * dy)))
    return math.hypot(px - (x1 + t * dx), py - (y1 + t * dy))


def point_line_dist(px, py, lines):
    best = float('inf')
    for pts in lines:
        for i in range(len(pts) - 1):
            d = _seg_dist(px, py, pts[i][0], pts[i][1], pts[i + 1][0], pts[i + 1][1])
            if d < best:
                best = d
    return best


# ── 매칭 ────────────────────────────────────────────────────────────────
FIELDS = ('LINK_ID', 'ROAD_RANK', 'ROAD_TYPE', 'ROAD_NO', 'ROAD_NAME',
          'LANES', 'MAX_SPD', 'ROAD_USE', 'UPDATEDATE')


def match(lat, lon, radius_m=100.0, limit=5, db=GPKG, with_geom=False):
    """위경도 → 반경 내 최근접 도로링크 목록(거리 오름차순).

    with_geom=True 면 각 항목에 '_geom'(EPSG:5186 좌표쌍 배열)을 함께 담는다.
    배포용 데모 데이터를 잘라낼 때만 쓰고, API 응답에는 싣지 않는다.
    """
    x, y = to_tm(lat, lon)
    con = sqlite3.connect('file:' + db.replace('\\', '/') + '?mode=ro&immutable=1', uri=True)
    con.text_factory = str
    cur = con.cursor()
    sql = (f"SELECT m.fid, m.geom, {', '.join('m.' + f for f in FIELDS)} "
           "FROM rtree_moct_link_geom r JOIN moct_link m ON m.fid = r.id "
           "WHERE r.maxx >= ? AND r.minx <= ? AND r.maxy >= ? AND r.miny <= ?")
    out = []
    for row in cur.execute(sql, (x - radius_m, x + radius_m, y - radius_m, y + radius_m)):
        geom = parse_gpkg_geom(row[1])
        d = point_line_dist(x, y, geom)
        if d <= radius_m:
            rec = dict(zip(FIELDS, row[2:]))
            rec['dist_m'] = round(d, 2)
            if with_geom:
                rec['_geom'] = geom
            out.append(rec)
    con.close()
    out.sort(key=lambda r: r['dist_m'])
    return out[:limit]
