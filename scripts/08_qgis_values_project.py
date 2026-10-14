"""Build data/experimental_extract/08_redistribution_values.qgs (QGIS 4.2) on 08_redistribution_values_view.gpkg: the
values of step 08 and nothing else - no change against an earlier run, no per-km2 or per-m2 variants. One map theme per
class (the 7 redistributed VISUM categories and the 5 visitor values): buildings filled by their value, POI points as
circles and POI areas as dashed outlines in the colour of their value (outline only, so every building shows its own
value), all on the same breaks; zoomed out (above 1:150,000), the zones coloured by the class's total
in the zone (the sum over its buildings). Two print layouts: the zone totals of every class for the whole region, and an
atlas with all classes for one zone at a time (each panel title gives the zone's total).

Run 08_qgis_values_view.py first. QGIS must not have the project open.

usage (QGIS's python, from PowerShell):
    & "C:/Program Files/QGIS 4.2.3/bin/python-qgis.bat" scripts/08_qgis_values_project.py [<repo_root>]
       (env VIEW_DIR: build next to a test view file elsewhere)
"""
import math
import os
import re
import sys
from pathlib import Path

from qgis.core import (Qgis, QgsApplication, QgsCoordinateReferenceSystem, QgsFeatureRequest, QgsFillSymbol,
                       QgsGraduatedSymbolRenderer, QgsHueSaturationFilter, QgsLayerTreeModel, QgsLayoutItemLabel,
                       QgsLayoutItemLegend, QgsLayoutItemMap, QgsLayoutItemPage, QgsLayoutPoint, QgsLayoutSize,
                       QgsLegendRenderer, QgsLegendStyle, QgsMapThemeCollection, QgsMarkerSymbol, QgsPalLayerSettings,
                       QgsPrintLayout, QgsProject, QgsProperty, QgsRasterLayer, QgsReferencedRectangle, QgsRendererRange,
                       QgsSimpleFillSymbolLayer, QgsSingleSymbolRenderer, QgsSymbolLayer, QgsTextBufferSettings,
                       QgsTextFormat, QgsVectorLayer, QgsVectorLayerSimpleLabeling)
from qgis.PyQt.QtGui import QColor, QFont

REPO = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(__file__).resolve().parents[1]
VIEW_DIR = Path(os.environ['VIEW_DIR']) if os.environ.get('VIEW_DIR') else REPO / 'data' / 'experimental_extract'
EXTRACT = VIEW_DIR / '08_redistribution_values_view.gpkg'
FINAL = VIEW_DIR / '08_redistribution_values.qgs'
assert EXTRACT.exists(), f'run scripts/08_qgis_values_view.py first: {EXTRACT}'

app = QgsApplication([], False)
app.initQgis()
project = QgsProject.instance()
project.setCrs(QgsCoordinateReferenceSystem('EPSG:25832'))
project.setEllipsoid('NONE')                                   # planar areas in EPSG:25832
project.setFilePathStorage(Qgis.FilePathType.Relative)
project.setTitle('Step 08 - the value of every class')

