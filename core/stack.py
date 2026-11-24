"""A stacked bar on the server (templates/ui/_stack.html), the same bar the islands draw (frontend/islands/ui/StackedBar.tsx,
static/css/ds.css, Stacked bar): one whole cut into its parts, each segment as long as its share. `stack()` lays the
parts out once (each segment's start on the whole), so the template only prints numbers: no style attribute, nothing for
the Content-Security-Policy to refuse. A part of 0 stays in the legend and draws no segment."""
from django.utils.formats import number_format

TONES = {'ok', 'warning', 'critical', 'hold', 'neutral', 'note'}


def part(key, label, value, tone):
    """One part: its key, its words, its count and its tone (one of TONES)."""
    if tone not in TONES:
        raise ValueError(f'no stack tone {tone!r}')
    return {'key': key, 'label': str(label), 'value': int(value), 'figure': number_format(int(value)), 'tone': tone}


def stack(label, parts, empty=None):
    """The bar's context: its label, its parts with their segments laid out, the whole, the sentence a screen reader
    hears, and what is said when the whole is 0. The same props the island's StackedBar takes (`props`)."""
    total, at, segments = sum(max(each['value'], 0) for each in parts), 0, []
    for each in parts:
        if each['value'] > 0:
            segments.append({**each, 'x': at})
            at += each['value']
    return {'label': str(label), 'parts': parts, 'segments': segments, 'total': total,
            'said': f"{label}. {', '.join(f'{each['label']} {each['figure']}' for each in parts)}",
            'empty': str(empty) if empty else str(label),
            'props': {'label': str(label), 'parts': parts, 'empty': str(empty) if empty else None}}
