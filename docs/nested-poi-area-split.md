# Splitting a building's weight across nested POIs

**Status:** design agreed 2026-09-09. Not implemented. Step 01 does not yet emit
the columns this needs.

Redistribution keeps the ALKIS/LOD2 **building volume as the weight**. This note
covers only the *internal* question: when one building holds several POIs, how
much of that volume does each one get?

The old pipeline
(`Capacity_Calculation-pipeline-original/Volume-redistribution-VISUM.ipynb`)
divided evenly:

    weight = volume_m3 / n_non_worker

That gives a 12 m² kiosk the same demand as an anchor department store in the
same mall. Where OSM has mapped the individual units we can do better.

## The rule

Give every POI a `split_area_m2`, then split by it:

    share(poi)  = split_area_m2 / SUM(split_area_m2 over siblings)
    weight(poi) = volume_m3 * share(poi)

`split_area_m2` is:

| child geometry | `split_area_m2` |
| --- | --- |
| polygon | its own area |
| point | **median area of its polygon siblings** |
| point, and no polygon siblings exist | `1.0` (any constant) |

That is the whole rule. There is no branching on "does this building have
areas?" — the three cases below fall out of the one formula.

## Why the even split does not need a separate code path

When *no* child has a polygon, every child is imputed the same constant, so
every share is `1/n` and the formula **is** the old even split. The fallback is
not a special case; it is what the formula degenerates to. That matters because
it is the most common shape:

    all children are points      629 parents   1,245 children   -> collapses to 1/n
    all children have area       407 parents   1,007 children   -> pure area split
    MIXED                        163 parents   1,641 children   -> the reason for imputation

Mixed is only 163 parents but holds the most children, because the large parents
are all mixed:

    Schloss-Arkaden        126 children   123 polygons,  3 points
    TU Clausthal           101 children    17 polygons, 84 points
    designer outlets        89 children    88 polygons,  1 point
    Volkswagenwerk          49 children    11 polygons, 38 points

Neither naive option works there. Splitting Schloss-Arkaden evenly across 126
discards 123 measured areas; splitting it purely by area hands 3 real shops a
weight of zero. Imputing the sibling median keeps the measured areas and still
gives the 3 unmapped shops a typical shop's worth of demand.

Measured on `data/output/01_all_pois.gpkg` (34,144 POIs, 2026-09-09):
4,711 POIs nest inside another POI's footprint under 1,625 parents; 2,216 of
those children (47 %) are bare points. Median area of a polygon child is 659 m²;
median of the per-parent medians is 773 m².

## What step 01 must emit

- `poi_parent_id` — the `poi_id` of the smallest POI footprint containing this
  POI, else null. Smallest matters: a shop inside a mall inside a campus should
  point at the mall.
- `poi_role = 'unit'` — a new role for a POI nested inside a **single** building.
  This is *not* the same as today's `site`/`footprint`/`point`, which describe
  how a POI joins to a building. Nesting cuts across that: TU Clausthal and
  Volkswagenwerk are `site` POIs spanning many ALKIS buildings, which is a
  different case from a shop inside one mall, and they must not be treated as
  malls.
- `split_area_m2` — real or imputed, per the table above.

Points already carry `area_m2 = 0.0` rather than null, so a null check will not
find the children needing imputation. Test the geometry type, not the area.

## Traps

- **A parent with children must not also receive a share.** Otherwise the mall is
  weighted as both the whole and its tenants and the building is double-counted.
  Build the label set per ALKIS building *before* computing weights, never per
  POI-building pair — a `site` POI writes onto several buildings.
- **Child polygons are indoor unit outlines, not footprints.** At
  Schloss-Arkaden they sum to 159 % of the building footprint, across 3 levels.
  Never use them as an absolute area; only as a within-building share. `level`
  (in the folded `tags` JSON) is on all Schloss-Arkaden children but only ~18 %
  of nested children region-wide.
- **Shares must sum to 1.0 per building**, or demand leaks out of the zone.
- The share is dimensionless and computed within one building only, so m² is
  never compared against m³ across buildings. A building's total contribution to
  its zone is unchanged — only its internal activity ratio improves.