# --- the classes: two families, each its own one-hue ramp (validated: monotone lightness, light end >= 2:1) --------
VISUM = ['#86b6ef', '#5598e7', '#2a78d6', '#1c5cab', '#104281']      # the seven zone totals (blue)
VISIT = ['#ee9a7b', '#e36f43', '#ca4802', '#9e3702', '#752601']      # the five visitor values (orange)
CATS = [  # theme, style / panel title, field, unit, ramp
    ('01 Workers', 'Workers', 'assigned_Workers', 'persons', VISUM),
    ('02 School', 'School', 'assigned_School', 'pupils', VISUM),
    ('03 University', 'University', 'assigned_University', 'students', VISUM),
    ('04 Kindergarten', 'Kindergarten', 'assigned_Kindergarten', 'children', VISUM),
    ('05 Retail daily', 'Retail daily', 'assigned_Retail_Daily', 'VISUM value', VISUM),
    ('06 Retail non-daily', 'Retail non-daily', 'assigned_Retail_Non_Daily', 'VISUM value', VISUM),
    ('07 Leisure', 'Leisure', 'assigned_Leisure', 'VISUM value', VISUM),
    ('08 Visitors - business', 'Visitors: business', 'value_business', 'visits per working day', VISIT),
    ('09 Visitors - errands', 'Visitors: errands', 'value_errands', 'visits per working day', VISIT),
    ('10 Visitors - sports', 'Visitors: sports', 'value_sports', 'visits per working day', VISIT),
    ('11 Visitors - meetup', 'Visitors: meetup', 'value_meetup', 'visits per working day', VISIT),
    ('12 Visitors - lessons', 'Visitors: lessons', 'value_lessons', 'visits per working day', VISIT),
]
ZERO = '#dedcd5'          # a building that does not carry the class: recedes, still shows where buildings are
ZONE_ZERO = '#efeee9'
INK, INK2 = '#0b0b0b', '#52514e'
DETAIL_SCALE = 150000     # buildings and POIs below 1:150,000, the zones above
ZONE_LABEL_SCALE = 400000  # the zone totals are written on the zones between 1:400,000 and 1:150,000
SIZES = [2.0, 2.6, 3.2, 3.9, 4.6]
CHANGE = ('d_', 'moved_', 'chg_pct_', 'target_')    # no change columns, and no second number per class on the zones
UNIT_SHORT = {'persons': 'persons', 'pupils': 'pupils', 'students': 'students', 'children': 'children', 'VISUM value': '',
              'visits per working day': 'visits/day'}


def layer(name, title):
    lyr = QgsVectorLayer(f'{EXTRACT}|layername={name}', title, 'ogr')
    assert lyr.isValid(), f'{name} did not load'
    return lyr


def nice(v):
    if v <= 0:
        return 0.0
    e = 10 ** math.floor(math.log10(v))
    for m in (1, 1.2, 1.5, 2, 2.5, 3, 4, 5, 6, 8, 10):
        if v <= m * e * (1 + 1e-9):
            return round(m * e, 10)


def breaks(vals, ps):
    pos = sorted(v for v in vals if v is not None and v > 0)
    q = lambda p: pos[min(len(pos) - 1, int(round(p * (len(pos) - 1))))]
    out = []
    for p in ps:
        b = nice(q(p))
        while out and b <= out[-1]:
            b = nice(out[-1] * 1.05)
        out.append(b)
    return out, len(pos)


def fmt(v):
    if v >= 10:
        return f'{v:,.0f}'
    if v >= 1:
        return f'{v:.1f}'.rstrip('0').rstrip('.')
    return f'{v:.2g}'


def class_labels(cuts, top_note):
    labs = [f'up to {fmt(cuts[0])}'] + [f'{fmt(a)} - {fmt(b)}' for a, b in zip(cuts, cuts[1:])]
    return labs + [f'over {fmt(cuts[-1])}{top_note}']


def fill(colour, stroke=None, width='0.05', style='solid'):
    if stroke is None:
        return QgsFillSymbol.createSimple({'color': colour, 'outline_style': 'no'})
    return QgsFillSymbol.createSimple({'color': colour, 'outline_color': stroke, 'outline_width': width,
                                       'outline_width_unit': 'MM', 'outline_style': style})


def outline(colour, width=0.5):
    """a POI area: no fill, a dashed line in the class colour on a white casing, so it reads on any building fill"""
    sym = QgsFillSymbol.createSimple({'style': 'no', 'outline_color': '#ffffff', 'outline_width': str(width + 0.4),
                                      'outline_width_unit': 'MM', 'outline_style': 'solid'})
    sym.appendSymbolLayer(QgsSimpleFillSymbolLayer.create({'style': 'no', 'outline_color': colour, 'outline_width': str(width),
                                                            'outline_width_unit': 'MM', 'outline_style': 'dash'}))
    return sym


def dot(colour, size, stroke='#ffffff', width='0.4'):
    return QgsMarkerSymbol.createSimple({'name': 'circle', 'color': colour, 'outline_color': stroke, 'outline_width': width,
                                         'outline_width_unit': 'MM', 'size': str(size), 'size_unit': 'MM'})


