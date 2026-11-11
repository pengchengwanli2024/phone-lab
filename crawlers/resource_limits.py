"""Observe only the owned route process group; never signal unrelated processes."""
import subprocess

def group_rss_kib(group):
    result=subprocess.run(['ps','-axo','pgid=,rss='],capture_output=True,text=True,timeout=2)
    if result.returncode:raise ValueError('resource_observation_unavailable')
    rows=[line.split() for line in result.stdout.splitlines()]
    return sum(int(row[1]) for row in rows if len(row)==2 and row[0]==str(group))
