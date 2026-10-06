"""Parse complete ODS identifiers without conflating neighbouring offers."""
import re

ODS_PATTERN = r'ODS\d{2}-\d{3,4}(?!\d)(?:-(?:STR|CIV|GEO)-[A-Z]{3}|-[A-Z]{3})?'


def reference(value):
    match = re.search(ODS_PATTERN, str(value or ''), re.I)
    return match.group(0).upper() if match else ''


def matches(value, query):
    actual, wanted = reference(value), reference(query)
    return bool(actual and wanted and (
        actual == wanted or (wanted.count('-') == 1 and actual.startswith(wanted + '-'))
    ))
