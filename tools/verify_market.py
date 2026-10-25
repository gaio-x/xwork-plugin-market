"""市场索引只读校验（CI 用）：包体一致性 + 索引签名。

**本脚本绝不修改任何文件**。CI 只做校验，索引的权威版本必须由签名机在本地
生成并签名后推送 —— 为什么不让 CI 重建：CI 没有私钥，它一旦改写 index.json，
签名立刻失效，全客户端都会拒用该索引（2026-10-25 启用签名时的设计决定）。

校验三件事：
1. `market/index.json` 里每个插件的 `size` / `sha256` 与 `plugins/<id>/*.zip` 实际一致；
2. `market/index.json.sig` 存在，且 `pubkey` 在受信公钥列表内；
3. 用该公钥对 `index.json` 的字节验签通过。

任一不满足 → 退出码 1，CI 红灯。

用法：
    python tools/verify_market.py
"""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
INDEX = ROOT / "market" / "index.json"
SIG = ROOT / "market" / "index.json.sig"

# 受信发布者公钥（与客户端 core/plugin/signature.py 的 TRUSTED_PUBKEYS 保持一致）。
# 公钥是公开信息，硬编码在仓库里没有风险；私钥只在签名机本地（data/_market_keys/）。
TRUSTED_PUBKEYS = [
    "23c15b347e6c89829047135cafea97e5112b949a9ddd26d71a3010e2d170e373",
]

# ---------------------------------------------------------------- Ed25519 验签
# 纯 Python 实现（RFC 8032），与客户端同一套算法；不依赖 cryptography，CI 无需装包。
_P = 2**255 - 19
_L = 2**252 + 27742317777372353535851937790883648493
_D = -121665 * pow(121666, _P - 2, _P) % _P
_I = pow(2, (_P - 1) // 4, _P)
_B = (15112221349535400772501151409588531511454012693041857206046113283949847762202,
      46316835694926478169428394003475163141307993866256225615783033603165251855960)


def _modinv(a: int, m: int) -> int:
    return pow(a, m - 2, m)


def _point_add(P, Q):
    (x1, y1), (x2, y2) = P, Q
    a = (x1 * y2 + x2 * y1) % _P
    b = (1 + _D * x1 * x2 * y1 * y2) % _P
    return ((a * _modinv(b, _P)) % _P,
            ((y1 * y2 + x1 * x2) * _modinv((1 - _D * x1 * x2 * y1 * y2) % _P, _P)) % _P)


def _point_mul(n: int, P=_B):
    R = (0, 1)
    Q = P
    while n > 0:
        if n & 1:
            R = _point_add(R, Q)
        Q = _point_add(Q, Q)
        n >>= 1
    return R


def _recover_x(y: int, sign: int) -> int:
    y2 = (y * y) % _P
    u = (y2 - 1) % _P
    v = (_D * y2 + 1) % _P
    xx = (u * _modinv(v, _P)) % _P
    x = pow(xx, (_P + 3) // 8, _P)
    if (x * x - xx) % _P != 0:
        x = (x * _I) % _P
    if (x * x - xx) % _P != 0:
        raise ValueError("不是曲线上的点")
    if (x & 1) != sign:
        x = _P - x
    return x


def _hash_int(data: bytes) -> int:
    return int.from_bytes(hashlib.sha512(data).digest(), "little")


def verify(message: bytes, sig_hex: str, pub_hex: str) -> bool:
    try:
        sig = bytes.fromhex(sig_hex.strip())
        pub = bytes.fromhex(pub_hex.strip())
    except ValueError:
        return False
    if len(sig) != 64 or len(pub) != 32:
        return False
    Renc, S = sig[:32], int.from_bytes(sig[32:], "little")
    if S >= _L:
        return False
    y = int.from_bytes(pub, "little") & ((1 << 255) - 1)
    x = _recover_x(y, (pub[31] >> 7) & 1)
    A = (x, y % _P)
    Ry = int.from_bytes(Renc, "little") & ((1 << 255) - 1)
    R = (_recover_x(Ry, (Renc[31] >> 7) & 1), Ry)
    k = _hash_int(Renc + pub + message) % _L
    return _point_mul(S) == _point_add(R, _point_mul(k, A))


# ---------------------------------------------------------------- 校验主流程
def main() -> int:
    fails: list[str] = []
    if not INDEX.exists():
        print(f"✗ 缺少 {INDEX.relative_to(ROOT)}")
        return 1
    raw = INDEX.read_bytes()
    if b"\r\n" in raw:
        fails.append("index.json 含 CRLF（签名按字节计算，行尾转换会让所有客户端验签失败）")
    try:
        data = json.loads(raw.decode("utf-8-sig"))
    except json.JSONDecodeError as exc:
        print(f"✗ index.json 不是合法 JSON：{exc}")
        return 1
    plugins = data.get("plugins") if isinstance(data, dict) else data
    if not isinstance(plugins, list):
        print("✗ index.json 结构应为 { plugins: [...] }")
        return 1

    # 1) 包体一致性
    for it in plugins:
        pid = it.get("id") or "<无 id>"
        rel = it.get("download") or ""
        if not rel:
            fails.append(f"{pid}: 缺少 download")
            continue
        f = ROOT / rel
        if not f.exists():
            fails.append(f"{pid}: 找不到包体 {rel}")
            continue
        blob = f.read_bytes()
        sha = hashlib.sha256(blob).hexdigest()
        if sha != str(it.get("sha256", "")).lower():
            fails.append(f"{pid}: sha256 与索引不符（索引 {str(it.get('sha256'))[:12]}… 实际 {sha[:12]}…）")
        if "size" in it and int(it["size"]) != len(blob):
            fails.append(f"{pid}: size 与索引不符（索引 {it['size']} 实际 {len(blob)}）")

    # 2) 签名
    if not SIG.exists():
        fails.append("缺少 market/index.json.sig（改动索引后必须重新签名，CI 不会代签）")
    else:
        try:
            meta = json.loads(SIG.read_text(encoding="utf-8-sig"))
        except json.JSONDecodeError as exc:
            fails.append(f"index.json.sig 不是合法 JSON：{exc}")
            meta = {}
        pub = (meta or {}).get("pubkey", "")
        sig = (meta or {}).get("sig", "")
        if pub not in TRUSTED_PUBKEYS:
            fails.append(f"签名公钥不在受信列表内：{pub[:16]}…")
        elif not verify(raw, sig, pub):
            fails.append("索引验签失败（index.json 与 .sig 不匹配，可能改了索引但没重新签名）")

    if fails:
        print(f"✗ 校验失败（{len(fails)} 项）：")
        for f in fails:
            print(f"  - {f}")
        print("\n修复：本地跑 python tools/rebuild_index.py 后重新签名，再推送。")
        return 1
    print(f"✓ 校验通过：{len(plugins)} 个插件，包体一致，索引签名有效")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
