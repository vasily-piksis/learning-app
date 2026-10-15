import json
import sys
import unicodedata

if unicodedata.unidata_version != "15.1.0":
    raise SystemExit("Generation requires Unicode 15.1.0 (CPython 3.13)")
ranges = []
for point in range(sys.maxunicode + 1):
    category = unicodedata.category(chr(point))[0]
    if category not in "LNM":
        continue
    if ranges and ranges[-1][1] + 1 == point and ranges[-1][2] == category:
        ranges[-1][1] = point
    else:
        ranges.append([point, point, category])
print(
    json.dumps(
        {
            "unicode_category_version": unicodedata.unidata_version,
            "generator": "CPython 3.13 unicodedata.category; L/N/M inclusive ranges",
            "ranges": ranges,
        },
        separators=(",", ":"),
    )
)
