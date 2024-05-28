#!/usr/bin/env python3

# inject-1.log

import sys
import json

buglog = []

with open(sys.argv[1], 'r') as fd:
    data = fd.read()
    data = data.split("TESTING -- FUZZED INPUTS")[1].strip()
    records = data.split("============================================================")
    for bug in records:
        if not bug:
            continue
        bug = bug.strip()
        lines = bug.split('\n')
        assert (lines[2].startswith("Bug["))
        bugid = int(lines[2].split(']')[0][4:])
        #print(bugid)
        bugtype = lines[2].split(',')[0].split('=')[-1]
        #print(bugtype)
        loc = lines[2].split("atp=ATP[")[1].split(',')[0].split('=')[1]
        #print(loc)
        valid = (lines[-1] != "RV does not indicate memory corruption")
        #print(valid)
        buglog.append({
            'id': bugid,
            'type': bugtype,
            'loc': loc,
            'valid': valid
            })
with open('out.json', 'w') as fd:
    json.dump(buglog, fd)