def graduated(expr, cuts, labels, zero_label, zero_sym, sym):
    ranges = [QgsRendererRange(0.0, 0.0, zero_sym, zero_label)]
    edges = [0.0] + cuts + [1e12]
    for i in range(len(edges) - 1):
        ranges.append(QgsRendererRange(edges[i], edges[i + 1], sym(i), labels[i]))
    return QgsGraduatedSymbolRenderer(expr, ranges)


def text_format(size, colour=INK, bold=False, buffer=False):
    t = QgsTextFormat()
    f = QFont('Segoe UI')
    f.setBold(bold)
    t.setFont(f)
    t.setSize(size)
    t.setColor(QColor(colour))
    if buffer:
        b = QgsTextBufferSettings()
        b.setEnabled(True)
        b.setSize(0.8)
        b.setColor(QColor('#ffffff'))
        t.setBuffer(b)
    return t


def labeling(expr, max_scale_denominator, size=7, fit=False, margin=0.8, colour=INK):
    """a label on its own feature: centred on a point inside it (fit: only where the whole label fits inside), at least
    `margin` mm from any other label, so two numbers never run together"""
    s = QgsPalLayerSettings()
    s.fieldName = expr
    s.isExpression = True
    s.scaleVisibility = True
    s.minimumScale = max_scale_denominator          # visible only when zoomed in further than this
    s.setFormat(text_format(size, colour, buffer=True))
    s.placement = Qgis.LabelPlacement.OverPoint
    s.centroidInside = True
    s.fitInPolygonOnly = fit
    t = s.thinningSettings()
    t.setLabelMarginDistance(margin)
    t.setLabelMarginDistanceUnit(Qgis.RenderUnit.Millimeters)
    s.setThinningSettings(t)
    return QgsVectorLayerSimpleLabeling(s)


def number(v, decimals_from_10=0):
    """a value (field reference or expression) as the labels and map tips write it, in the legends' English format: from 10
    up with `decimals_from_10` decimals, one decimal below, '<0.1' for what would round to 0.0"""
    return (f"CASE WHEN {v} >= 10 THEN format_number({v}, {decimals_from_10}, 'en') "
            f"WHEN {v} >= 0.05 THEN format_number({v}, 1, 'en') WHEN {v} > 0 THEN '<0.1' ELSE '0' END")


def add_styles(lyr, styles, current):
    sm = lyr.styleManager()
    for k, (name, renderer, lab) in enumerate(styles):
        if k == 0:
            sm.renameStyle(sm.currentStyle(), name)
        else:
            assert sm.addStyleFromLayer(name), f'could not add style {name}'
            assert sm.setCurrentStyle(name), f'could not switch to {name}'
        lyr.setRenderer(renderer)
        lyr.setLabeling(lab) if lab is not None else None
        lyr.setLabelsEnabled(lab is not None)
    assert sm.setCurrentStyle(current), f'could not switch back to {current}'
    assert len(sm.styles()) == len(styles), sm.styles()


def field_values(lyr, field):
    i = lyr.fields().indexOf(field)
    assert i >= 0, f'{lyr.name()}: no field {field}'
    req = QgsFeatureRequest().setFlags(QgsFeatureRequest.Flag.NoGeometry).setSubsetOfAttributes([i])
    return [f.attributes()[i] for f in lyr.getFeatures(req)]


# --- the layers -----------------------------------------------------------------------------------------------
bld = layer('buildings', 'Buildings')
ppoly = layer('poi_polygons', 'POIs - polygons (mapped as areas)')
ppts = layer('poi_points', 'POIs - points')
zover = layer('zones', 'Zones - total in the zone (zoomed out)')
zline = layer('zones', 'Zone boundaries')
for lyr in (bld, ppoly, ppts, zover):
    bad = [f.name() for f in lyr.fields() if f.name().startswith(CHANGE)]
    assert not bad, f'{lyr.name()} carries change or VISUM input fields: {bad}'
for lyr in (bld, ppoly, ppts):
    lyr.setScaleBasedVisibility(True)
    lyr.setMinimumScale(DETAIL_SCALE)
