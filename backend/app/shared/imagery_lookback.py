"""How far back a "latest reading" query looks before it reads all history.

Several reads ask for the newest grid reading per cell or per index. On a
compressed hypertable they must read every row they are given before
they can name the newest, so their cost grows with the farm's history.
They read this many days first, and the whole history only when the
window holds nothing.

180 days is about 36 Sentinel-2 passes and 11 Landsat passes. A cell or
index with no reading in that window is not current for any decision the
engine makes.
"""

LATEST_LOOKBACK_DAYS = 180
