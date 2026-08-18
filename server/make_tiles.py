# -*- coding: utf-8 -*-
"""표준노드링크 → 브라우저가 필요한 조각만 받아 쓰는 타일 색인.

  원본 gpkg 는 575MB(지오메트리만 266MB)라 통째로 배포할 수 없다.
  전국을 10km 격자로 나누고, 조회 반경 상한 500m 를 감안해 각 타일을 500m 넓혀
  그 안에 들어오는 링크 구간만 담는다. 브라우저는 좌표가 속한 타일 하나만 받으면
  주변 500m 안의 도로를 전부 가지고 있어 이웃 타일을 챙길 필요가 없다.

  타일을 하나씩 만들면서 바로 파일로 내보내므로 메모리에 전국 지오메트리를 올리지 않는다.
  후보 링크는 gpkg 의 R-tree 공간색인으로 뽑는다.

  좌표는 EPSG:5186 평면(m) 정수로, 타일 원점 기준 첫 점 + 이후 델타로 적는다.
  도로명은 타일마다 사전을 두어 중복을 없앤다.
"""
import io, json, math, os, sqlite3, sys, time
sys.stdout.reconfigure(encoding='utf-8')
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import roadmatch as RM

TILE = 10000        # 타일 한 변 10km
BUF = 500           # 조회 반경 상한과 같은 여유폭
EPS = 1.0           # 선형 단순화 허용오차 1m — 매칭 정밀도(m 단위)에 영향 없음
OUT = sys.argv[1] if len(sys.argv) > 1 else 'roadtiles'


def simplify(pts, eps):
    """Douglas-Peucker (반복 구현 — 정점이 많은 링크에서도 재귀 한도에 걸리지 않는다)."""
    if len(pts) < 3:
        return pts
    keep = [False] * len(pts)
    keep[0] = keep[-1] = True
    stack = [(0, len(pts) - 1)]
    while stack:
        a, b = stack.pop()
        if b - a < 2:
            continue
        x0, y0 = pts[a]
        dx, dy = pts[b][0] - x0, pts[b][1] - y0
        dd = dx * dx + dy * dy
        best, bi = -1.0, a
        for i in range(a + 1, b):
            px, py = pts[i]
            if dd == 0:
                d = math.hypot(px - x0, py - y0)
            else:
                u = ((px - x0) * dx + (py - y0) * dy) / dd
                u = 0.0 if u < 0 else (1.0 if u > 1 else u)
                d = math.hypot(px - (x0 + u * dx), py - (y0 + u * dy))
            if d > best:
                best, bi = d, i
        if best > eps:
            keep[bi] = True
            stack.append((a, bi)); stack.append((bi, b))
    return [p for p, k in zip(pts, keep) if k]


def runs_in_box(pts, lo_x, hi_x, lo_y, hi_y):
    """상자 안에 들어오는 연속 구간들. 경계를 넘는 선분을 살리려 양끝에 한 점씩 더 붙인다."""
    inside = [lo_x <= x <= hi_x and lo_y <= y <= hi_y for x, y in pts]
    out, cur = [], []
    for i, ok in enumerate(inside):
        if ok:
            if not cur and i > 0:
                cur.append(pts[i - 1])
            cur.append(pts[i])
        elif cur:
            cur.append(pts[i])
            out.append(cur); cur = []
    if cur:
        out.append(cur)
    return [r for r in out if len(r) >= 2]


nz = lambda v: None if v is None or str(v).strip() in ('', '-') else str(v).strip()


def main():
    os.makedirs(OUT, exist_ok=True)
    con = sqlite3.connect('file:' + RM.GPKG.replace(chr(92), '/') + '?mode=ro&immutable=1', uri=True)
    con.text_factory = str
    cur = con.cursor()
    bx0, bx1, by0, by1 = cur.execute(
        'SELECT MIN(minx),MAX(maxx),MIN(miny),MAX(maxy) FROM rtree_moct_link_geom').fetchone()
    tx0, tx1 = int(bx0 // TILE), int(bx1 // TILE)
    ty0, ty1 = int(by0 // TILE), int(by1 // TILE)
    cells = [(tx, ty) for tx in range(tx0, tx1 + 1) for ty in range(ty0, ty1 + 1)]
    print(f'격자 {tx1 - tx0 + 1} x {ty1 - ty0 + 1} = {len(cells):,}칸 검사')

    sql = ('SELECT m.LINK_ID, m.ROAD_RANK, m.ROAD_NO, m.ROAD_NAME, m.LANES, m.MAX_SPD, '
           'm.UPDATEDATE, m.geom FROM rtree_moct_link_geom r JOIN moct_link m ON m.fid = r.id '
           'WHERE r.maxx >= ? AND r.minx <= ? AND r.maxy >= ? AND r.miny <= ?')
    index, total, vin, vout, t0 = {}, 0, 0, 0, time.time()
    for k, (tx, ty) in enumerate(cells, 1):
        if k % 300 == 0:
            print(f'  {k:,}/{len(cells):,} · 타일 {len(index):,}개 · {time.time() - t0:.0f}s', flush=True)
        lo_x, hi_x = tx * TILE - BUF, (tx + 1) * TILE + BUF
        lo_y, hi_y = ty * TILE - BUF, (ty + 1) * TILE + BUF
        ox, oy = tx * TILE, ty * TILE
        names, nidx, rows = [], {}, []
        for lid, rank, no, name, lanes, spd, upd, blob in cur.execute(sql, (lo_x, hi_x, lo_y, hi_y)):
            for part in RM.parse_gpkg_geom(blob):
                vin += len(part)
                pts = simplify([(round(x, 1), round(y, 1)) for x, y in part], EPS)
                vout += len(pts)
                for run in runs_in_box(pts, lo_x, hi_x, lo_y, hi_y):
                    nm = nz(name)
                    if nm is not None and nm not in nidx:
                        nidx[nm] = len(names); names.append(nm)
                    g, px, py = [], ox, oy
                    for x, y in run:
                        ix, iy = int(round(x)), int(round(y))
                        g.append(ix - px); g.append(iy - py)
                        px, py = ix, iy
                    rows.append([str(lid), nz(rank), nz(no), (nidx[nm] if nm is not None else -1),
                                 lanes if isinstance(lanes, int) else None,
                                 spd if isinstance(spd, int) else None, nz(upd), g])
        if not rows:
            continue
        blob = json.dumps({'o': [ox, oy], 'n': names, 'l': rows},
                          ensure_ascii=False, separators=(',', ':'))
        open(os.path.join(OUT, f'{tx}_{ty}.json'), 'w', encoding='utf-8').write(blob)
        index[f'{tx}_{ty}'] = len(rows)
        total += len(blob.encode('utf-8'))
    con.close()

    json.dump({'tile': TILE, 'buf': BUF, 'eps': EPS, 'srs': 5186, 'tiles': index},
              open(os.path.join(OUT, 'index.json'), 'w', encoding='utf-8'),
              ensure_ascii=False, separators=(',', ':'))
    big = max(os.path.getsize(os.path.join(OUT, f'{k}.json')) for k in index)
    print(f'\n  정점 {vin:,} → 단순화 {vout:,} ({vout * 100 // max(vin, 1)}%)')
    print(f'  타일 {len(index):,}개 / 총 {total / 1048576:.1f} MB '
          f'/ 평균 {total / len(index) / 1024:.1f} KB / 최대 {big / 1024:.0f} KB')
    print(f'  소요 {time.time() - t0:.0f}초')


if __name__ == '__main__':
    main()