zover.setScaleBasedVisibility(True)
zover.setMaximumScale(DETAIL_SCALE)
HAS_USED = bld.fields().indexOf('labels_used') >= 0
P_USED = ppts.fields().indexOf('poi_labels_used') >= 0

VALUE_ROWS = ''.join(f'<tr><td>{title}</td><td align="right">[% {number(chr(34) + field + chr(34), 1)} %]</td></tr>'
                     for _, title, field, _, _ in CATS)
B_USED = ('<br>labels used: <b>[% "labels_used" %]</b>' if HAS_USED else '')
bld.setMapTipTemplate('<b>[% coalesce("name", "building_id") %]</b><br>[% "bosserhof_class" %] - [% "label_en" %]<br>'
                      '[% "storeys" %] storeys, floor [% format_number("floor_area_m2", 0, \'en\') %] m², used [% format_number("occupied_m2", 0, \'en\') %] m²<br>'
                      '<span style="color:#52514e">model labels: [% "mid_labels_merged" %]</span>' + B_USED +
                      f'<table style="font-size:9pt">{VALUE_ROWS}</table><span style="color:#52514e">building values include its POIs</span>')
bld.setDisplayExpression('coalesce("name", "building_id")')
for lyr in (ppoly, ppts):
    lyr.setMapTipTemplate('<b>[% coalesce("name", "poi_id") %]</b><br>[% "poi_class" %]<br>'
                          '<span style="color:#52514e">model labels: [% "poi_mid_labels" %] - in [% "building_id" %]</span>'
                          + ('<br>labels used: <b>[% "poi_labels_used" %]</b>' if P_USED else '') + '<br>'
                          'used [% format_number("occupied_m2", 0, \'en\') %] m²'
                          f'<table style="font-size:9pt">{VALUE_ROWS}</table>')
    lyr.setDisplayExpression('coalesce("name", "poi_id")')
ZONE_TIP = ('<b>[% "NAME" %]</b> ([% "NO" %])<table style="font-size:9pt">'
            + ''.join(f'<tr><td>{title}</td><td align="right">[% {number(chr(34) + field + chr(34), 1)} %]</td></tr>'
                      for _, title, field, _, _ in CATS)
            + '</table><span style="color:#52514e">total in the zone: the sum over its buildings</span>')
for lyr in (zover, zline):
    lyr.setMapTipTemplate(ZONE_TIP)
    lyr.setDisplayExpression('"NAME"')

report = {}
b_styles, poly_styles, pt_styles, z_styles = [], [], [], []
for theme, title, field, unit, ramp in CATS:
    vals = field_values(bld, field)
    cuts, n_pos = breaks(vals, (0.40, 0.70, 0.90, 0.97))
    labels = class_labels(cuts, '  (top 3 %)')
    q = f'"{field}"'
    # buildings: their value, written on them when zoomed in
    b_lab = labeling(f'CASE WHEN {q} > 0 THEN {number(q)} END', 5000)
    b_styles.append((title, graduated(q, cuts, labels, '0 (does not carry it)', fill(ZERO), lambda i: fill(ramp[i])), b_lab))
    # POIs on the buildings' breaks, so a colour means the same amount on every layer; POI areas as outlines only, so the
    # building under them keeps showing its own value
    r = graduated(q, cuts, labels, '0 (does not carry it)',
                  QgsFillSymbol.createSimple({'style': 'no', 'outline_color': '#8a8983', 'outline_width': '0.25',
                                              'outline_width_unit': 'MM', 'outline_style': 'dash'}),
                  lambda i: outline(ramp[i]))
    r.setOrderBy(QgsFeatureRequest.OrderBy([QgsFeatureRequest.OrderByClause('$area', False)]))   # large areas first, small ones on top
    r.setOrderByEnabled(True)
    poly_styles.append((title, r, None))
    r = graduated(q, cuts, labels, '0 (does not carry it)', dot('#8a8983', 1.4, '#ffffff', '0.2'), lambda i: dot(ramp[i], SIZES[i]))
    r.setOrderBy(QgsFeatureRequest.OrderBy([QgsFeatureRequest.OrderByClause(q, True)]))  # the largest on top
    r.setOrderByEnabled(True)
    pt_styles.append((title, r, None))
    # zones: the class's total in the zone, written inside the zone (where it fits) between 1:400,000 and 1:150,000
    zv = field_values(zover, field)
    z_cuts, n_z = breaks(zv, (0.20, 0.40, 0.60, 0.80))
    z_lab = labeling(f'CASE WHEN {q} > 0 THEN {number(q)} END', ZONE_LABEL_SCALE, fit=True, margin=1.5)
    z_styles.append((title, graduated(q, z_cuts, class_labels(z_cuts, ''), '0 (none in the zone)',
                                      fill(ZONE_ZERO, '#ffffff', '0.1'), lambda i: fill(ramp[i], '#ffffff', '0.1')), z_lab))
    report[title] = {'buildings carrying it': n_pos, 'breaks': cuts, 'zones carrying it': n_z, 'zone breaks': z_cuts,
                     'region total': round(sum(v for v in zv if v), 1)}

