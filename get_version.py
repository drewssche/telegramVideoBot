# get_version.py
import json
import os

with open('version.json', 'r', encoding='utf-8') as f:
    data = json.load(f)

version = data['version']
changelog = '- ' + '\n- '.join(data['changelog'])

print(f"Extracted version: {version}")
print(f"Changelog:\n{changelog}")

with open(os.environ['GITHUB_OUTPUT'], 'a', encoding='utf-8') as f:
    f.write(f'VERSION={version}\n')
    f.write('CHANGELOG<<EOF\n')
    f.write(changelog + '\n')
    f.write('EOF\n')