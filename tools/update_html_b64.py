import os

b64 = open(r'd:\cloud CLI\cloud_run_service\default_board_b64.txt').read().strip()
data_url = 'data:image/png;base64,' + b64

html_path = r'd:\cloud CLI\cloud_run_service\test.html'
with open(html_path, 'r', encoding='utf-8') as f:
    content = f.read()

lines = content.splitlines()
new_lines = []
for l in lines:
    if l.startswith('const DEFAULT_BOARD_PNG ='):
        new_lines.append(f'const DEFAULT_BOARD_PNG = "{data_url}";')
    else:
        new_lines.append(l)

new_content = '\n'.join(new_lines)

with open(html_path, 'w', encoding='utf-8') as f:
    f.write(new_content)

with open(r'd:\cloud CLI\tools\debug_console.html', 'w', encoding='utf-8') as f:
    f.write(new_content)

print(f"Successfully updated HTML files with {len(b64)} chars base64 Board Buddy image!")