add_styles(bld, b_styles, 'Workers')
add_styles(ppoly, poly_styles, 'Workers')
add_styles(ppts, pt_styles, 'Workers')
add_styles(zover, z_styles, 'Workers')

# zone boundaries (below 1:150,000): thin above 1:50,000, the atlas zone drawn heavy in the atlas layout; one style per class
# that writes the zone's total of the class inside the zone, with the zone's name below 1:60,000
zsym = QgsFillSymbol.createSimple({'style': 'no', 'outline_color': '#4b4a46', 'outline_width': '0.4', 'outline_width_unit': 'MM'})
zsym.symbolLayer(0).setDataDefinedProperty(QgsSymbolLayer.Property.StrokeWidth, QgsProperty.fromExpression(
    'CASE WHEN @atlas_featureid = $id THEN 0.9 WHEN @map_scale > 50000 THEN 0.12 ELSE 0.4 END'))
zline.setScaleBasedVisibility(True)                  # zoomed out, the zones' own white outlines show them
zline.setMinimumScale(DETAIL_SCALE)
zl_styles = []
for theme, title, field, unit, ramp in CATS:
    q = f'"{field}"'
    zl_lab = labeling(f"CASE WHEN @map_scale > 60000 THEN (CASE WHEN {q} > 0 THEN {number(q)} END) "
                      f"ELSE \"NAME\" || '\\n' || {number(q)} END", DETAIL_SCALE, size=8, fit=True, margin=1.5,
                      colour='#222222')
    zl_styles.append((title, QgsSingleSymbolRenderer(zsym.clone()), zl_lab))
add_styles(zline, zl_styles, 'Workers')

# basemap.de Web Raster grey (BKG / AdV, keyless, CC BY 4.0); CARTO Positron now asks for an API key
positron = QgsRasterLayer('type=xyz&url=https://sgx.geodatenzentrum.de/wmts_basemapde/tile/1.0.0/de_basemapde_web_raster_grau/default/'
                          'GLOBAL_WEBMERCATOR/{z}/{y}/{x}.png&zmax=18&zmin=0', 'Basemap: basemap.de grey', 'wms')
assert positron.isValid(), 'basemap.de did not load'
positron.renderer().setOpacity(0.55)
osm = QgsRasterLayer('type=xyz&url=https://tile.openstreetmap.org/{z}/{x}/{y}.png&zmax=19&zmin=0', 'Basemap: OpenStreetMap (grey)', 'wms')
osm.hueSaturationFilter().setGrayscaleMode(QgsHueSaturationFilter.GrayscaleMode.GrayscaleLuminosity)
osm.renderer().setOpacity(0.5)

ORDER = [zline, ppts, ppoly, bld, zover, positron, osm]
for lyr in ORDER:
    project.addMapLayer(lyr, False)
root = project.layerTreeRoot()
for lyr in ORDER:
    root.addLayer(lyr)
root.findLayer(osm.id()).setItemVisibilityChecked(False)
ext = zover.extent()
ext.grow(2000)
project.viewSettings().setDefaultViewExtent(QgsReferencedRectangle(ext, zover.crs()))

