# get_version.py
import json
import os

with open('version.json', 'r', encoding='utf-8') as f:
    data = json.load(f)

version = data['version']
# Объединяем changelog с переносами строк \n и префиксом "- "
changelog = '- ' + '\n- '.join(data['changelog'])

# Для записи в $GITHUB_OUTPUT используем многострочный синтаксис
with open(os.environ['GITHUB_OUTPUT'], 'a', encoding='utf-8') as f:
    f.write(f'VERSION={version}\n')
    f.write('CHANGELOG<<EOF\n')
    f.write(changelog + '\n')
    f.write('EOF\n')