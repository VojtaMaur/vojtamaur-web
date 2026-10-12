"""Count processed hosted searches without counting ignored attempts at the API cap."""


def classify(output, maximum):
    calls = [item for item in output if isinstance(item, dict) and item.get('type') == 'web_search_call']
    # Missing/failed statuses remain conservative chargeable observations. Only
    # the exact observed shape of an extra unprocessed search is excluded.
    processed = sum(item.get('status') == 'completed' for item in calls)
    accounted, ignored = [], []
    for item in calls:
        action = item.get('action') or {}
        unprocessed_at_cap = (type(maximum) is int and maximum > 0 and processed == maximum
            and item.get('status') == 'searching' and action.get('type') == 'search'
            and not action.get('sources') and not action.get('url'))
        (ignored if unprocessed_at_cap else accounted).append(item)
    return accounted, ignored

def unfinished_at_cap(output, maximum):
    """Evidence of ambiguous extra search items, never free/unbilled assertions.

    Only search-shaped unfinished items AFTER exactly the requested number of
    completed searches qualify. Source metadata may be present, so these items
    remain conservatively accounted by classify(). Real completed overages,
    failed/open-page/unknown work and pending work before the cap do not qualify.
    """
    calls = [item for item in output if isinstance(item, dict) and item.get('type') == 'web_search_call']
    if type(maximum) is not int or maximum <= 0 or sum(item.get('status') == 'completed' for item in calls) != maximum:
        return []
    completed, found = 0, []
    for item in calls:
        if item.get('status') == 'completed':
            completed += 1
        action = item.get('action') or {}
        if completed == maximum and item.get('status') == 'searching' and action.get('type') == 'search' and not action.get('url'):
            found.append(item)
    return found
