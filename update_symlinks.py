import pathlib

path = pathlib.Path(".").absolute()

for p in path.iterdir():
    if not p.is_dir():
        continue
    if p.stem == "uploads":
        continue
    for f in p.iterdir():
        print(f)
        if not f.is_symlink():
            continue

        relative = f.resolve(strict=False).name
        f.unlink()
        f.symlink_to(relative)
