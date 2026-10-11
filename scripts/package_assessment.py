"""Package only the public static client; never publish a repository directory."""
import argparse
from pathlib import Path
import shutil

ROOT = Path(__file__).resolve().parents[1]
PUBLIC_FILES = ('index.html', 'style.css', 'app.mjs', 'core.mjs', 'definition.json')


def main():
    parser = argparse.ArgumentParser(description='打包公共自检页面（仅白名单文件）')
    parser.add_argument('--output', type=Path, default=ROOT / '_site')
    args = parser.parse_args()
    source = ROOT / 'assessment'
    for name in PUBLIC_FILES:
        path = source / name
        if not path.is_file() or path.is_symlink():
            parser.error(f'缺少公共资源或不允许符号链接：{name}')
    try:
        args.output.mkdir(parents=True, exist_ok=False)
    except OSError as error:
        parser.error(f'需要新目录，避免混入旧文件：{error}')
    for name in PUBLIC_FILES:
        shutil.copyfile(source / name, args.output / name)
    (args.output / '.nojekyll').write_text('', encoding='utf-8')
    print(f'Packaged {len(PUBLIC_FILES)} public assets into {args.output}')


if __name__ == '__main__':
    main()
