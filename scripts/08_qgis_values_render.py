"""Render the values-only project (08_qgis_values_project.py) into PNGs for a visual check, never saving the project:
main-map themes at a detail scale, at 1:250,000, 1:100,000, 1:40,000 and the region extent, the region layout and atlas pages.
usage: python-qgis.bat scripts/08_qgis_values_render.py <repo_root> <png_dir> [zone_no]
       (env VIEW_DIR: a test project elsewhere; the atlas is also exported for the rural zone 315402101)"""
import os
import sys
from pathlib import Path

from qgis.core import (QgsApplication, QgsLayoutExporter, QgsLayoutItemMap, QgsMapRendererParallelJob, QgsMapSettings,
                       QgsProject, QgsRectangle)
from qgis.PyQt.QtCore import QSize
from qgis.PyQt.QtGui import QColor

REPO, OUT = Path(sys.argv[1]), Path(sys.argv[2])
ZONE = sys.argv[3] if len(sys.argv) > 3 else '310103903'
VIEW_DIR = Path(os.environ['VIEW_DIR']) if os.environ.get('VIEW_DIR') else REPO / 'data' / 'experimental_extract'
OUT.mkdir(parents=True, exist_ok=True)
app = QgsApplication([], False)
app.initQgis()
p = QgsProject.instance()
assert p.read(str(VIEW_DIR / '08_redistribution_values.qgs'))
themes = p.mapThemeCollection()


def render(theme, extent, size, name):
    s = QgsMapSettings()
    s.setDestinationCrs(p.crs())
    s.setLayers(themes.mapThemeVisibleLayers(theme))
    s.setLayerStyleOverrides(themes.mapThemeStyleOverrides(theme))
    s.setExtent(extent)
    s.setOutputSize(QSize(*size))
    s.setBackgroundColor(QColor('#ffffff'))
    j = QgsMapRendererParallelJob(s)
    j.start()
    j.waitForFinished()
    j.renderedImage().save(str(OUT / name))
    print('map', name, f'1:{s.scale():,.0f}')


zl = [l for l in p.mapLayers().values() if l.name() == 'Zone boundaries'][0]
bs = next(zl.getFeatures(f'"NO" = {ZONE}')).geometry().boundingBox()
names = themes.mapThemes()
print('themes:', names)
c = bs.center()
d = bs
d.grow(250)
for t in [n for n in names if n[:2] in ('01', '05', '09', '12')]:
    render(t, d, (1400, 1100), f'detail_{t[:2]}.png')
w, h = 1200 / 96 * 0.0254 * 250000, 900 / 96 * 0.0254 * 250000      # 1:250,000 at 96 dpi
mid = QgsRectangle(c.x() - w / 2, c.y() - h / 2, c.x() + w / 2, c.y() + h / 2)
for t in [n for n in names if n[:2] in ('01', '09')]:
    render(t, mid, (1200, 900), f'mid250k_{t[:2]}.png')
for sc in (100000, 40000):
    w, h = 1200 / 96 * 0.0254 * sc, 900 / 96 * 0.0254 * sc
    r = QgsRectangle(c.x() - w / 2, c.y() - h / 2, c.x() + w / 2, c.y() + h / 2)
    for t in [n for n in names if n[:2] in ('01', '02')]:
        render(t, r, (1200, 900), f'mid{sc // 1000}k_{t[:2]}.png')
ext = zl.extent()
for t in [n for n in names if n[:2] in ('01', '03', '09')]:
    render(t, ext, (700, 1250), f'region_{t[:2]}.png')

lm = p.layoutManager()
s = QgsLayoutExporter.ImageExportSettings()
s.dpi = 90
for k, lay in enumerate(lm.printLayouts()):
    tag = f'{k + 1}'
    if lay.atlas().enabled():
        atlas = lay.atlas()
        atlas.setFilterFeatures(True)
        for zone in (ZONE, '315402101'):
            atlas.setFilterExpression(f'"NO" = {zone}')
            assert atlas.beginRender() and atlas.first(), 'atlas has no page'
            sizes = {(round(i.sizeWithUnits().width(), 1), round(i.sizeWithUnits().height(), 1)) for i in lay.items() if isinstance(i, QgsLayoutItemMap)}
            print(lay.name(), zone, 'atlas map sizes on this page:', sizes)
            r = QgsLayoutExporter(lay).exportToImage(str(OUT / f'layout{tag}_{zone}.png'), s)
            atlas.endRender()
    else:
        r = QgsLayoutExporter(lay).exportToImage(str(OUT / f'layout{tag}.png'), s)
    print('layout', tag, lay.name(), r)
p.clear()
sys.stdout.flush()
os._exit(0)
