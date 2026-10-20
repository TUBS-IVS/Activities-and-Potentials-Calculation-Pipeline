"""Step 08: the visitor rates of the five labels without a zone total (config VISITOR_RULES, notebook 08 section 8).
visitor_rate_id() is lib/floor_rules' lookup with these rules:
  sport_words        the sports type words for every sports class and before a generic or several-valued sports use;
  library            a university library 0, research / specialist / archive / private libraries the public-office rate;
  cafe_zero_by_rate  the cafe zero wherever the gastronomy rate applies; academy: company academies by their own words;
  no_zone_zero       no value for a building in no zone; school_hall: lessons at a school's sports hall 0;
  audience_zero      no meetup at a leisure venue whose rate counts its whole audience; events: the event rate for event venues.
The counter cap and the office boxes are applied in the value loop of notebook 08 (they need the unit's floor).
"""
import re


def sport_use_rate(use, sport_uses):
    for rid, uses in sport_uses.items():
        if use in uses:
            return rid
    return None


def _words(text, pats):
    for pat, rid in pats:
        if re.search(pat, text or '', flags=re.IGNORECASE):
            return rid
    return None


def visitor_rate_id(label, u, *, group_rates, class_rates, type_rates, default_rates, sport_uses, dance_uses, events_uses,
                     car_uses, gastro_class, hotel_classes, industry_class, rules=None):
    """The rate id of one unit for one of the five labels without a zone total, and the tier that set it - lib/floor_rules
    visitor_rate_id with the rules of config VISITOR_RULES (each switched by its key; with rules = {} it is floor_rules'). u: as
    there, plus text (the unit's own names and types), zoned (its building lies in a zone), labels and access (a POI's OSM access tag)."""
    R = rules or {}
    g = u.group if isinstance(u.group, str) else None
    use = u.use if isinstance(u.use, str) else ''
    c = u.cls
    text = getattr(u, 'text', '') or ''
    # a building in no zone gets no value - the allocation leaves it out too
    if R.get('no_zone_zero') and not getattr(u, 'zoned', True):
        return 'ZERO', 'zero: no zone'
    if u.staff_only:
        return 'ZERO', 'zero: staff only'
    if label == 'business' and (g == 'hotel' or c in hotel_classes):
        return 'ZERO', 'zero: hotel'
    rid, tier = _lookup(label, u, g, use, c, text, R, group_rates=group_rates, class_rates=class_rates, type_rates=type_rates,
                        default_rates=default_rates, sport_uses=sport_uses, dance_uses=dance_uses, events_uses=events_uses,
                        car_uses=car_uses, gastro_class=gastro_class, industry_class=industry_class)
    if tier.startswith('zero'):
        return rid, tier
    # riding, shooting and tennis words replace only the generic hall rate (clubhouse and multi-sport words keep it)
    hw = R.get('hall_words')
    if hw and label == 'sports' and rid == 'S_HALL':
        w = _words(text, hw)
        if w and w != 'S_HALL':
            return w, 'type words'
    # the cafe zero wherever the gastronomy rate would apply (any POI group)
    if R.get('cafe_zero_by_rate') and label == 'meetup' and u.leisure and rid == 'M_GASTRO':
        return 'ZERO', 'zero: also leisure'
    # the cafe zero for the rates that count a leisure venue's whole audience
    az = R.get('audience_zero')
    if az and u.leisure and label in az['labels'] and rid in az['rates'] and use not in az.get('exclude_uses', ()):
        return 'ZERO', 'zero: also leisure (audience rate)'
    return rid, tier


