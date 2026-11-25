"""Verify the Vue 3 project delivery against its unpacked build and page structure."""
import argparse
import json
from pathlib import Path
from zipfile import ZipFile


def require(condition, description):
    if not condition:
        raise ValueError(description)
    print('PASS', description)


def verify(root):
    package = json.loads((root / 'package.json').read_text())
    require(package['name'] == 'aisol-env-booking-web', 'Web delivery name')
    require(package['dependencies']['vue'].lstrip('~^').startswith('3.')
            and 'vite' in package['devDependencies']
            and 'ant-design-vue' in package['dependencies'], 'Vue 3, Vite and Ant Design Vue')
    for resource in ('bookings', 'maintenance', 'waitlist'):
        view = (root / 'src/views' / resource / 'index.vue').read_text()
        require('<script setup' not in view and 'export default' in view, resource + ' Options API page')
        require((root / 'src/router/routes' / (resource + '.js')).is_file(), resource + ' route module')
        require((root / 'src/api' / resource / 'index.js').is_file(), resource + ' request module')
    dist = root / 'dist'
    files = {p.relative_to(dist).as_posix() for p in dist.rglob('*') if p.is_file()}
    require('index.html' in files, 'dist/index.html')
    with ZipFile(root / 'AISOL_EnvBookingWeb.zip') as archive:
        names = [item.filename for item in archive.infolist() if not item.is_dir()]
        require(len(names) == len(files) and set(names) == files, 'ZIP file list matches dist')
        for name in names:
            if archive.read(name) != (dist / name).read_bytes():
                raise ValueError('ZIP content mismatch ' + name)
        print('PASS ZIP contents match dist for', len(names), 'files')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('web', type=Path)
    verify(parser.parse_args().web)