# --- the map themes: one per class ---------------------------------------------------------------------------------
model = QgsLayerTreeModel(root)
themes = project.mapThemeCollection()
for theme, title, *_ in CATS:
    for lyr in ORDER:
        root.findLayer(lyr.id()).setItemVisibilityChecked(lyr is not osm)
    for lyr in (bld, ppoly, ppts, zover, zline):
        assert lyr.styleManager().setCurrentStyle(title), f'{lyr.name()}: no style {title}'
    themes.insert(theme, QgsMapThemeCollection.createThemeFromCurrentState(root, model))
for lyr in (bld, ppoly, ppts, zover, zline):
    lyr.styleManager().setCurrentStyle('Workers')


# --- the print layouts ----------------------------------------------------------------------------------------------
MM = Qgis.LayoutUnit.Millimeters


def label_item(layout, text, x, y, w, h, size, colour=INK, bold=False):
    it = QgsLayoutItemLabel(layout)
    it.setText(text)
    it.setTextFormat(text_format(size, colour, bold))
    it.attemptMove(QgsLayoutPoint(x, y, MM))
    it.attemptResize(QgsLayoutSize(w, h, MM))
    layout.addLayoutItem(it)
    return it


def legend_item(layout, map_item, lyr, title, x, y, w, h, background=False):
    lg = QgsLayoutItemLegend(layout)
    lg.setLinkedMap(map_item)
    lg.setSyncMode(Qgis.LegendSyncMode.Manual)
    g = lg.model().rootGroup()
    g.clear()
    node = g.addLayer(lyr)
    QgsLegendRenderer.setNodeLegendStyle(node, QgsLegendStyle.Style.Hidden)
    lg.setTitle(title)
    lg.rstyle(QgsLegendStyle.Style.Title).setTextFormat(text_format(8, INK, bold=True))
    lg.rstyle(QgsLegendStyle.Style.SymbolLabel).setTextFormat(text_format(7, INK2))
    lg.setSymbolWidth(5)
    lg.setSymbolHeight(3)
    lg.setBackgroundEnabled(background)
    if background:
        lg.setBackgroundColor(QColor(255, 255, 255, 225))
    lg.setResizeToContents(True)
    lg.attemptMove(QgsLayoutPoint(x, y, MM))
    layout.addLayoutItem(lg)
    return lg


def map_item(layout, theme, x, y, w, h, extent=None):
    m = QgsLayoutItemMap(layout)
    m.attemptMove(QgsLayoutPoint(x, y, MM))
    m.attemptResize(QgsLayoutSize(w, h, MM))
    m.setCrs(zover.crs())
    if extent is not None:
        m.zoomToExtent(extent)
    m.setFollowVisibilityPreset(True)
    m.setFollowVisibilityPresetName(theme)
    m.setFrameEnabled(True)
    m.setFrameStrokeColor(QColor('#c3c2b7'))
    layout.addLayoutItem(m)
    return m


def new_layout(name):
    lay = QgsPrintLayout(project)
    lay.initializeDefaults()
    lay.setName(name)
    lay.pageCollection().page(0).setPageSize('A2', QgsLayoutItemPage.Orientation.Landscape)
    project.layoutManager().addLayout(lay)
    return lay


W, GAP, X0, Y0 = 90.0, 6.8, 10.0, 30.0
region = zover.extent()
region.grow(1500)
W2, H2, GAP2 = 139.0, 120.0, 6.0
PANELS = [(t, ti, f, u) for t, ti, f, u, _ in CATS]

# 1) the whole region, the total of every class in each zone: 6 x 2 panels
lay = new_layout('Overview - total of every class per zone (region)')
label_item(lay, 'Step 08 - the total of every class in each zone', 10, 7, 500, 10, 18, bold=True)
label_item(lay, 'Each zone coloured by the total of the class on its buildings (POIs included). Blue: the seven VISUM classes as '
                'redistributed to the buildings (where places share totals across zone borders, a zone\'s sum differs from its VISUM '
                'input). Orange: the five visitor values (visits per average working day, area x rate). Colour classes per class: about '
                'quintiles of the zones (rounded). Zoom into the main map below 1:150,000 to see the buildings and POIs.',
           10, 17, 560, 8, 9, INK2)
