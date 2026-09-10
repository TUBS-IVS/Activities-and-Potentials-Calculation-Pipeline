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

## The reverse case: one site, many buildings

**Status:** decided 2026-09-10. Not implemented; belongs to 04.5.

A `site` POI is the mirror image of the nesting above: one OSM polygon (a
school's grounds, a hospital, a campus, a riding centre) spanning several ALKIS
buildings. The mapper drew the area to describe the whole facility, so the
facility's activity happens in every building on it.

Rule: **every building kept by 04.4 whose representative point lies inside the
site polygon receives the site's use and name.** No size threshold here. The
04.4 rescue uses one (`POI_SITE_RESCUE_MIN_AREA_M2`) because there the question
is keep-or-drop; here the question is only who shares the demand, and the
redistribution weights by volume. Measured after the 04.4 filter: 8,045 kept
buildings lie inside a site, 7,207 of them with no POI of their own; 2,696 of
those are under 50 m² and hold 0.3 % of the volume inside sites. The sheds
receive the label and weigh nothing; the pending size rule on `31001_2000` may
remove them anyway.

Still open for 04.5, each with a proposed answer:

- a building with its own point/footprint POI *and* a site around it keeps
  both, as a list with the role marked, so the classification sees "school
  site, café point" rather than one overwriting the other;
- a site's demand is shared across its buildings by volume — the same weight
  the redistribution uses, and the mirror of the area split above;
- nested sites (a sports-centre site inside a campus site): attach both.

## POIs that miss their building

**Status:** decided 2026-09-10. Not implemented; belongs to 04.5.

The 04.4 rescue is strict containment and stays that way: no buffer, no snap.
The snap is an *assignment* device for 04.5, so that a café whose node was
placed a few metres outside the wall still lands on its building instead of
staying unassigned. Nothing gets rescued by it.

Measured on the filtered layer (point and footprint POIs, 22,177):

    inside a kept building                17,966
    inside a dropped structure (canopy)      233   -> ignored by decision, not re-homed
    outside every footprint                3,978   -> 3,369 have a kept building within 100 m, 609 none

Most of the 3,978 are features that legitimately have no building - 659
swimming pools, 185 attractions, 165 ruins, 139 graveyards, 128 information
boards - and snapping them would hang a garden pool on the neighbour's house.
So the snap applies only to **building-bound uses**, decided by the data rather
than by a hand list: a `poi_use` is building-bound when at least 80 % of its
POIs region-wide sit inside a footprint (133 uses: restaurant 95 %, supermarket
97 %, hairdresser 95 %, doctors 95 %, cafe 91 %, ...). Uses under 50 %
(swimming_pool 3 %, grave_yard 2 %, ruins 24 %, information 30 %, attraction
31 %, public_bookcase 12 %, christian 24 %) are outdoor and are never snapped.

Of the 1,024 outside POIs with a building-bound use, the distance to the
nearest kept building is:

    within   5 m     538   53 %
    within  10 m     720   70 %
    within  25 m     904   88 %
    within  50 m     973   95 %
    within 100 m   1,006   98 %
    none            18

**Radius: 50 m, decided 2026-09-10.** The previous pipeline used 100 m (its
run: 14,256 inside, 1,921 snapped, 31 unmatched); beyond 50 m the nearest
building is more likely the wrong one than the right one, and the extra 33
POIs are not worth that. Rule 1 structures are never a
snap target, and the 233 POIs inside them are ignored rather than re-homed
(decided 2026-09-10): the petrol station's shop is a `31001_2130` building of
its own, and a pharmacy whose node sits under its entrance canopy is judged by
its building's class instead.
