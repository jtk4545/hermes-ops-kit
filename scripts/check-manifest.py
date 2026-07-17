#!/usr/bin/env python3
import sys
import json

manifest = sys.argv[1] + "/manifest.json"
with open(manifest) as f:
    data = json.load(f)
print(data["agents"][0])