def _lookup(label, u, g, use, c, text, R, *, group_rates, class_rates, type_rates, default_rates, sport_uses, dance_uses,
            events_uses, car_uses, gastro_class, industry_class):
    if label == 'errands':
        if u.parking:
            return 'E_PARKING', 'zero: parking'
        rid = group_rates['errands'].get(g)
        if g == 'small_retail':
            rid = 'E_COUNTER'
        elif g == 'big_box':
            rid = 'E_VEHICLE' if use in car_uses else 'E_COUNTER'
        elif g == 'community':
            rid = 'E_PRACTICE' if use == 'centre' else 'E_PUBOFF'
        elif g == 'culture' and use == 'library':
            rid = 'E_LIBRARY'
            lib = R.get('library')            # the public-library rate only for public lending libraries
            if lib:
                uni = 'university' in (getattr(u, 'labels', ()) or ()) or c in lib['university_classes']
                if uni and lib.get('university_zero'):
                    return 'ZERO', 'zero: university library'
                if (uni or c in lib['classes'] or re.search(lib['words'], text, flags=re.IGNORECASE)
                        or getattr(u, 'access', '') in lib['access']):
                    rid = lib['rate']
        if rid:
            return rid, 'use'
    if label == 'sports':
        sw = R.get('sport_words')             # the type words before a generic or several-valued POI use
        if sw:
            generic = sw['generic_uses']
            if ';' in use and sw.get('several_uses', True):   # several sports: their one rate, else read like a generic use
                rs = {sport_use_rate(p_.strip(), sport_uses) for p_ in use.split(';') if p_.strip() and p_.strip() not in generic}
                rs.discard(None)
                ur, specific = (rs.pop(), True) if len(rs) == 1 else (None, False)
            else:
                ur = sport_use_rate(use, sport_uses)
                specific = ur is not None and use not in generic
            if g == 'community':
                return 'S_CLUB', 'use'
            if g in ('sport', 'unmapped', 'culture', 'small_school') and specific:
                return ur, 'use'
            w = _words(text, sw['words'])
            if w:
                return w, 'type words'
            if g in ('sport', 'unmapped', 'culture', 'small_school') and ur:
                return ur, 'use'
            if g == 'sport':
                return 'S_HALL', 'use'
        else:
            if g in ('sport', 'unmapped', 'culture', 'small_school'):
                rid = sport_use_rate(use, sport_uses)
                if rid:
                    return rid, 'use'
                if g == 'sport':
                    return 'S_HALL', 'use'
            if g == 'community':
                return 'S_CLUB', 'use'
    if label == 'meetup':
        if u.plain_home:
            return 'ZERO', 'zero: plain home'
        if u.leisure and (g == 'gastronomy' or (g is None and c == gastro_class)):
            return 'ZERO', 'zero: also leisure'
        ev = R.get('events')                  # event venues by use (any group) or by their own type words
        if ev:
            if use in ev['uses']:
                return 'M_EVENTS', 'use'
            if (g in ev['word_groups'] and re.search(ev['words'], text, flags=re.IGNORECASE)
                    and not re.search(ev.get('not_words', '^$'), text, flags=re.IGNORECASE)):
                return 'M_EVENTS', 'type words'
        if g == 'culture' and use in events_uses:
            return 'M_EVENTS', 'use'
        rid = group_rates['meetup'].get(g)
        if rid:
            return rid, 'use'
    if label == 'lessons':
        if u.co_school:
            return 'ZERO', 'zero: school or university building'
        if g == 'industry' or c == industry_class:
            return 'ZERO', 'zero: company academy'
        ac = R.get('academy')                 # company academies by their own words, in any class
        if ac and re.search(ac['words'], text, flags=re.IGNORECASE) and (
                re.search(ac['company'], text, flags=re.IGNORECASE) or c in ac['classes']):
            return 'ZERO', 'zero: company academy'
        sh = R.get('school_hall')             # a school's sports hall is part of the school
        if sh and re.search(sh, text, flags=re.IGNORECASE):
            return 'ZERO', 'zero: school or university building'
        if g == 'small_school':
            return ('L_DANCE' if use in dance_uses else 'L_SMALL'), 'use'
        if g in ('sport', 'unmapped'):
            rid = sport_use_rate(use, sport_uses)
            if rid:
                return rid, 'use'
            if g == 'sport':
                return 'S_HALL', 'use'
        rid = group_rates['lessons'].get(g)
        if rid:
            return rid, 'use'
    rid = class_rates[label].get(c)
    if label == 'sports' and R.get('sport_words') and c in R['sport_words'].get('cmp_classes', ()) and getattr(u, 'kind', '') != 'poi':
        rid = 'CMP'                           # a POI unit read its own words above; its building's type may name another tenant
    if rid == 'CMP':
        pats, fallback = type_rates[label]
        if label == 'sports' and R.get('sport_words'):     # the class's type words: the sports words (cmp_words, else words)
            pats = R['sport_words'].get('cmp_words', R['sport_words']['words'])
        for pat, r in pats:
            if re.search(pat, u.btype or '', flags=re.IGNORECASE):
                return r, 'class (type words)'
        if (label == 'meetup' and R.get('events') and re.search(R['events']['words'], u.btype or '', flags=re.IGNORECASE)
                and not re.search(R['events'].get('not_words', '^$'), text + ' | ' + (u.btype or ''), flags=re.IGNORECASE)):
            return 'M_EVENTS', 'class (type words)'
        return fallback, 'class (type words)'
    if (label == 'meetup' and R.get('events') and rid == 'M_COMMUNITY' and re.search(R['events']['words'], text, flags=re.IGNORECASE)
            and not re.search(R['events'].get('not_words', '^$'), text, flags=re.IGNORECASE)):
        return 'M_EVENTS', 'class (type words)'
    if rid:
        return rid, 'class'
    return default_rates[label], 'default'
