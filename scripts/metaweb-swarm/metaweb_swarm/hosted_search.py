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
