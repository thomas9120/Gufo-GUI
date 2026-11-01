"""Do not launch installer descendants until the parent owns our Windows Job."""
import json
import subprocess
import sys

if sys.stdin.readline() == "start\n":
    sys.exit(subprocess.call(json.loads(sys.argv[1]), stdin=subprocess.DEVNULL))
sys.exit(2)
