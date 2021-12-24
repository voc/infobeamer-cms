import os

import requests

export_dir = 'infobeamer-cms-export'

os.makedirs(export_dir)
r = requests.get('http://localhost:8000/content/live?all=1')
for idx, asset in enumerate(r.json()['assets']):
    r = requests.get('http://localhost:8000' + asset['url'], stream=True)
    with open('{}/asset-{:04d}-{}.{}'.format(export_dir, idx, asset['user'], {'image': 'jpg', 'video': 'mp4'}[asset['filetype']]), 'wb') as out:
        out.write(r.raw.read())
