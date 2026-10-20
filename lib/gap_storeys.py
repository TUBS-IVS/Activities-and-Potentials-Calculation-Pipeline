"""Step 08: the storeys of the OSM-only buildings on step 04's placeholder height (notebook 08 section 3.2b, config
FLOOR_OSM_GAP_STOREYS).

Step 04 fills the gaps in ALKIS with OSM outlines (source 'osm'). Where OSM gives neither a height nor building:levels, it writes
OSM_GAP_DEFAULT_FLOORS x OSM_GAP_FLOOR_HEIGHT_M = 1 x 2.0 m as the height - a placeholder, not a measurement - which the height
rule reads as one storey. estimate() gives such a building of a storeyed class "the class-and-size median": the median storeys of the
ALKIS buildings of its class and footprint band that have a LoD2 eaves height, no hall and no dwellings.
"""
import numpy as np
import pandas as pd


def estimate(b, base, *, mode, placeholder_height_m, placeholder_tol_m, keep_one_classes, keep_one_tags, only_classes,
                max_area_m2, bands_m2, min_n):
    """A storey estimate for the OSM-only buildings without OSM building:levels and without an OSM height.
    Step 04 gave them OSM_GAP_DEFAULT_FLOORS x OSM_GAP_FLOOR_HEIGHT_M (1 x 2.0 m) as their height, so the height rule
    round(h / 3.5 m) makes every one of them one storey. The reference: the ALKIS buildings with a LoD2 eaves height, no hall and
    no dwellings, and their height-rule storeys. mode 'class': the median of the same Bosserhof class; 'band': of the same class
    and footprint band (bands_m2 are the band edges), with fewer than min_n such buildings the median of every class in that
    band. A half median rounds down (the storeys more than half of the reference buildings reach). Never a hall, a class in
    keep_one_classes, an OSM building tag in keep_one_tags, a class outside only_classes (None: every class) or an outline of
    max_area_m2 or more (None: no limit). Returns the mask of the placeholder rows and a frame (index = bld index) with cls,
    band, source, median, n and storeys for the rows that take an estimate."""
    hm = b['volume_3d_m3'] / b['area_m2']
    gap = (b['source'].eq('osm') & ~base['osm'] & (base['hall'] == '')
           & (hm - placeholder_height_m).abs().lt(placeholder_tol_m))
    t = gap & ~b['bosserhof_class'].isin(keep_one_classes) & ~b['osm_tag'].fillna('').isin(keep_one_tags)
    if only_classes is not None:
        t &= b['bosserhof_class'].isin(only_classes)
    if max_area_m2:
        t &= b['area_m2'].lt(max_area_m2)
    ref = b['source'].eq('alkis') & (base['hall'] == '') & ~b['RC'].astype(bool) & b['height_eaves_m'].gt(0)
    band = pd.Series(np.searchsorted(np.asarray(bands_m2, dtype=float), b['area_m2'].to_numpy(), side='right'), index=b.index)
    hs = base['height_storeys']
    g_cls = hs[ref].groupby(b.loc[ref, 'bosserhof_class']).agg(['median', 'size'])
    g_cb = hs[ref].groupby([b.loc[ref, 'bosserhof_class'], band[ref]]).agg(['median', 'size'])
    g_b = hs[ref].groupby(band[ref]).agg(['median', 'size'])
    rows = []
    for i in b.index[t]:
        c, k = b.at[i, 'bosserhof_class'], int(band[i])
        if mode == 'class':
            ok = c in g_cls.index and g_cls.at[c, 'size'] >= min_n
            m, n, s = (g_cls.at[c, 'median'], int(g_cls.at[c, 'size']), 'class') if ok else (np.nan, 0, 'none')
        elif (c, k) in g_cb.index and g_cb.at[(c, k), 'size'] >= min_n:
            m, n, s = g_cb.at[(c, k), 'median'], int(g_cb.at[(c, k), 'size']), 'class and size'
        else:
            m, n, s = g_b.at[k, 'median'], int(g_b.at[k, 'size']), 'size'
        rows.append((i, c, k, s, m, n))
    est = pd.DataFrame(rows, columns=['idx', 'cls', 'band', 'source', 'median', 'n']).set_index('idx')
    est['storeys'] = np.maximum(1.0, np.ceil(est['median'].fillna(1.0) - 0.5))
    return gap, est


def check_config(cfg):
    """FLOOR_OSM_GAP_STOREYS: its keys, a known mode, rising band edges, a positive placeholder height and min_n"""
    need = {'mode', 'placeholder_height_m', 'placeholder_tol_m', 'keep_one_classes', 'keep_one_tags', 'only_classes', 'max_area_m2',
            'bands_m2', 'min_n'}
    e = list(cfg.get('bands_m2', []))
    if (set(cfg) != need or cfg['mode'] not in ('band', 'class') or not cfg['placeholder_height_m'] > 0 or not cfg['min_n'] >= 1
            or e != sorted(e) or len(set(e)) != len(e)):
        raise ValueError(f'FLOOR_OSM_GAP_STOREYS: {sorted(set(cfg) ^ need)} or a value out of range')