for k, (theme, ptitle, field, unit) in enumerate(PANELS):
    col, row = k % 6, k // 6
    x, y = X0 + col * (W + GAP), Y0 + row * 192
    label_item(lay, ptitle, x, y, W, 7, 12, bold=True)
    m = map_item(lay, theme, x, y + 8, W, 140, region)
    legend_item(lay, m, zover, f'{unit} in the zone', x, y + 150, W, 36)

# 2) the atlas: all classes for one zone, buildings and POIs: 4 x 3 panels
lay2 = new_layout('Zone atlas - all classes (buildings and POIs)')
atlas = lay2.atlas()
atlas.setCoverageLayer(zline)
atlas.setPageNameExpression('"NAME"')
atlas.setSortFeatures(True)
atlas.setSortExpression('"NAME"')
atlas.setEnabled(True)
label_item(lay2, '[% @atlas_pagename %]  (zone [% attribute(@atlas_feature, \'NO\') %])', 10, 7, 500, 10, 18, bold=True)
label_item(lay2, 'Each panel title gives the zone\'s total of the class (the sum over its buildings). Buildings filled by their value '
                 'of each class (building values include their POIs); POI areas as dashed outlines and POI points as circles in the '
                 'colour of their own value, on the same classes. Grey: does not carry the class. Pick the zone in the Atlas toolbar.',
           10, 17, 560, 8, 9, INK2)
for k, (theme, ptitle, field, unit) in enumerate(PANELS):
    col, row = k % 4, k // 4
    x, y = 10 + col * (W2 + GAP2), 30 + row * (H2 + 9)
    total = number(f"attribute(@atlas_feature, '{field}')")
    label_item(lay2, f'{ptitle}  ·  zone total [% {total} %] {UNIT_SHORT[unit]}'.rstrip(), x, y, W2, 7, 11, bold=True)
    m = map_item(lay2, theme, x, y + 7, W2, H2 - 7, region)     # an extent with the item's shape, or the atlas resizes the item
    m.setAtlasDriven(True)
    m.setAtlasScalingMode(QgsLayoutItemMap.AtlasScalingMode.Auto)
    m.setAtlasMargin(0.08)
    legend_item(lay2, m, bld, unit, x + 1.5, y + 8.5, 40, 30, background=True)

# --- write, then read back ---------------------------------------------------------------------------------------
assert project.write(str(FINAL)), 'project write failed'
xml = FINAL.read_text(encoding='utf-8')
_abs = re.findall(r'(\w+)="[^"]*(?:Capacity_Calculation|AppData)[^"]*"', xml)   # the atlas keeps its coverage source absolute; it resolves by layer id
assert './08_redistribution_values_view.gpkg|layername=buildings' in xml and set(_abs) <= {'coverageLayerSource'}, f'absolute paths in {_abs}'
assert not re.search(r'(?:"|&quot;|&apos;)(?:d_|moved_|chg_pct_)[A-Za-z]', xml), 'the project refers to change fields'
print(f'ok: {FINAL} ({FINAL.stat().st_size / 1e3:,.0f} kB)')
print(f'  {len(themes.mapThemes())} map themes:', themes.mapThemes())
print('  layouts:', [l.name() for l in project.layoutManager().printLayouts()])
for t, v in report.items():
    print(f'  {t}: {v}')
p2 = QgsProject()
assert p2.read(str(FINAL)), 'read back failed'
bad = [l.name() for l in p2.mapLayers().values() if not l.isValid() and l.type() != Qgis.LayerType.Raster]
assert not bad, f'invalid layers on read back: {bad}'
assert sorted(p2.mapThemeCollection().mapThemes()) == sorted(themes.mapThemes()), 'themes lost on read back'
assert len(p2.layoutManager().printLayouts()) == 2, 'layouts lost on read back'
print('  read back ok')
p2.clear()
project.clear()
sys.stdout.flush()
os._exit(0)
