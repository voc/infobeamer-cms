import os

import requests

os.makedirs('36c3')
r = requests.get('http://localhost:8080/content/live?all=1')
for idx, asset in enumerate(r.json()['assets']):
    r = requests.get('http://localhost:8080' + asset['url'], stream=True)
    with open('36c3/asset-%03d-%s.%s' % (idx, asset['user'], {'image': 'jpg', 'video': 'mp4'}[asset['filetype']]), 'wb') as out:
        out.write(r.raw.read())
