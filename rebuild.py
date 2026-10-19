import sys
from pathlib import Path
sys.path.insert(0, 'idos-core')
from idos.site.builder import write_site

write_site(Path('.'))
print('Site rebuilt OK')
