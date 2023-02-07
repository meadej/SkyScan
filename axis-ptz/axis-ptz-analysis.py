import re
import sys

# Usage: python3 axis-ptz-analysis.py [camera docker container log file]
# Regexes to search files for recorded Pan and Tilt Values
regex_a = r"Camera Position, A - Pan ([-]?[0-9]+\.[0-9]+) Tilt ([0-9]+\.[0-9]+)"
regex_b = r"Camera Position, B - Pan ([-]?[0-9]+\.[0-9]+) Tilt ([0-9]+\.[0-9]+)"

a_pans = []
a_tilts = []
b_pans = []
b_tilts = []

# Search for and collect all algorithm a and b pan and tilt logs
with open(str(sys.argv[1]), 'r') as fh:
    for line in fh.readlines():
        search_a = re.search(regex_a, line)
        search_b = re.search(regex_b, line)

        if search_a is not None:
            a_pans.append(float(search_a.group(1)))
            a_tilts.append(float(search_a.group(2)))

        if search_b is not None:
            b_pans.append(float(search_b.group(1)))
            b_tilts.append(float(search_b.group(2)))

# Calculate the differences internally between n and n+1 for a pans and b pans
diffs_a_pan = [abs(j - i) for i, j in zip(a_pans[:-1], a_pans[1:])]
diffs_b_pan = [abs(j - i) for i, j in zip(b_pans[:-1], b_pans[1:])]

# Calculate the differences internally between n and n+1 for a tilts and b tilts
diffs_a_tilt = [abs(j - i) for i, j in zip(a_tilts[:-1], a_tilts[1:])]
diffs_b_tilt = [abs(j - i) for i, j in zip(b_tilts[:-1], b_tilts[1:])]

# Calculate the differences between the differences (some wacky order differential) for pans and tilts between a and b
a_b_pan_diffs = [abs(a - b) for a, b in zip(diffs_a_pan, diffs_b_pan)]
a_b_tilt_diffs = [abs(a - b) for a, b in zip(diffs_a_tilt, diffs_b_tilt)]

a_b_pan_diffs_avg = sum(a_b_pan_diffs) / len(a_b_pan_diffs)
a_b_pan_diffs_max = max(a_b_pan_diffs)
a_b_pan_diffs_min = min(a_b_pan_diffs)

a_b_tilt_diffs_avg = sum(a_b_tilt_diffs) / len(a_b_tilt_diffs)
a_b_tilt_diffs_max = max(a_b_tilt_diffs)
a_b_tilt_diffs_min = min(a_b_tilt_diffs)

print("Pan differences between A and B AVG: ", a_b_pan_diffs_avg)
print("Pan differences between A and B MAX: ", a_b_pan_diffs_max)
print("Pan differences between A and B MIN: ", a_b_pan_diffs_min)

print("Tilt differences between A and B AVG: ", a_b_tilt_diffs_avg)
print("Tilt differences between A and B MAX: ", a_b_tilt_diffs_max)
print("Tilt differences between A and B MIN: ", a_b_tilt_diffs_min)