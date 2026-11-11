"""Fixed worker entry with per-process CPU, file and descriptor hard limits."""
import resource
import runpy
import sys
from pathlib import Path

for resource_id,limit in [(resource.RLIMIT_CPU,120),(resource.RLIMIT_FSIZE,8*1024*1024),(resource.RLIMIT_NOFILE,1024)]:
    soft,hard=resource.getrlimit(resource_id)
    bounded=limit if hard==resource.RLIM_INFINITY else min(limit,hard)
    resource.setrlimit(resource_id,(bounded,bounded))
article=len(sys.argv)>1 and sys.argv[1]=='--article'
if article:del sys.argv[1]
runpy.run_path(str(Path(__file__).with_name('article.py' if article else 'worker.py')),run_name='__main__')
