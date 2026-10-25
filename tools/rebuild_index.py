"""市场索引维护脚本：扫描 plugins/*/<id>-<version>.zip，校验 zip 结构并重建 index.json。

给 GitHub Actions（.github/workflows/release.yml）调用，也供维护者本地手动跑：
    python tools/rebuild_index.py

流程：
1. 扫描 plugins/<id>/ 下所有 zip；
2. 每个 zip 校验：能解压、能找到 manifest.json、manifest.id == 目录名；
3. 重算 sha256 / size；
4. 保留 index.json 里已有的元数据（category/author/rating/downloads/min_app...），
   只刷新 version/download/sha256/size 这些「随包变化」的字段；
5. 写出新的 market/index.json。

这样维护者只需要把 zip 丢进对应目录，跑一下（或让 CI 自动跑）索引就对齐了，
不用手算 sha256、手改 JSON。
"""
from __future__ import annotations

import hashlib
import json
import sys
import zipfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
PLUGINS_DIR = REPO_ROOT / "plugins"
INDEX_PATH = REPO_ROOT / "market" / "index.json"

# 这些元数据字段在重建时**保留旧值**，不被「随包变化」的字段覆盖
_PRESERVE_META = ("category", "author", "homepage", "rating", "downloads",
                  "min_app", "tags")


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def read_manifest(zip_path: Path) -> dict:
    """从 zip 里读出 manifest.json 的原始 dict（不解压到磁盘）。"""
    with zipfile.ZipFile(zip_path) as zf:
        names = [n for n in zf.namelist()
                 if n.endswith("manifest.json") and not n.startswith("__MACOSX/")]
        if len(names) != 1:
            raise ValueError(f"zip 内应恰好有一个 manifest.json，实际 {len(names)}")
        raw = json.loads(zf.read(names[0]).decode("utf-8-sig"))
        return raw


def load_old_index() -> list[dict]:
    if not INDEX_PATH.exists():
        return []
    data = json.loads(INDEX_PATH.read_text(encoding="utf-8-sig"))
    plugins = data.get("plugins") if isinstance(data, dict) else data
    return [p for p in plugins if isinstance(p, dict)]


def main() -> int:
    if not PLUGINS_DIR.exists():
        print("plugins/ 目录不存在", file=sys.stderr)
        return 1

    old = {p.get("id"): p for p in load_old_index()}
    entries: list[dict] = []
    errors: list[str] = []

    for d in sorted(PLUGINS_DIR.iterdir()):
        if not d.is_dir() or d.name.startswith("."):
            continue
        zips = sorted(d.glob("*.zip"))
        if not zips:
            errors.append(f"{d.name}: 无 zip")
            continue
        # 取版本号最高的 zip（字符串比较对 semver 多数场景够用）
        zip_path = sorted(zips, key=lambda p: p.name)[-1]
        try:
            manifest = read_manifest(zip_path)
            pid = manifest.get("id")
            if pid != d.name:
                errors.append(f"{d.name}: zip 内 id={pid} 与目录名不一致")
                continue
            entry = {
                "id": pid,
                "name": manifest.get("name", pid),
                "version": manifest.get("version", "0.0.0"),
                "description": manifest.get("description", ""),
                "permissions": manifest.get("permissions", []),
                "download": f"plugins/{d.name}/{zip_path.name}",
                "sha256": sha256_file(zip_path),
                "size": zip_path.stat().st_size,
            }
            # 保留旧索引里的元数据
            prev = old.get(pid, {})
            for k in _PRESERVE_META:
                if prev.get(k) is not None:
                    entry[k] = prev[k]
            entries.append(entry)
        except (ValueError, KeyError, json.JSONDecodeError, zipfile.BadZipFile) as exc:
            errors.append(f"{d.name}: {exc}")

    entries.sort(key=lambda e: e["id"])
    out = {"generated_by": "xwork", "plugins": entries}
    INDEX_PATH.parent.mkdir(parents=True, exist_ok=True)
    INDEX_PATH.write_text(json.dumps(out, ensure_ascii=False, indent=2) + "\n",
                          encoding="utf-8")

    print(f"重建完成：{len(entries)} 个插件")
    for e in errors:
        print(f"  跳过：{e}")
    if errors:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
