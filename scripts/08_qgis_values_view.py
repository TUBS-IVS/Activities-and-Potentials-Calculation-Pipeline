"""Write data/experimental_extract/08_redistribution_values_view.gpkg for the values-only QGIS project
08_redistribution_values.qgs: the buildings and POIs of 08_redistribution.gpkg unchanged, the asked POIs split by their own
geometry (POIs mapped as areas get their OSM polygon from 01_all_pois.gpkg, layer poi_polygons; POIs mapped as points stay
points, layer poi_points), and the zones with one value per class: the sum over the zone's buildings (assigned_* as in the
file, plus the five visitor values). The VISUM zone inputs (target_*) are left out of the view, so a zone shows one number
per class; they stay in 08_redistribution.gpkg. No change columns. The real output is only read, so
QGIS never opens it through this project.

Rebuild it, then 08_qgis_values_project.py, after every run of notebook 08.

usage (capacity-final env):  python scripts/08_qgis_values_view.py [<repo_root>]
       (env VIEW_OUT: write a test file elsewhere)
"""
import os
import sys
from pathlib import Path

import geopandas as gpd
import numpy as np
import pyogrio
from shapely.geometry import MultiPolygon

REPO = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(__file__).resolve().parents[1]
SRC = REPO / 'data' / 'output' / '08_redistribution.gpkg'
POIS01 = REPO / 'data' / 'output' / '01_all_pois.gpkg'
OUT = REPO / 'data' / 'experimental_extract' / '08_redistribution_values_view.gpkg'
if os.environ.get('VIEW_OUT'):                  # a test build elsewhere
    OUT = Path(os.environ['VIEW_OUT'])

bld = pyogrio.read_dataframe(SRC, layer='buildings')
bld['zone_no'] = bld['zone_no'].astype('Int64')     # nullable: read as float because of the buildings in no zone
pois = pyogrio.read_dataframe(SRC, layer='pois')
zones = pyogrio.read_dataframe(SRC, layer='zones')
assert bld['building_id'].is_unique and pois['poi_id'].is_unique and zones['NO'].is_unique

ASSIGNED = [c for c in bld.columns if c.startswith('assigned_')]
VALS = [c for c in bld.columns if c.startswith('value_') and c != 'value_assumed']
assert len(ASSIGNED) == 7 and len(VALS) == 5, (ASSIGNED, VALS)
CHANGE = ('d_', 'moved_', 'chg_pct_')
for name, df in (('buildings', bld), ('pois', pois), ('zones', zones)):
    assert not [c for c in df.columns if c.startswith(CHANGE)], f'{name} carries change columns'

own = pyogrio.read_dataframe(POIS01, layer='pois', columns=['poi_id'])
own = own[own['poi_id'].isin(pois['poi_id'])].set_index('poi_id').geometry
assert pois['poi_id'].isin(own.index).all(), 'asked POIs missing from 01_all_pois'
is_area = pois['poi_id'].map(own.geom_type).isin(['Polygon', 'MultiPolygon'])
poly = pois[is_area].copy()
poly['geometry'] = [g if g.geom_type == 'MultiPolygon' else MultiPolygon([g]) for g in poly['poi_id'].map(own)]
poly = gpd.GeoDataFrame(poly, geometry='geometry', crs=pois.crs)
pts = pois[~is_area].copy()

# a zone's value of a class = the sum over its buildings (their POIs are included in them); the file already holds that for
# the seven redistributed classes, the five visitor values are added
zb = bld.dropna(subset=['zone_no']).assign(zone_no=lambda d: d['zone_no'].astype('int64'))
per_zone = zb.groupby('zone_no')[ASSIGNED + VALS].sum()
assert set(per_zone.index) <= set(zones['NO']), 'buildings in zones the file does not hold'
for c in ASSIGNED:
    s = zones['NO'].map(per_zone[c]).fillna(0.0)
    assert np.allclose(s.to_numpy(), zones[c].to_numpy(), rtol=1e-9, atol=1e-6), f'zones {c} is not the sum of its buildings'
for c in VALS:
    zones[c] = zones['NO'].map(per_zone[c]).fillna(0.0)
outside = bld.loc[bld['zone_no'].isna(), ASSIGNED + VALS].abs().to_numpy().sum()
assert outside == 0, f'buildings in no zone carry {outside}'
zones = zones[['NO', 'NAME'] + ASSIGNED + VALS + ['geometry']]     # one value per class: the VISUM inputs stay in the output

if OUT.exists():
    OUT.unlink()
for name, df in (('buildings', bld), ('poi_polygons', poly), ('poi_points', pts), ('zones', zones)):
    pyogrio.write_dataframe(df, OUT, layer=name, driver='GPKG')

back = {name: pyogrio.read_info(OUT, layer=name)['features'] for name, _ in pyogrio.list_layers(OUT)}
assert back == {'buildings': len(bld), 'poi_polygons': len(poly), 'poi_points': len(pts), 'zones': len(zones)}, back
for name, _ in pyogrio.list_layers(OUT):
    fields = list(pyogrio.read_info(OUT, layer=name)['fields'])
    assert not [f for f in fields if f.startswith(CHANGE + ('target_',))], f'{name} got change or VISUM input columns'
assert list(pyogrio.read_info(OUT, layer='zones')['fields']) == ['NO', 'NAME'] + ASSIGNED + VALS
assert pyogrio.read_info(OUT, layer='buildings')['dtypes'][list(pyogrio.read_info(OUT, layer='buildings')['fields']).index('zone_no')] == 'int64'
num = ASSIGNED + VALS
assert np.allclose(poly[num].sum().to_numpy() + pts[num].sum().to_numpy(), pois[num].sum().to_numpy(), rtol=1e-9, atol=1e-6)
print(f'ok: {OUT} ({OUT.stat().st_size / 1e6:,.1f} MB):', back)
print('  region totals: ' + ' · '.join(f'{c.split("_", 1)[1]} {zones[c].sum():,.1f}' for c in num))
