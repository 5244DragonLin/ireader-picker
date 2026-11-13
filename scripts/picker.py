#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""掌阅选书助手：查余额 / 找能零付买下的书 / 按热度或分类推荐 / 按类型检索 / 下单购买。

设计要点
--------
* 查询类只读：`balance` / `coupons` / `afford` / `recommend` / `category` /
  `search` / `info` / `shelves` 绝不动账号。
* 写操作有两类，都要显式确认：
  `buy` 扣券购买（必须 `--confirm`，否则只询价）；
  `shelf` 加书架、`move` 移书、`mkdir` / `rmdir` 建删文件夹（均有 `--dry` 预览）。
* 查价不需要登录：book.php / 分类页 / 搜索都匿名可用；
  只有「余额、代金券/满减券明细、是否已拥有、下单」需要 usr + zysid。
* 代金券与满减券是两套：代金券 1:1 抵阅饼、自动扣；满减券「满 X 减 Y」，
  只在 App 订单页手动选择，H5 下单页（Order.Create）不参与试算。
* 按热度推荐很快：分类页支持 order=download（热门）/ score（好评），
  热门书永远排在前面，所以只抓每类前几页即可，无需全量扫描。

凭证获取优先级：--auth 参数 > 环境变量 > config.json（技能根目录或 scripts/ 同目录）
没有凭证时可直接密码登录生成：python picker.py login <手机号>（需 pip install cryptography）

用法速查
--------
    python picker.py login 13800000000            # 手机号+密码登录（密码隐藏输入）
    python picker.py login 13800000000 --password XXX   # 密码随命令（写自动化脚本用）
    python picker.py balance                      # 阅饼 + 代金券（含到期日）
    python picker.py coupons                      # 满减券（满 X 减 Y，含门槛与有效期）
    python picker.py afford --limit 100           # 能零付买下的书（≤ 可用券额）
    python picker.py afford --full --limit 300    # 穷举全书城（慢，约 10 分钟）
    python picker.py recommend --limit 100        # 按热门程度推荐能买的书
    python picker.py recommend --sort score       # 按好评推荐
    python picker.py category 计算机               # 按分类推荐
    python picker.py search 聊斋                   # 按书名检索
    python picker.py search 推理 --genre           # 按类型/题材检索
    python picker.py info 10007034                # 单本详情（价/是否已有/能否抵扣）
    python picker.py buy 10007034                 # ⚠️ 下单：默认只询价
    python picker.py buy 10007034 --confirm       # ⚠️ 真正扣券购买（买后自动加书架）
    python picker.py buy 10007034 --confirm --folder 外国经典文学   # 买完直接归夹
    python picker.py shelf 10007034               # 把已购书补进云书架
    python picker.py shelves                     # 书架结构：文件夹 + 各夹书数（只读）
    python picker.py shelves --folder 科幻 --books  # 看某个文件夹里的书
    python picker.py move 10007034 --to 科幻      # ⚠️ 把书移到文件夹（--dry 预览）
    python picker.py move 10007034                # --to 留空 = 移出到未归类
    python picker.py mkdir 新夹                   # ⚠️ 新建文件夹
    python picker.py rmdir 新夹 --force           # ⚠️ 删文件夹（先把书移出，不丢书）
"""
from __future__ import annotations

import argparse
import concurrent.futures as cf
import gzip
import html as _html
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid

# Windows 控制台中文输出
try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except (AttributeError, ValueError):
    pass

APP_BASE = "https://ah2.zhangyue.com"
M_BASE = "https://m.zhangyue.com"
PC_BASE = "https://api-pc.zhangyue.com/bookstore/open"
CAT_BASE = "https://ireader.com.cn/index.php"
DOUBAN_BASE = "https://book.douban.com"

APP_UA = ("Mozilla/5.0 (Linux; Android 11; M2012K11AC) AppleWebKit/537.36 "
          "(KHTML, like Gecko) Chrome/91.0.4472.114 Mobile Safari/537.36 iReader/8.7.4")
PC_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
         "(KHTML, like Gecko) Chrome/126.0 Safari/537.36")
PC_PAGE_PARAMS = "p29=zye5b814&p2=104583&p3=18070403&p4=501603&p33=com.chaozh.iReaderFree"

# 频道 / 筛选 / 排序的语义（实测确认）
CHANNELS = {"10": "男频", "68": "女频", "92": "出版"}
STATUS = {"0": "全部", "1": "免费", "2": "特价", "3": "完结", "4": "VIP"}
ORDERS = {"download": "热门", "score": "好评", "update": "最新"}

# 分类名 → (频道, cid)。由脚本自动抓取，这里只留常用别名便于直接 -c 指定
CATEGORY_ALIAS = {
    "小说": ("92", "93"), "文学": ("92", "113"), "历史": ("92", "142"),
    "传记": ("92", "127"), "社科": ("92", "179"), "心理": ("92", "168"),
    "经济": ("92", "212"), "管理": ("92", "448"), "理财": ("92", "232"),
    "科普": ("92", "453"), "医学": ("92", "336"), "计算机": ("92", "320"),
    "哲学": ("92", "181"), "军事": ("92", "653"), "艺术": ("92", "156"),
    "国学": ("92", "119"), "少儿": ("92", "296"), "外语": ("92", "351"),
    "玄幻": ("10", "11"), "都市": ("10", "27"), "科幻": ("10", "60"),
    "武侠": ("10", "19"), "仙侠": ("10", "22"),
    "现代言情": ("68", "69"), "古代言情": ("68", "74"),
    "青春校园": ("68", "86"), "推理悬疑": ("68", "90"),
}


# ---------------------------------------------------------------- 基础 HTTP

def _fetch(url: str, ua: str, referer: str = "", tries: int = 3,
           timeout: int = 20) -> str:
    """GET 并解压，失败重试；最终失败返回空串。"""
    req = urllib.request.Request(
        urllib.parse.quote(url, safe=":/?&=%"),
        headers={"User-Agent": ua, "Accept": "*/*",
                 "Accept-Encoding": "gzip, deflate",
                 "Referer": referer or "https://ireader.com.cn/"},
    )
    for i in range(tries):
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                body = r.read()
                if "gzip" in r.headers.get("Content-Encoding", ""):
                    try:
                        body = gzip.decompress(body)
                    except OSError:
                        pass
                return body.decode("utf-8", "ignore")
        except Exception:
            time.sleep(0.6 * (i + 1))
    return ""


def _text(html: str) -> str:
    s = re.sub(r"<script.*?</script>|<style.*?</style>", " ", html, flags=re.S)
    s = re.sub(r"<[^>]+>", " ", s)
    return re.sub(r"\s+", " ", s)


def _clean(frag: str) -> str:
    """片段去标签 + 反转义 + 折叠空白。"""
    if not frag:
        return ""
    s = re.sub(r"<[^>]+>", " ", frag)
    return re.sub(r"\s+", " ", _html.unescape(s)).strip()


# ---------------------------------------------------------------- 豆瓣读书

DOUBAN_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
             "(KHTML, like Gecko) Chrome/126.0 Safari/537.36")

# 豆瓣正常图书页 ≥10 万字节；显著小于此值即为反爬壳页，别当正文解析
DOUBAN_MIN_PAGE = 20000


def douban_get(url: str, tries: int = 2, timeout: int = 20) -> tuple[int, str, str]:
    """GET 豆瓣页面，返回 (状态码, 最终URL, HTML)。

    豆瓣对 UA 敏感（无 UA 会被拦），且会 302 跳到 subject 页，
    所以要跟随跳转并回传最终 URL。gzip 需手动解压。

    ⚠️ 豆瓣按 IP 限流：持续抓取后会返回 403/429，或 200 但只有几 KB 的反爬壳页
    （实测冷却 5 分钟以上仍未恢复）。因此 403/429 不重试，直接上报。
    """
    req = urllib.request.Request(
        url, headers={"User-Agent": DOUBAN_UA, "Accept": "text/html,*/*",
                      "Accept-Language": "zh-CN,zh;q=0.9",
                      "Accept-Encoding": "gzip"})
    for i in range(tries):
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                body = r.read()
                if "gzip" in r.headers.get("Content-Encoding", ""):
                    try:
                        body = gzip.decompress(body)
                    except OSError:
                        pass
                return r.status, r.url, body.decode("utf-8", "ignore")
        except urllib.error.HTTPError as e:
            if e.code == 404:          # ISBN 在豆瓣无对应书，重试没意义
                return 404, url, ""
            if e.code in (403, 429):   # 触发限流，重试只会加重，直接上报
                return e.code, url, ""
            if i == tries - 1:
                return e.code, url, ""
        except Exception:
            if i == tries - 1:
                return 0, url, ""
        time.sleep(0.8 * (i + 1))
    return 0, url, ""


def _title_similar(a: str, b: str) -> bool:
    """粗判两个书名是否指向同一本书（去标点、去卷册后缀后比对）。

    ISBN 会对应豆瓣上不同卷册（《平凡的世界》各部共用一个 ISBN），
    所以名字差太多时要提醒用户评分可能不是这一版的。
    """
    def key(s):
        s = re.sub(r"[（(][^）)]*[）)]", "", s or "")          # 去括号副标题
        s = re.sub(r"第[一二三四五六七八九十\d]+[部卷册集]", "", s)  # 去卷册
        return re.sub(r"[\s\-—–_·・:：,，.。、!！?？'\"“”‘’&/]+", "", s).lower()
    ka, kb = key(a), key(b)
    if not ka or not kb:
        return True                      # 无从判断，不误报
    return ka in kb or kb in ka          # 一方包含另一方即视为同书


def douban_by_isbn(isbn: str, local_title: str = "") -> dict:
    """按 ISBN 查豆瓣评分。返回 {ok, rating, rating_count, url, title, ...}。

    只取评分与评价人数，不取豆瓣内容简介——评分与简介在同一张 subject 页里，
    少解析一份正文不影响请求数，但输出更干净。

    请求链路：`book.douban.com/isbn/<isbn>/` 会 302 跳到 `subject/<id>/`，
    客户端因此**实际发出 2 次 HTTP 请求**（跳转 + 落地页），
    这也是限流来得比预期快的原因之一。

    评价人数不足时 `v:average` 标签存在但内容为空，此时 rating 为 None。
    传 local_title 时会与豆瓣书名比对，不同名则附提醒（ISBN 可能跨卷册）。
    """
    out = {"ok": False, "rating": None, "rating_count": None,
           "url": "", "title": "", "note": "",
           "title_match": True, "limited": False}
    isbn = re.sub(r"[^0-9Xx]", "", isbn or "")
    if not isbn:
        out["note"] = "无 ISBN"
        return out
    status, url, h = douban_get(f"{DOUBAN_BASE}/isbn/{isbn}/")
    out["url"] = url
    # 限流：403/429，或 200 但只有反爬壳页（正常页 ≥10 万字节）
    if status in (403, 429) or (status == 200 and 0 < len(h) < DOUBAN_MIN_PAGE):
        out["limited"] = True
        out["note"] = "豆瓣触发限流（403/429），请隔一段时间再试"
        return out
    if status == 404:
        out["note"] = "豆瓣未收录该 ISBN"
        return out
    if not h:
        out["note"] = "豆瓣请求失败"
        return out
    if "sec.douban.com" in h or "异常请求" in h:
        out["limited"] = True
        out["note"] = "被豆瓣反爬拦截，稍后再试"
        return out
    m = re.search(r'property="v:average">\s*([0-9.]+)\s*<', h)
    if m:
        out["rating"] = float(m.group(1))
    m = re.search(r'property="v:votes">\s*(\d+)\s*<', h)
    if m:
        out["rating_count"] = int(m.group(1))
    m = re.search(r"<title>(.*?)</title>", h, re.S)
    if m:
        out["title"] = m.group(1).replace("(豆瓣)", "").replace(" (豆瓣)", "").strip()
    if local_title and out["title"]:
        out["title_match"] = _title_similar(local_title, out["title"])
        if not out["title_match"]:
            out["note"] = f"豆瓣同名书为《{out['title'][:24]}》，评分可能不是这一版"
    if out["rating"] is None and "评价人数不足" in h:
        out["note"] = out["note"] or "豆瓣评价人数不足，暂无评分"
        out["ok"] = True                 # 页面有效，只是没分数
        return out
    out["ok"] = out["rating"] is not None
    if not out["ok"]:
        out["note"] = out["note"] or "页面无评分信息"
    return out


def douban_many(isbns: dict[str, str], workers: int = 4,
                delay: float = 0.5, titles: dict[str, str] | None = None
                ) -> dict[str, dict]:
    """并发查多个 ISBN → 豆瓣评分。isbns = {book_id: isbn}。

    豆瓣比掌阅脆弱得多（实测会按 IP 封 403/429 且 5 分钟不恢复），
    所以并发压到 4、每请求间隔 0.5s。一旦发现限流就停止后续请求，
    避免把整个 IP 拖进更长封禁。
    """
    pairs = [(bid, i) for bid, i in isbns.items() if i]
    if not pairs:
        return {}
    titles = titles or {}

    def one(item) -> tuple[str, dict]:
        bid, isbn = item
        time.sleep(delay)                # 限速，保护豆瓣
        return bid, douban_by_isbn(isbn, titles.get(bid, ""))

    out: dict[str, dict] = {}
    with cf.ThreadPoolExecutor(min(workers, 4)) as ex:
        for bid, r in ex.map(one, pairs):
            out[bid] = r
            if r.get("limited"):
                break                    # 已限流，别再发了
    return out


def _post(url: str, data: bytes, ctype: str, ua: str, tries: int = 3,
          timeout: int = 30) -> str:
    """POST（写操作，如加书架）。失败重试，最终返回错误 JSON 串。"""
    req = urllib.request.Request(
        urllib.parse.quote(url, safe=":/?&=%"),
        data=data,
        headers={"User-Agent": ua, "Accept": "application/json",
                 "Content-Type": ctype, "Accept-Encoding": "gzip"},
    )
    last = None
    for _ in range(tries):
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                body = r.read()
                if "gzip" in r.headers.get("Content-Encoding", ""):
                    try:
                        body = gzip.decompress(body)
                    except OSError:
                        pass
                return body.decode("utf-8", "ignore")
        except Exception as e:  # noqa: BLE001
            last = e
    return json.dumps({"_err": str(last)[:150]})


# ---------------------------------------------------------------- 凭证

def load_auth(cli_auth: str | None) -> str:
    """按优先级解析 usr&zysid：参数 > 环境变量 > config.json。

    config.json 支持放在两处（先找技能根目录，再找 scripts/ 同级）：
      <skill>/config.json
      <skill>/scripts/config.json
    """
    if cli_auth:
        return cli_auth.strip().lstrip("&?")
    u, z = os.environ.get("IREADER_USR"), os.environ.get("IREADER_ZYSID")
    if u and z:
        return f"usr={u}&zysid={z}"
    here = os.path.dirname(os.path.abspath(__file__))
    for cfg in (os.path.join(os.path.dirname(here), "config.json"),
                os.path.join(here, "config.json")):
        if not os.path.exists(cfg):
            continue
        try:
            d = json.load(open(cfg, encoding="utf-8"))
            if d.get("usr") and d.get("zysid"):
                return f"usr={d['usr']}&zysid={d['zysid']}"
        except (OSError, ValueError):
            pass
    return ""


def need_auth(auth: str) -> str:
    if auth:
        return auth
    print("⚠️  该操作需要登录凭证（usr + zysid）。\n"
          "   任选一种方式提供：\n"
          "     1) 密码登录（推荐，会自动写入 config.json）：\n"
          "        python picker.py login <手机号>\n"
          "     2) 环境变量：set IREADER_USR=xxx  &  set IREADER_ZYSID=yyy\n"
          "     3) 命令行：  --auth \"usr=i123456&zysid=abcdef...\"\n"
          "     4) 同目录 config.json：{\"usr\": \"i123456\", \"zysid\": \"abcdef...\"}\n"
          "   凭证不要提交到任何仓库（config.json 已在 .gitignore）。",
          file=sys.stderr)
    sys.exit(2)


# ---------------------------------------------------------------- 密码登录

_LOGIN_UC = "https://uc.ireader.com"
_LOGIN_VER, _LOGIN_CHANNEL, _LOGIN_VERCODE = "1.0", "100", "80740"

# 硬编码在掌阅客户端 dex 里的登录加密公钥（RSA 公钥还原服务端下发的 AES 密钥用）
_LOGIN_PUB = (
    "MIGfMA0GCSqGSIb3DQEBAQUAA4GNADCBiQKBgQCAqSnnZ9BVOZjIMTkATIn29nM0hLOsQsXlPbqr"
    "GE4CUmDCncVBHdkfEIF73tSKjhYfLuPH1gDtHRKeCC1DQ4uYJL83oeHtXSldGUlfuv9rh0Q/2Hx"
    "l3iG8TUc1drTKTZFfkQWWseTb3vAx8Ggse9xZNTjI6enOEjNyGlAIF+RKrwIDAQAB"
)


def _login_crypto_available() -> bool:
    try:
        import cryptography  # noqa: F401
        return True
    except ImportError:
        return False


def _load_login_keys() -> list:
    """读取客户端内置 RSA 私钥列表（scripts/native_keys.json）。

    登录参数串必须用客户端私有密钥签名，服务端只认第 4 把（下标 3），
    用其余私钥会返回 [null, 6]。
    """
    import base64
    from cryptography.hazmat.primitives.serialization import load_der_private_key
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                        "native_keys.json")
    with open(path, "r", encoding="utf-8") as f:
        raw = json.load(f)
    return [load_der_private_key(base64.b64decode(x["der_b64"]), password=None)
            for x in raw]


def _login_params_and_sign(priv, params: dict) -> dict:
    """补 timestamp 并用私钥做 SHA1WithRSA 签名（按 key 字典序拼串）。"""
    import base64
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.asymmetric import padding
    p = {k: v for k, v in params.items() if k != "sign"}
    p["timestamp"] = str(int(time.time() * 1000))
    msg = "&".join(f"{k}={p[k]}" for k in sorted(p) if p[k] not in (None, ""))
    p["sign"] = base64.b64encode(
        priv.sign(msg.encode(), padding.PKCS1v15(), hashes.SHA1())).decode()
    return p


def password_login(phone: str, password: str) -> dict:
    """手机号 + 密码登录掌阅（走 App 的 uc.ireader.com 接口）。

    链路：业务体 AES 加密 → AES 密钥再 RSA 公钥加密成 data 字段 →
    参数串用客户端私钥签名 POST → 返回 token 用「公钥解密」还原 AES 密钥 →
    解出 session_id（即 zysid）。

    返回 {"usr", "zysid", "nick"}；失败抛 RuntimeError。
    """
    if not _login_crypto_available():
        raise RuntimeError(
            "密码登录需要 cryptography 库：python -m pip install cryptography")
    if not os.path.exists(os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                       "native_keys.json")):
        raise RuntimeError("缺少 scripts/native_keys.json（客户端签名私钥）")

    import base64
    from cryptography.hazmat.primitives.asymmetric import padding as apadding
    from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
    from cryptography.hazmat.primitives.serialization import load_der_public_key

    def rsa_encrypt(b64_pub: str, plain: str) -> str:
        pub = load_der_public_key(base64.b64decode(b64_pub))
        return base64.b64encode(pub.encrypt(plain.encode(), apadding.PKCS1v15())).decode()

    def rsa_public_decrypt(b64_cipher: str) -> bytes:
        """c^e mod n：服务端用私钥加密下发 token，客户端只能用公钥还原。"""
        pub = load_der_public_key(base64.b64decode(_LOGIN_PUB))
        nums = pub.public_numbers()
        c = int.from_bytes(base64.b64decode(b64_cipher), "big")
        raw = pow(c, nums.e, nums.n).to_bytes((nums.n.bit_length() + 7) // 8, "big")
        if raw[:2] == b"\x00\x01":  # PKCS#1 v1.5 type 1 填充
            return raw[raw.find(b"\x00", 2) + 1:]
        return raw

    def aes_encrypt(key_b64: str, plain: str) -> str:
        key = base64.b64decode(key_b64)
        data = plain.encode()
        pad = 16 - len(data) % 16
        enc = Cipher(algorithms.AES(key), modes.CBC(key)).encryptor()
        return base64.b64encode(enc.update(data + bytes([pad]) * pad)
                                + enc.finalize()).decode()

    def aes_decrypt(key: bytes, b64_data: str) -> str:
        dec = Cipher(algorithms.AES(key), modes.CBC(key)).decryptor()
        pt = dec.update(base64.b64decode(b64_data)) + dec.finalize()
        return pt[:-pt[-1]].decode("utf-8")

    aes_key = base64.b64encode(os.urandom(16)).decode()
    inner = json.dumps({"password": password, "user_name": phone},
                       ensure_ascii=False, separators=(",", ":"))
    data_blob = json.dumps({"AesKey": rsa_encrypt(_LOGIN_PUB, aes_key),
                            "Data": aes_encrypt(aes_key, inner)},
                           ensure_ascii=False, separators=(",", ":"))
    params = {
        "data": data_blob,
        "imei": "86" + str(int(time.time() * 1000))[-13:],
        "ver": _LOGIN_VER,
        "channel_id": _LOGIN_CHANNEL,
        "version_id": _LOGIN_VERCODE,
        "encrypt_method": "1",
        "usr": phone,
    }
    signed = _login_params_and_sign(_load_login_keys()[3], params)
    res_raw = _post(f"{_LOGIN_UC}/user/slogin/passwd/v2",
                    urllib.parse.urlencode(signed).encode(),
                    "application/x-www-form-urlencoded",
                    "Mozilla/5.0 (Linux; Android 12) Mobile iReader/8.7.4")
    try:
        res = json.loads(res_raw)
    except ValueError:
        raise RuntimeError(f"登录响应异常：{res_raw[:200]}")
    if res.get("code") != 0:
        raise RuntimeError(f"登录失败：{res.get('msg') or res}")
    body = res.get("body")
    if isinstance(body, list):
        raise RuntimeError(f"登录被拒（签名私钥不匹配）：{body}")
    token = body["token"]
    aes_raw = base64.b64decode(rsa_public_decrypt(token["AesKey"]))
    sess = json.loads(aes_decrypt(aes_raw, token["Data"]))
    return {"usr": body["name"], "zysid": sess["session_id"],
            "nick": body.get("nick", "")}


def save_credentials(usr: str, zysid: str) -> str:
    """把凭证写入技能根目录 config.json，返回路径。"""
    here = os.path.dirname(os.path.abspath(__file__))
    path = os.path.join(os.path.dirname(here), "config.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump({"usr": usr, "zysid": zysid}, f, ensure_ascii=False, indent=2)
    return path


# ---------------------------------------------------------------- 客户端

class Client:
    def __init__(self, auth: str = "", workers: int = 8, delay: float = 0.15):
        self.auth = auth
        self.workers = workers
        self.delay = delay
        self._shelf: set[str] | None = None

    # ---------- 账户 ----------

    def balance(self) -> dict:
        """阅饼余额（remain_sum）+ 代金券总额（账户页渲染）。"""
        info = _fetch(f"{APP_BASE}/zybook3/u/p/api.php?Act=getUserInfo&{self.auth}",
                      APP_UA)
        try:
            j = json.loads(info)
        except ValueError:
            j = {}
        page = _fetch(f"{APP_BASE}/zybook3/app/app.php?ca=Account.Index&{self.auth}",
                      APP_UA)
        pairs = re.findall(
            r'<p class="t2" data-js="num">([^<]*)</p>\s*<p class="t1"[^>]*>([^<|]*)',
            page)
        notice = re.search(r"您有([^<]*)", page)
        return {
            "read_coin": j.get("remain_sum"),
            "read_coin_yb": j.get("remain_sum_yb"),
            "pairs": [(n.strip(), v.strip()) for v, n in pairs],
            "notice": notice.group(1) if notice else "",
        }

    def vouchers(self) -> list[dict]:
        """代金券明细（含有效期），需要登录。"""
        t = _fetch(f"{APP_BASE}/zyuc/gift/ajaxrequest?index=2&{self.auth}", APP_UA)
        try:
            html = json.loads(t).get("html") or ""
        except ValueError:
            return []
        out = []
        for chunk in re.split(r'(?=<div class="card_useless)', html)[1:]:
            amt = re.search(r'<div class="num">([0-9.]+)</div>', chunk)
            if not amt:
                continue
            nm = re.search(r'<div class="name">(.*?)</div>', chunk, re.S)
            tx = re.search(r'<div class="txt">([^<]*)</div>', chunk)
            name = re.sub(r"<[^>]+>", "", nm.group(1)).strip() if nm else ""
            exp = None
            if tx:
                m = re.search(r"(\d{4}-\d{2}-\d{2})", tx.group(1))
                if m:
                    exp = m.group(1)
            out.append({
                "amount": float(amt.group(1)),
                "source": name.split("|")[-1].strip() if "|" in name else "",
                "expire": exp,
                "used": "card_useless used" in chunk[:60],
            })
        return out

    def coupons(self, kind: str = "book") -> list[dict]:
        """满减券（「优惠券」）明细，需要登录。

        与代金券是两套东西：代金券按面额 1:1 抵阅饼、必须全额覆盖售价；
        满减券是「满 X 减 Y」，达到门槛才可选择使用，且只在部分下单入口生效。
        `kind`：`book` 书籍优惠券（index=1）/ `goods` 实物商品优惠券（index=2）。
        """
        idx = {"book": 1, "goods": 2}.get(kind, 1)
        t = _fetch(f"{APP_BASE}/zyuc/coupon/ajaxrequest?index={idx}&{self.auth}",
                   APP_UA)
        try:
            html = json.loads(t).get("html") or ""
        except ValueError:
            return []
        out = []
        for chunk in re.split(r'(?=<div class="card_use)', html)[1:]:
            amt = re.search(r'<div class="num">([0-9.]+)', chunk)
            if not amt:
                continue
            nm = re.search(r'<div class="name">([^<]+)</div>', chunk)
            per = re.search(r"(\d{4}-\d{2}-\d{2})\s*至\s*(\d{4}-\d{2}-\d{2})", chunk)
            cond = re.search(r"满([0-9.]+)\s*阅饼使用", chunk)
            pid = re.search(r'data-productid="(\d+)"', chunk)
            out.append({
                "amount": float(amt.group(1)),
                "name": _clean(nm.group(1)) if nm else "",
                "threshold": float(cond.group(1)) if cond else 0.0,
                "start": per.group(1) if per else "",
                "end": per.group(2) if per else "",
                "product_id": pid.group(1) if pid else "",
                "expired": "expired" in chunk[:40],
            })
        return out

    def usable_coupons(self, kind: str = "book") -> list[dict]:
        """当前可用的满减券（排除已过期、未到生效日），按门槛升序。"""
        import datetime as dt
        today = dt.date.today()
        out = []
        for v in self.coupons(kind):
            if v["expired"] or not v["end"]:
                continue
            try:
                if dt.date.fromisoformat(v["end"]) < today:
                    continue
                if v["start"] and dt.date.fromisoformat(v["start"]) > today:
                    continue
            except ValueError:
                continue
            v["days_left"] = (dt.date.fromisoformat(v["end"]) - today).days
            out.append(v)
            out.sort(key=lambda v: (v["threshold"], -v["amount"]))
        return out

    def usable_total(self) -> tuple[float, list[dict]]:
        """可用代金券总额 + 明细（排除已用/已过期）。"""
        import datetime as dt
        today = dt.date.today()
        usable = []
        for v in self.vouchers():
            if v["used"] or not v["expire"]:
                continue
            try:
                exp = dt.date.fromisoformat(v["expire"])
            except ValueError:
                continue
            if exp >= today:
                v["days_left"] = (exp - today).days
                usable.append(v)
        usable.sort(key=lambda v: v["expire"])
        return sum(v["amount"] for v in usable), usable

    # ---------- 书架 / 拥有状态 ----------

    def shelf_ids(self) -> set[str]:
        """书架 book_id 集合。注意：书架只收录「主 ID」，同书可能有多 ID 别名。"""
        if self._shelf is not None:
            return self._shelf
        rows, _ = self._shelf_rows()
        self._shelf = {str(r.get("book_id")) for r in rows
                       if str(r.get("book_id", "")).isdigit()}
        return self._shelf

    def is_owned(self, bid: str) -> bool | None:
        """权威拥有判断（下单接口 IsAsset）。详情页不反映拥有状态，别用详情页判断。"""
        t = _fetch(f"{APP_BASE}/zybook3/u/p/order.php?Act=getOrderTmpInfo"
                   f"&bid={bid}&{self.auth}", APP_UA)
        if not t.strip().startswith("{"):
            return None
        try:
            ch = ((json.loads(t).get("Data") or {}).get("Charging")) or {}
        except ValueError:
            return None
        if "IsAsset" not in ch:
            return None
        return ch.get("IsAsset") == 1

    # ---------- 书籍详情 ----------

    def detail(self, bid: str) -> dict:
        """完整书目：书名/作者/译者/出版社/书号/简介/评分/价格等。

        详情页信息分三块：
        * `<dd class="d_author">`  作者、译者（`xxx[译]`）、版权品牌方
        * `<div class="brief_...>` 推荐语（`dt_info`）+ 内容简介（`brief_intro_txt`）
        * `<div class="bookinfo">` 字数、大小、上架时间、出版社、书号
        """
        t = _fetch(f"{APP_BASE}/zybook3/u/p/book.php?key=17B{bid}&{self.auth}", APP_UA)
        out = {"id": str(bid), "price": None, "orig_price": None, "per_k": None,
               "free": False, "special": False, "name": "", "author": "",
               "translator": "", "publisher": "", "isbn": "", "words": "",
               "size": "", "pub_date": "", "rating": None, "rating_count": None,
               "chapters": None, "blurb": "", "intro": "", "brand": "",
               "cover": "", "status": "", "len": len(t)}
        m = re.search(r"<dt>([^<]{1,80})</dt>", t)
        out["name"] = m.group(1).strip() if m else ""

        # ---- 作者区：作者 / 译者 / 版权品牌方 ----
        da = re.search(r'<dd class="d_author">(.*?)</dd>', t, re.S)
        if da:
            names = [_clean(x[1]) for x in
                     re.findall(r"<span([^>]*)>([^<]+)</span>", da.group(1))]
            plain = [n for n in names if n and n != "|"]
            out["translator"] = next((n for n in plain if "[译]" in n), "")
            out["author"] = next((n for n in plain if "[译]" not in n), "")
            # 末位无 [著]/[译] 标记的通常是版权品牌方
            if len(plain) > 1 and not re.search(r"\[[著编译绘]\]", plain[-1]):
                out["brand"] = plain[-1]
            else:
                # 作者区不可靠时回退到免责声明里的版权方
                out["brand"] = _clean(
                    (re.search(r"数字版权由([^提]{2,20})提供", t) or [0, ""])[1])
        else:
            m = re.search(r'data-js="author-page"[^>]*>([^<]{1,50})</span>', t)
            out["author"] = _clean(m.group(1)) if m else ""

        # ---- 价格 ----
        m = re.search(r'<span class="dark_gray">\s*([0-9.]+)\s*阅饼\s*</span>', t)
        if m:
            out["price"] = float(m.group(1))
        m = re.search(r"<del>\s*([0-9.]+)\s*阅饼\s*</del>", t)
        if m:
            out["orig_price"] = float(m.group(1))
        m = re.search(r"([0-9.]+)\s*阅饼/千字", t)
        if m:
            out["per_k"] = float(m.group(1))
        out["free"] = bool(re.search(r'<span class="dark_gray">\s*免费\s*</span>', t))
        out["special"] = "特价" in t
        # 连载/完结 + 网文字数（`<dd class="font_inof"><span class="font_num">连载中 20.6万字`）
        m = re.search(r'class="font_num">\s*(连载中|已完结)\s*(.*?)</span>', t)
        if m:
            out["status"] = m.group(1)
            out["words"] = out["words"] or _clean(m.group(2))

        # ---- 推荐语 + 内容简介 ----
        m = re.search(r'class="dt_info">\s*(.*?)</div>', t, re.S)
        out["blurb"] = _clean(m.group(1))[:200] if m else ""
        m = re.search(r'data-js="brief_intro_txt">(.*?)</p>', t, re.S)
        out["intro"] = _clean(m.group(1)) if m else ""

        # ---- 图书更多信息（出版社 / 书号 / 字数 …）----
        info = dict(re.findall(r"<p>(字数|大小|上架时间|出版社|书号|出版时间)："
                               r"(.*?)</p>", t))
        out["words"] = _clean(info.get("字数", ""))
        out["size"] = _clean(info.get("大小", ""))
        out["pub_date"] = _clean(info.get("上架时间") or info.get("出版时间", ""))
        out["publisher"] = _clean(info.get("出版社", ""))
        out["isbn"] = _clean(info.get("书号", ""))

        # ---- 评分 / 章节数 / 封面 ----
        m = re.search(r"stars_box.*?custom-font'?>([0-9.]+)</strong>", t, re.S)
        if m:
            out["rating"] = float(m.group(1))
        m = re.search(r"(\d+)人评分", t)
        if m:
            out["rating_count"] = int(m.group(1))
        m = re.search(r"共(\d+)章", t)
        if m:
            out["chapters"] = int(m.group(1))
        m = re.search(r'class="bookcover" src="([^"]+)"', t)
        if m:
            out["cover"] = m.group(1)
        return out

    # ---------- 分类页（覆盖远大于榜单） ----------

    def categories(self, channel: str) -> list[tuple[str, str]]:
        t = _fetch(f"{CAT_BASE}?ca=booksort.index&pca=bookrank.index"
                   f"&pid={channel}&cid=93&page=1", PC_UA)
        seen: dict[str, str] = {}
        for c, n in re.findall(r"cid=(\d+)[^>]*>([^<]{1,12})<", t):
            seen.setdefault(c, n)
        return sorted(seen.items())

    @staticmethod
    def _parse_cards(html: str) -> list[dict]:
        out = []
        for li in re.split(r"<li>", html):
            if "bookdetail.index" not in li:
                continue
            m = re.search(r"bid=(\d+)", li)
            if not m:
                continue
            nm = (re.search(r"<h3><a[^>]*>([^<]+)</a></h3>", li) or [None, ""])[1]
            out.append({"id": m.group(1), "name": nm.strip()})
        return out

    def cat_pages(self, channel: str, cid: str, status: str = "2",
                  order: str = "download", pages: int = 2) -> list[dict]:
        """抓某分类前 N 页（热门书排前面，所以前几页就够）。"""
        out: list[dict] = []
        for pg in range(1, pages + 1):
            html = _fetch(f"{CAT_BASE}?ca=booksort.index&pca=bookrank.index"
                          f"&pid={channel}&cid={cid}&order={order}"
                          f"&status={status}&page={pg}", PC_UA)
            got = self._parse_cards(html)
            if not got:
                break
            out += got
            if pg < pages:
                time.sleep(self.delay)
        return out

    def cat_many(self, targets: list[tuple[str, str]], status: str = "2",
                 order: str = "download", pages: int = 2) -> list[dict]:
        """并发抓多个分类（targets = [(频道, cid)]），保持分类顺序返回。

        分类页抓取是纯 HTML 拉取、无依赖，并发能把 40+ 分类的等待时间
        从「串行 × 每类 1~2 秒」压到几秒。
        每本书带 `_cat` 标记（"频道/cid"），供 _interleave 做跨分类取样。
        """
        if not targets:
            return []

        def one(ch: str, cid: str) -> list[dict]:
            rows = self.cat_pages(ch, cid, status, order, pages)
            for r in rows:
                r["_cat"] = f"{ch}/{cid}"
            return rows

        out: list[dict] = []
        with cf.ThreadPoolExecutor(min(self.workers, 8)) as ex:
            futs = [ex.submit(one, ch, cid) for ch, cid in targets]
            for f in futs:
                try:
                    out += f.result()
                except Exception:
                    pass
        return out

    # ---------- 搜索 ----------

    def search(self, keyword: str, max_pages: int = 3) -> list[dict]:
        """按书名/作者搜全书城（注意域名是 m.zhangyue.com）。"""
        kw = urllib.parse.quote(keyword)
        page = _fetch(f"{M_BASE}/search?keyWord={kw}", APP_UA, referer=f"{M_BASE}/")
        if not page.strip():
            return []
        rows = self._parse_search(page)
        total = int((re.search(r'totalpage="(\d+)"', page) or [0, 1])[1] or 1)
        for pg in range(2, min(total, max_pages) + 1):
            time.sleep(self.delay)
            raw = _fetch(f"{M_BASE}/search/more?keyWord={kw}&currentPage={pg}",
                         APP_UA, referer=f"{M_BASE}/search?keyWord={kw}")
            if not raw.strip().startswith("{"):
                break
            try:
                rows += self._parse_search(json.loads(raw).get("html") or "")
            except ValueError:
                break
        seen, uniq = set(), []
        for r in rows:
            if r["id"] not in seen:
                seen.add(r["id"])
                uniq.append(r)
        return uniq

    @staticmethod
    def _parse_search(html: str) -> list[dict]:
        out = []
        for card in re.split(r'<div class="bk1 flex"', html)[1:]:
            bid = (re.search(r'data-id="(\d+)"', card) or [None, None])[1]
            if not bid:
                continue
            out.append({
                "id": bid,
                "name": ((re.search(r'<div class="name ellipsis">([^<]*)</div>', card)
                          or [None, ""])[1] or "").strip(),
                "author": ((re.search(r'<div class="author ellipsis">([^<]*)</div>', card)
                            or [None, ""])[1] or "").strip(),
            })
        return out

    # ---------- 批量查价 ----------

    def price_many(self, ids: list[str]) -> dict[str, dict]:
        out: dict[str, dict] = {}
        if not ids:
            return out
        with cf.ThreadPoolExecutor(self.workers) as ex:
            for r in ex.map(self.detail, ids):
                out[r["id"]] = r
        return out

    def filter_buyable(self, cands: list[dict], limit: float,
                       skip_owned: bool = True, top: int | None = None) -> list[dict]:
        """候选 → 查价 → 只留「未拥有 且 0 < 价格 ≤ limit」的书。

        top: 只查前 N 本。候选若来自多分类（cat_many），先按分类轮转交错，
             避免「只查了第一个分类」——保证样本横跨各类。
        """
        if top is not None and len(cands) > top:
            cands = _interleave(cands, top)
        ids = [c["id"] for c in cands]
        priced = self.price_many(ids)
        name_map = {c["id"]: c.get("name", "") for c in cands}
        shelf = self.shelf_ids() if skip_owned else set()

        hits = []
        for bid, r in priced.items():
            if not r.get("price") or r["price"] <= 0 or r["price"] > limit:
                continue
            if bid in shelf:
                continue
            r["name"] = r["name"] or name_map.get(bid, "")
            hits.append(r)

        # 别名复核：书架判定未拥有，但服务端可能已拥有（同书多 ID）
        if skip_owned and hits:
            with cf.ThreadPoolExecutor(self.workers) as ex:
                checked = dict(zip([h["id"] for h in hits],
                                   ex.map(self.is_owned, [h["id"] for h in hits])))
            hits = [h for h in hits if checked.get(h["id"]) is not True]
        return hits

    # ---------- 下单（⚠️ 写操作，会真扣券） ----------

    def quote(self, bid: str) -> dict:
        """打开订单页询价（不扣费），解析需支付额与一次性令牌 chargingStr。"""
        html = _fetch(
            f"{APP_BASE}/zytc/public/index.php?ca=Order.Create&alone="
            f"&bid={bid}&cid=0&pay_360=&pca=client_askOrder&pk=askOrder"
            f"&projectSource=zybook3&{self.auth}", APP_UA,
            referer=f"{APP_BASE}/")
        txt = _text(html)
        out: dict = {"bid": str(bid), "text": txt, "ok": bool(html),
                     "need": None, "have": None, "price": None,
                     "owned": False, "insufficient": False, "token": None}
        m = re.search(r"需支付：\s*([0-9.]+)\s*代金券", txt)
        if m:
            out["need"] = float(m.group(1))
        m = re.search(r"余额：\s*([0-9.]+)\s*阅饼\s*([0-9.]+)\s*代金券", txt)
        if m:
            out["have"] = float(m.group(2))
        m = re.search(r"价格：\s*(?:([0-9.]+)\s*阅饼\s*)?([0-9.]+)\s*阅饼", txt)
        if m:
            out["price"] = float(m.group(2))
        out["owned"] = ("已拥有" in txt or "您已购买本书" in txt)
        out["insufficient"] = "余额不足" in txt
        m = re.search(r"chargingStr=([A-Za-z0-9%]+)", html)
        out["token"] = m.group(1) if m else None
        return out

    def pay(self, token: str) -> dict:
        """提交真实订单（会扣券）。token 来自 quote()。"""
        raw = _fetch(
            f"{APP_BASE}/zytc/public/index.php?ca=Order.Pay&pca=Order.Create"
            f"&projectSource=zybook3&{self.auth}&chargingStr={token}"
            f"&pk=askOrder&rgt=", APP_UA, referer=f"{APP_BASE}/")
        try:
            return json.loads(raw)
        except ValueError:
            return {"_raw": raw[:300]}

    # ---------- 新版订单通道（支持满减券 + 代金券/阅饼混合支付） ----------
    #
    # 旧通道（Order.Create + Order.Pay）只认代金券、必须全额覆盖售价、用不了满减券。
    # 新版 Vue 订单页走 `/trade/order/{volume,pay}`：试算会同时给出满减券折扣、
    # 代金券抵扣额、阅饼抵扣额与差额，下单时把 `coupon_code` 一并提交即可用上满减券。
    # 实测（2026-11-12，Web 端）：body 只需 6 个字段，不需要任何签名。

    def order_quote(self, bid: str) -> dict:
        """新版通道试算（不扣费）：满减券折扣、代金券/阅饼各抵多少、还差多少。

        返回字段：
          price      标价（阅饼）
          dis_price  活动价（阅饼）
          coupon     满减券 {code, amount, threshold}，无可用券时为 None
          amount     折后应付（阅饼）
          voucher    代金券抵扣额（阅饼）
          yb         阅饼抵扣额（阅饼）
          gap        还差多少（阅饼），够付时为 0
          enough     代金券 + 阅饼是否够付
          token      下单令牌
        """
        url = (f"{APP_BASE}/trade/order/volume?bid={bid}&cid=0&vbuy=0"
               f"&coupon_code=&time={int(time.time() * 1000)}"
               f"&{PC_PAGE_PARAMS}&{self.auth}")
        raw = _fetch(url, APP_UA, referer=f"{APP_BASE}/")
        out: dict = {"bid": str(bid), "ok": False, "price": None, "dis_price": None,
                     "coupon": None, "amount": None, "voucher": None, "yb": None,
                     "gap": None, "enough": False, "token": None, "name": ""}
        if not raw.strip().startswith("{"):
            return out
        try:
            body = (json.loads(raw) or {}).get("body") or {}
        except ValueError:
            return out
        p = body.get("pay") or {}
        cp = body.get("coupon") or {}
        bi = body.get("book_info") or {}
        yuan = lambda x: round((x or 0) * 100, 2)   # 接口价格单位是元
        out.update({
            "ok": True,
            "name": bi.get("name") or "",
            "price": yuan(body.get("price")),
            "dis_price": yuan(body.get("dis_price")),
            "amount": yuan(p.get("amount")),
            "voucher": yuan(p.get("coupon_amount")),
            "yb": yuan(p.get("yb_amount")),
            "gap": yuan(p.get("gap_yb_amount")),
            "enough": bool(p.get("is_enough")),
            "token": p.get("token"),
            "support_voucher": body.get("is_support_voucher", True),
        })
        if cp.get("code"):
            out["coupon"] = {"code": cp.get("code"),
                             "amount": cp.get("amount") or 0,
                             "threshold": cp.get("condition_amount") or 0}
        return out

    def pay_v2(self, q: dict) -> dict:
        """新版通道下单（⚠️ 会真扣券）。参数取自 order_quote() 的返回。

        实测 body 只需 6 个字段，签名参数一个都不要：
          type / token / price / dis_price / bid / coupon_code
        """
        params = {
            "type": "volume",
            "token": q.get("token") or "",
            "price": round((q.get("price") or 0) / 100, 2),        # 元
            "dis_price": round((q.get("dis_price") or 0) / 100, 2),  # 元
            "bid": str(q.get("bid")),
            "coupon_code": (q.get("coupon") or {}).get("code") or "",
        }
        if not params["token"]:
            return {"code": -1, "msg": "缺少下单令牌"}
        body = urllib.parse.urlencode(params).encode()
        url = (f"{APP_BASE}/trade/order/pay?bid={q.get('bid')}&cid=0&vbuy=0"
               f"&pk=askOrder&rgt={PC_PAGE_PARAMS}&{self.auth}")
        req = urllib.request.Request(
            url, data=body, method="POST",
            headers={"User-Agent": APP_UA,
                     "Content-Type": "application/x-www-form-urlencoded",
                     "Referer": f"{APP_BASE}/"})
        for i in range(2):
            try:
                with urllib.request.urlopen(req, timeout=25) as r:
                    raw = r.read().decode("utf-8", "ignore")
                return json.loads(raw)
            except (urllib.error.URLError, ValueError):
                time.sleep(0.8 * (i + 1))
        return {"code": -1, "msg": "下单请求失败"}

    # ---------- 加入云书架（写操作） ----------

    def shelf_add(self, bid: str, name: str, book_type: int = 24,
                  dry: bool = False, folder: str = "") -> dict:
        """把已购书籍补进云书架。掌阅「购买」与「加书架」是两步。

        `folder` 非空时直接落到该文件夹（等价于「加书架 + 移动」一步做完）；
        文件夹不存在会自动补建。
        """
        rows, ver = self._shelf_rows()
        if bid in {str(r.get("book_id")) for r in rows}:
            return {"code": 0, "msg": "已在书架，无需添加", "skipped": True,
                    "total": len(rows), "version": ver}
        orders = [r.get("order") for r in rows
                  if isinstance(r.get("order"), (int, float))]
        new_order = (int(min(orders)) - 1) if orders else 0
        row = {
            "book_id": str(bid), "book_name": name, "cover_name": "",
            "book_type": book_type, "is_local_book": False,
            "book_file_id": "", "book_file_size": 0,
            "cover_file_id": "", "cover_file_size": 0,
            "folder_hierarchy": (json.dumps([folder], ensure_ascii=False)
                                 if folder else "[]"),
            "dtype": 0, "order": new_order,
            "folder": "", "top": 0, "top_sort": 0, "md5": "", "mark": "",
        }
        if dry:
            return {"code": 0, "msg": "[dry] 未写入", "dry": True,
                    "total": len(rows), "version": ver, "row": row}
        if folder:
            # 目标文件夹不存在时先建，否则书架里会出现「只挂在书上的文件夹」
            exist = {_folder_of(it) for it in self.shelf_tree()[0]
                     if it.get("dtype") == 1}
            if folder not in exist:
                mv = self.shelf_move([], folder, create=True)
                if mv.get("code") != 0:
                    return mv
                _, ver = self.shelf_tree()
        r = self._upsert_shelf([row], ver, "1")
        r["before_total"], r["before_version"] = len(rows), ver
        return r

    def _shelf_rows(self) -> tuple[list[dict], int]:
        items, ver = self.shelf_tree()
        rows = []
        for it in items:
            rows += (it.get("children") or [it])
        return rows, ver

    def shelf_tree(self) -> tuple[list[dict], int]:
        """书架**原始顶层数组**（含 dtype=1 的文件夹节点）+ current_version。

        与 `_shelf_rows()` 的区别：那个把 children 摊平成纯书列表，
        这里保留文件夹节点，用来还原「有哪些文件夹、各装了几本」。
        """
        t = _fetch(f"{PC_BASE}/cloud/bookshelf/list?{self.auth}&{PC_PAGE_PARAMS}",
                   PC_UA)
        try:
            body = (json.loads(t).get("body") or {})
            data = body.get("data")
            if isinstance(data, str):
                data = json.loads(data)
        except (ValueError, TypeError):
            body, data = {}, []
        return (data or []), body.get("current_version") or 0

    def shelf_layout(self) -> dict:
        """书架结构快照：文件夹清单 + 各文件夹书数 + 未归类书。

        书架是一个**扁平数组**，两类条目混在一起：
          * `dtype=0` 书，`folder_hierarchy` 是 `["文件夹名"]` 或 `[]`
          * `dtype=1` 文件夹节点，`folder_hierarchy` 即自身名字
        `dtype` 是唯一判据；`mark="A_1"` 文件夹节点和本地导入书都有，别用它区分。
        多级路径是 `["一级","二级"]`，本账号实测只有一级。
        """
        items, ver = self.shelf_tree()
        rows = []
        for it in items:
            rows += (it.get("children") or [it])

        folders: dict[str, dict] = {}
        for it in items:
            if it.get("dtype") == 1:
                name = _folder_of(it)
                if name:
                    folders[name] = {"name": name, "id": str(it.get("book_id")),
                                     "count": 0}
        books, loose = [], []
        for r in rows:
            if r.get("dtype") == 1:
                continue
            books.append(r)
            name = _folder_of(r)
            if name:
                folders.setdefault(name, {"name": name, "id": "", "count": 0})
                folders[name]["count"] += 1
            else:
                loose.append(r)
        return {"version": ver, "total": len(books),
                "folders": sorted(folders.values(),
                                  key=lambda f: (-f["count"], f["name"])),
                "loose": loose, "books": books}

    def shelf_move(self, bids: list[str], folder: str,
                   create: bool = False, dry: bool = False) -> dict:
        """把书移动到文件夹（`folder=""` 表示移出到未归类）。⚠️ 写操作

        掌阅的文件夹只是条目上的一个 `folder_hierarchy` 字段，书本身不用挪位置，
        所以「移动」= 改这个字段再 upsert 回去（type=3 更新）。
        文件夹不存在时可以 `create=True` 顺手建一个空文件夹节点。
        """
        items, ver = self.shelf_tree()
        existing = {_folder_of(it) for it in items if it.get("dtype") == 1}
        existing.discard("")
        if folder and folder not in existing and not create:
            return {"code": -1, "msg": f"没有「{folder}」这个文件夹",
                    "folders": sorted(existing)}
        want = json.dumps([folder], ensure_ascii=False) if folder else "[]"

        index: dict[str, dict] = {}
        for it in items:
            for r in (it.get("children") or [it]):
                if r.get("dtype") != 1:
                    index[str(r.get("book_id"))] = r

        changed, missing, same = [], [], []
        for bid in bids:
            r = index.get(str(bid))
            if r is None:
                missing.append(bid)
                continue
            cur = r.get("folder_hierarchy") or "[]"
            if isinstance(cur, list):
                cur = json.dumps(cur, ensure_ascii=False)
            if cur == want:
                same.append(bid)
                continue
            r["folder_hierarchy"] = want
            changed.append(r)

        out = {"code": 0, "folder": folder or "（未归类）",
               "moved": [str(r.get("book_id")) for r in changed],
               "already": same, "missing": missing,
               "before_version": ver}
        if missing and not changed:
            out.update(code=-1, msg="这些书不在书架里，无法移动")
            return out
        if not changed and not (folder and folder not in existing):
            out.update(code=0, msg="无需改动")
            return out
        if dry:
            out.update(dry=True,
                       row=[{k: r.get(k) for k in ("book_id", "book_name",
                                                   "folder_hierarchy")}
                            for r in changed])
            return out

        # 文件夹不存在：先插一个文件夹节点（type=1），版本号会变，要重新读
        if folder and folder not in existing:
            r = self.shelf_mkdir(folder)
            if r.get("code") != 0:
                out.update(r, msg=f"新建文件夹失败：{r.get('msg', '')}")
                return out
            time.sleep(1)
            _, ver = self.shelf_tree()
            out["folder_created"] = folder

        if changed:
            r = self._upsert_shelf(changed, ver, "3")
            if r.get("code") != 0:
                out.update(r)
                return out
        out["code"] = 0
        out["msg"] = "ok"
        return out

    def shelf_mkdir(self, folder: str) -> dict:
        """新建空文件夹节点（`dtype=1`）。已存在时跳过。⚠️ 写操作

        实测服务端**不会**因为某本书的 `folder_hierarchy` 指向新名字就自动建文件夹，
        必须显式插一个节点。
        """
        items, ver = self.shelf_tree()
        if folder in {_folder_of(it) for it in items if it.get("dtype") == 1}:
            return {"code": 0, "msg": "文件夹已存在", "skipped": True}
        node = {
            "book_id": uuid.uuid4().hex[:8], "book_name": "", "cover_name": "",
            "book_type": 0, "is_local_book": False, "book_file_id": "",
            "book_file_size": 0, "cover_file_id": "", "cover_file_size": 0,
            "folder_hierarchy": json.dumps([folder], ensure_ascii=False),
            "dtype": 1, "order": _next_folder_order(items), "folder": "",
            "top": 0, "top_sort": 0, "mark": "A_1", "btype_ext": 0,
        }
        return self._upsert_shelf([node], ver, "1")

    def shelf_rmdir(self, folder: str, force: bool = False) -> dict:
        """删除文件夹节点。⚠️ 写操作

        默认拒绝删「还有书的文件夹」——直接删节点后那些书仍带着一个
        不存在的文件夹名，比留着更乱。加 `--force` 会先把书移出到未归类，
        再删节点，不会丢书。
        """
        items, ver = self.shelf_tree()
        nodes = [it for it in items
                 if it.get("dtype") == 1 and _folder_of(it) == folder]
        if not nodes:
            return {"code": -1, "msg": f"没有「{folder}」这个文件夹"}
        inside = [r for it in items
                  for r in (it.get("children") or [it])
                  if r.get("dtype") != 1 and _folder_of(r) == folder]
        if inside and not force:
            return {"code": -2, "folder": folder,
                    "msg": f"「{folder}」里还有 {len(inside)} 本书，先移走再删",
                    "books": [{"id": str(r.get("book_id")),
                               "name": r.get("book_name", "")} for r in inside]}
        out: dict = {}
        if inside:
            for r in inside:
                r["folder_hierarchy"] = "[]"
            moved = self._upsert_shelf(inside, ver, "3")
            if moved.get("code") != 0:
                return moved
            time.sleep(1)
            _, ver = self.shelf_tree()
            out["moved_out"] = len(inside)
        result = self._upsert_shelf(nodes, ver, "2")
        result.update(out)
        return result

    def _upsert_shelf(self, rows: list[dict], ver: int, typ: str) -> dict:
        """写书架。`typ`：1=新增插入，2=删除，3=更新（已实测）。

        所有写操作都要带 `current_version`，每写一次版本号 +1，
        连续写之间必须重新读书架拿新版本，否则报 `100006 version not equal error`。
        """
        boundary = "----zypick" + uuid.uuid4().hex[:16]

        def part(k: str, v: str) -> bytes:
            return (f"--{boundary}\r\nContent-Disposition: form-data; "
                    f'name="{k}"\r\n\r\n{v}\r\n').encode("utf-8")

        payload = b""
        payload += part("usr", self.auth.split("&")[0].split("=")[1])
        payload += part("current_version", str(ver))
        payload += part("type", typ)
        payload += part("data", json.dumps(rows, ensure_ascii=False))
        payload += f"--{boundary}--\r\n".encode()
        raw = _post(f"{PC_BASE}/cloud/bookshelf/upsert?{self.auth}&{PC_PAGE_PARAMS}",
                    payload, f"multipart/form-data; boundary={boundary}", PC_UA)
        try:
            return json.loads(raw)
        except ValueError:
            return {"_raw": raw[:200]}


def _folder_of(row: dict) -> str:
    """取条目所属文件夹的**一级名**（书架只有一级；多级时也只看第一级）。"""
    fh = row.get("folder_hierarchy")
    if isinstance(fh, str):
        try:
            fh = json.loads(fh)
        except ValueError:
            return ""
    if isinstance(fh, list) and fh:
        return str(fh[0])
    return ""


def _next_folder_order(items: list[dict]) -> int:
    """新建文件夹节点的 order：用 1000000 起的递增段，排在书后面。

    实测掌阅自己的文件夹节点就用 1000003/1000005/…，这里跟随同样风格，
    避免用「最小 order − 1」跟书抢最前面位置。
    """
    used = [it.get("order") for it in items
            if it.get("dtype") == 1 and isinstance(it.get("order"), (int, float))]
    base = max([1000000] + [int(o) for o in used if o >= 1000000])
    return base + 1


def _interleave(cands: list[dict], top: int) -> list[dict]:
    """按来源分类轮转取前 top 本，保证样本横跨各类（而非只取头部一个分类）。

    cat_many 给每本打了 _cat 标记（"频道/cid"），这里按 _cat 分组后轮流各取一本。
    没有标记时退化为直接截断。
    """
    groups: dict[str, list[dict]] = {}
    for c in cands:
        groups.setdefault(c.get("_cat", ""), []).append(c)
    if len(groups) <= 1:
        return cands[:top]
    out: list[dict] = []
    idx = {k: 0 for k in groups}
    keys = list(groups)
    while len(out) < top:
        progressed = False
        for k in keys:
            i = idx[k]
            if i < len(groups[k]):
                out.append(groups[k][i])
                idx[k] = i + 1
                progressed = True
                if len(out) >= top:
                    break
        if not progressed:
            break
    return out


def normalize_title(name: str) -> str:
    """书名归一化：去括号标记、全角转半角、去空白分隔符，用于同名分组。"""
    if not name:
        return ""
    s = re.sub(r"[\[【(（][^\]】)）]{0,12}[\]】)）]", "", name)
    s = re.sub(r"[\s\-—–_·・:：,，.。、!！?？'\"“”‘’]+", "", s)
    return s.lower()


# ---------------------------------------------------------------- 输出

def isbn_valid(isbn: str) -> bool:
    """ISBN-10 / ISBN-13 校验位验证。数据可信度用，不通过也不删。"""
    s = re.sub(r"[^0-9Xx]", "", isbn or "")
    if len(s) == 13 and s.isdigit():
        total = sum(int(c) * (1 if i % 2 == 0 else 3) for i, c in enumerate(s[:12]))
        return (10 - total % 10) % 10 == int(s[12])
    if len(s) == 10:
        if not s[:9].isdigit():
            return False
        total = sum((10 - i) * (10 if c in "Xx" else int(c))
                    for i, c in enumerate(s))
        return total % 11 == 0
    return False


def fmt_book(i: int, r: dict, vouchers: float | None = None,
             intro: bool = False) -> str:
    """vouchers = 真实可用券额，仅用于「能否零付」标记（不要用筛选上限代替）。"""
    price = f"{r['price']:>6.0f} 阅饼" if r.get("price") else "    免费"
    zero = ""
    if vouchers is not None and r.get("price"):
        zero = "  ✅ 券够，可 0 元" if r["price"] <= vouchers else "  ❌ 券不够"
    sp = " [特价]" if r.get("special") else ""
    # 版本辨识三件套：作者 / 译者 / 出版社 —— 同名书靠这些区分
    meta = [x for x in (r.get("author", "")[:20], r.get("translator", ""),
                        r.get("publisher", "")[:14]) if x]
    rate = ""
    if r.get("rating") is not None:
        rate = f"{r['rating']:.1f}分"
        if r.get("rating_count"):
            rate += f"({r['rating_count']}人)"
    # 豆瓣评分（--douban 时才有）
    db = ""
    dbr = r.get("douban") or {}
    if dbr.get("rating") is not None:
        db = f"豆瓣 {dbr['rating']:.1f}"
        if dbr.get("rating_count"):
            db += f"({dbr['rating_count']}人)"
    elif dbr:
        db = f"豆瓣 {'—'}"
    # ISBN 只有纸质出版物才有，网文一律为空，所以有才显示
    isbn = f"ISBN {r['isbn']}" if r.get("isbn") else ""
    tail = "  ".join(x for x in (isbn, rate, db) if x)
    line2 = " · ".join(meta) + (f"  {tail}" if tail else "")
    out = (f"{i:>3}. {price}{zero}{sp}  {r['name'][:34]}\n"
           f"       {line2}")
    if intro:
        snip = r.get("blurb") or r.get("intro") or ""
        if snip:
            # 原文截 160 字作为素材：供智能体用大模型整理成语义完整的简介；
            # 直接终端运行时这就是掌阅推荐语原文（不按句子截断，原样输出更完整）。
            out += f"\n       {snip[:160]}"
    return out


def fmt_detail(d: dict) -> str:
    """单本书的完整书目信息（人类可读）。"""
    L = [f"《{d['name']}》"]
    by = d.get("author", "")
    if d.get("translator"):
        by += f"   {d['translator']}"
    if by.strip():
        L.append(f"作者   {by.strip()}")
    if d.get("publisher"):
        L.append(f"出版   {d['publisher']}"
                 + (f"   ISBN {d['isbn']}" if d.get("isbn") else ""))
    elif d.get("isbn"):
        L.append(f"书号   {d['isbn']}")
    if d.get("isbn") and not isbn_valid(d["isbn"]):
        L.append("提示   ISBN 校验位不通过，可能登记有误，下单前请再核对")
    facts = "   ".join(x for x in (d.get("words", ""), d.get("size", ""),
                                   d.get("pub_date", ""),
                                   f"共{d['chapters']}章" if d.get("chapters") else "",
                                   d.get("status", "")) if x)
    if facts:
        L.append(f"规格   {facts}")
    if d.get("rating") is not None:
        L.append(f"评分   {d['rating']:.1f} 分"
                 + (f"（{d['rating_count']} 人评价）" if d.get("rating_count") else ""))
    if d.get("brand"):
        L.append(f"版权   {d['brand']}")
    if d.get("blurb"):
        L.append(f"一句话 {d['blurb']}")
    if d.get("intro"):
        body = d["intro"]
        L.append("简介   " + (body if len(body) <= 420 else body[:420] + "…（--json 看全文）"))
    if d.get("cover"):
        L.append(f"封面   {d['cover']}")
    return "\n".join(L)


def main():
    ap = argparse.ArgumentParser(
        description="掌阅选书助手（只读，不下单）",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__)
    ap.add_argument("--auth", help='凭证串 "usr=iXXX&zysid=YYY"')
    ap.add_argument("--workers", type=int, default=8, help="并发数（默认 8）")
    ap.add_argument("--json", action="store_true", help="JSON 输出")

    sub = ap.add_subparsers(dest="cmd")
    _common = argparse.ArgumentParser(add_help=False)
    _common.add_argument("--auth", default=argparse.SUPPRESS,
                         help='凭证串 "usr=iXXX&zysid=YYY"')
    _common.add_argument("--json", action="store_true", default=argparse.SUPPRESS,
                         help="JSON 输出")
    _common.add_argument("--workers", type=int, default=argparse.SUPPRESS,
                         help="并发数")
    _common.add_argument("--douban", action="store_true", default=argparse.SUPPRESS,
                         help="额外查豆瓣评分（按 ISBN，慢，限量分批）")
    _common.add_argument("--douban-top", type=int, default=argparse.SUPPRESS,
                         help="--douban 时最多查多少本（默认 20，保护豆瓣限速）")

    p = sub.add_parser("login", help="手机号+密码登录，成功后写入 config.json")
    p.add_argument("phone", help="手机号（即掌阅账号）")
    p.add_argument("--password", default=None,
                   help="密码；不加则隐藏输入（推荐，避免留在命令历史里）")
    p.add_argument("--no-save", action="store_true",
                   help="只登录验证，不写入 config.json")

    p = sub.add_parser("balance", help="阅饼余额 + 代金券（含到期日）", parents=[_common])

    p = sub.add_parser("coupons", help="满减券（满 X 减 Y），含门槛与有效期",
                       parents=[_common])
    p.add_argument("--kind", default="book", choices=["book", "goods"],
                   help="book=书籍优惠券(默认) / goods=实物商品优惠券")

    p = sub.add_parser("afford", help="能零付买下哪些书（按可用券额）", parents=[_common])
    p.add_argument("--limit", type=float, default=None,
                   help="价格上限（默认=可用代金券总额）")
    p.add_argument("--coupon", action="store_true",
                   help="把满减券算进去：上限提高到「券额+满减面额」，"
                        "列出在掌阅 App 里用券后能零付的书")
    p.add_argument("--full", action="store_true",
                   help="穷举全书城（慢，约 10 分钟）；默认只扫热门页")
    p.add_argument("--channels", default="92", help="频道，默认 92=出版")
    p.add_argument("--status", default="2", help="0全部/1免费/2特价/3完结/4VIP")
    p.add_argument("--top", type=int, default=600,
                   help="最多查价多少本（默认 600；--full 时忽略）")

    p = sub.add_parser("recommend", help="按热度/好评推荐能买的书", parents=[_common])
    p.add_argument("--sort", default="download", choices=list(ORDERS),
                   help="download=热门(默认) / score=好评 / update=最新")
    p.add_argument("--limit", type=float, default=None, help="价格上限")
    p.add_argument("--channels", default="92,10,68", help="频道，默认全部")
    p.add_argument("--per-cat", type=int, default=2, help="每分类抓几页（默认 2）")
    p.add_argument("--top", type=int, default=400,
                   help="最多查价多少本（候选已按热度排序，默认 400）")

    p = sub.add_parser("category", help="按分类推荐（如 计算机 / 推理悬疑）", parents=[_common])
    p.add_argument("name", help="分类名，见 SKILL.md 分类表")
    p.add_argument("--limit", type=float, default=None, help="价格上限")
    p.add_argument("--sort", default="download", choices=list(ORDERS))
    p.add_argument("--per-cat", type=int, default=3, help="抓几页（默认 3）")
    p.add_argument("--top", type=int, default=300, help="最多查价多少本（默认 300）")
    p.add_argument("--status", default="2", help="筛选，默认特价")

    p = sub.add_parser("search", help="按书名/类型检索", parents=[_common])
    p.add_argument("keyword", help="书名或题材关键词")
    p.add_argument("--limit", type=float, default=None, help="价格上限")
    p.add_argument("--exact", action="store_true", help="只留书名/作者含关键词的")
    p.add_argument("--pages", type=int, default=3, help="翻页上限（默认 3）")
    p.add_argument("--top", type=int, default=150, help="最多查价多少本（默认 150）")

    p = sub.add_parser("info", help="单本详情：书目/价/是否已有/券能否抵扣",
                       parents=[_common])
    p.add_argument("bid", help="book_id")

    p = sub.add_parser("categories", help="列出所有分类（可用 name）", parents=[_common])
    p.add_argument("--channel", default="92", help="频道，默认 92=出版")

    p = sub.add_parser("buy", help="⚠️ 下单购买（默认只询价，--confirm 才真扣券）",
                       parents=[_common])
    p.add_argument("bid", help="book_id")
    p.add_argument("--confirm", action="store_true",
                   help="⚠️ 真正提交订单并扣券；不加则只询价")
    p.add_argument("--max-voucher", type=float, default=None,
                   help="最多允许多少券，超出即中止")
    p.add_argument("--no-shelf", action="store_true",
                   help="下单成功后不自动加入云书架")
    p.add_argument("--folder", default="",
                   help="买完加书架时直接放进这个文件夹（不存在会自动建）")
    p.add_argument("--ignore-coupon", action="store_true",
                   help="确认不用满减券：按活动价全额用代金券支付")

    p = sub.add_parser("shelf", help="把已购书籍补进云书架（购买≠加书架）",
                       parents=[_common])
    p.add_argument("bid", help="book_id")
    p.add_argument("--name", default="", help="书架显示的书名")
    p.add_argument("--folder", default="", help="直接放进这个文件夹（不存在会自动建）")
    p.add_argument("--dry", action="store_true", help="只预览，不写入")

    p = sub.add_parser("shelves", help="查看书架结构与各文件夹书数（只读）",
                       parents=[_common])
    p.add_argument("--books", action="store_true", help="同时列出文件夹里的书名")
    p.add_argument("--folder", default=None,
                   help="只看某个文件夹（加 --books 才列书名）")

    p = sub.add_parser("move", help="把书移动到书架文件夹（⚠️ 写操作）",
                       parents=[_common])
    p.add_argument("bids", nargs="+", help="book_id，可给多个")
    p.add_argument("--to", default="", help="目标文件夹；留空 = 移出到未归类")
    p.add_argument("--create", action="store_true", help="目标文件夹不存在时自动新建")
    p.add_argument("--dry", action="store_true", help="只预览，不写入")

    p = sub.add_parser("mkdir", help="新建书架文件夹（⚠️ 写操作）",
                       parents=[_common])
    p.add_argument("folder", help="文件夹名")
    p.add_argument("--dry", action="store_true", help="只预览，不写入")

    p = sub.add_parser("rmdir", help="删除书架文件夹（⚠️ 写操作）",
                       parents=[_common])
    p.add_argument("folder", help="文件夹名")
    p.add_argument("--force", action="store_true",
                   help="文件夹里还有书时，先把书移出到未归类再删（不丢书）")
    p.add_argument("--dry", action="store_true", help="只预览，不写入")

    a = ap.parse_args()
    if not a.cmd:
        ap.print_help()
        return

    auth = load_auth(a.auth)
    c = Client(auth, workers=a.workers)
    show_intro = True   # 简介是列表默认字段（原 --intro 开关已废除）
    want_douban = getattr(a, "douban", False)
    douban_top = getattr(a, "douban_top", 20) or 20

    def enrich_douban(rows: list[dict]) -> None:
        """给命中列表补豆瓣评分（原地改 rows 的 douban 字段）。

        仅对有 ISBN 且前 douban_top 本生效——豆瓣限速，别一次查几百本。
        """
        if not want_douban or not rows:
            return
        pool = [r for r in rows if r.get("isbn")][:douban_top]
        if not pool:
            print("（豆瓣：这批书都没有 ISBN，跳过）", file=sys.stderr)
            return
        print(f"查豆瓣评分（{len(pool)} 本，限速中，约 {len(pool) * 0.5 / 4:.0f} 秒）…",
              file=sys.stderr)
        got = douban_many({r["id"]: r["isbn"] for r in pool},
                          titles={r["id"]: r.get("name", "") for r in pool})
        for r in pool:
            r["douban"] = got.get(r["id"], {})
        hit = sum(1 for r in pool if (r.get("douban") or {}).get("rating") is not None)
        lim = sum(1 for r in pool if (r.get("douban") or {}).get("limited"))
        mism = [r for r in pool
                if (r.get("douban") or {}).get("title_match") is False]
        print(f"（豆瓣：{hit}/{len(pool)} 本拿到评分）", file=sys.stderr)
        if lim:
            print(f"⚠️  {lim} 本被豆瓣限流（403/429）。豆瓣按 IP 封，"
                  f"冷却往往要十几分钟以上，建议稍后再试或减少 --douban-top。",
                  file=sys.stderr)
        for r in mism:
            print(f"⚠️  《{r['name'][:20]}》豆瓣匹配到不同版本："
                  f"{(r['douban'] or {}).get('note', '')}", file=sys.stderr)

    def douban_ask() -> None:
        """书目列表输出后询问是否查豆瓣评分（--json、已查豆瓣、无命中时不问）。"""
        if want_douban or a.json:
            return
        print("\n想看豆瓣评分对比？加 --douban 重跑即可"
              "（按 ISBN 查，豆瓣按 IP 限流，默认只查前 20 本）。")

    # ---------------- login（密码登录，写操作：改的是本地凭证文件） ----------------
    if a.cmd == "login":
        password = a.password
        if not password:
            import getpass
            password = getpass.getpass(f"请输入 {a.phone} 的掌阅密码（输入不回显）：")
        try:
            cred = password_login(a.phone, password)
        except RuntimeError as e:
            print(f"[失败] {e}", file=sys.stderr)
            sys.exit(1)
        if a.json:
            print(json.dumps(cred, ensure_ascii=False, indent=1))
        else:
            print(f"✅ 登录成功：{cred['nick'] or cred['usr']}（usr={cred['usr']}）")
        if a.no_save:
            print("（--no-save：未写入 config.json）")
        else:
            path = save_credentials(cred["usr"], cred["zysid"])
            print(f"凭证已写入 {path}，之后 balance / buy 等命令无需再传凭证。")
        return

    # ---------------- balance ----------------
    if a.cmd == "balance":
        auth = need_auth(auth)
        c = Client(auth, workers=a.workers)
        bal = c.balance()
        total, usable = c.usable_total()
        if a.json:
            print(json.dumps({"balance": bal, "usable_total": total,
                              "vouchers": usable}, ensure_ascii=False, indent=1))
            return
        print(f"阅饼余额   {bal['read_coin']}   （现金等价，可直接抵扣）")
        for name, val in bal["pairs"]:
            print(f"{name}   {val}")
        if bal["notice"]:
            print(f"⚠️  {bal['notice']}")
        print(f"\n可用代金券 {total:.0f} 阅饼（{len(usable)} 张）")
        for v in usable:
            d = v["days_left"]
            when = "今日过期 ⚠" if d == 0 else f"{d} 天后过期"
            print(f"   {v['amount']:>5.0f}  {v['expire']}  {when:<12} {v['source']}")
        print(f"\n→ 能零付买下售价 ≤ {total:.0f} 阅饼的书："
              f"python picker.py afford --limit {total:.0f}")
        cp = c.usable_coupons("book")
        if cp:
            print(f"\n另有满减券 {len(cp)} 张（不等于代金券，达到门槛才可选择使用）：")
            for v in cp:
                print(f"   {v['name']}  {v['amount']:.0f}阅饼  "
                      f"满{v['threshold']:.0f}可用  有效期至 {v['end']}"
                      f"（{v['days_left']} 天）")
            print("   详见：python picker.py coupons")
        return

    # ---------------- coupons（满减券） ----------------
    if a.cmd == "coupons":
        auth = need_auth(auth)
        c = Client(auth, workers=a.workers)
        rows = c.coupons(a.kind)
        if a.json:
            print(json.dumps({"kind": a.kind, "coupons": rows},
                             ensure_ascii=False, indent=1))
            return
        label = "书籍优惠券" if a.kind == "book" else "实物商品优惠券"
        usable = [v for v in rows if not v["expired"]]
        if not rows:
            print(f"没有{label}。")
            return
        print(f"{label}共 {len(rows)} 张，其中未过期 {len(usable)} 张\n")
        for v in rows:
            state = "❌ 已过期/已用" if v["expired"] else "✅ 可用"
            cond = f"满{v['threshold']:.0f}阅饼" if v["threshold"] else "无门槛"
            period = f"{v['start']} 至 {v['end']}" if v["start"] else v["end"]
            print(f"  {v['amount']:>5.0f} 阅饼  {cond:<12} {period}  {state}  {v['name']}")
        if a.kind == "book":
            print("\n满减券走新版订单通道（/trade/order/pay），buy 下单时自动使用；"
                  "\n要按原价购买（不下券）加 --ignore-coupon。")
        return

    # ---------------- buy（⚠️ 写操作） ----------------
    if a.cmd == "buy":
        auth = need_auth(auth)
        c = Client(auth, workers=a.workers)

        q2 = c.order_quote(a.bid)
        if not q2["ok"]:
            print("[中止] 试算页打不开（网络或凭证问题）", file=sys.stderr)
            sys.exit(1)

        title = q2["name"] or c.detail(a.bid).get("name") or f"book {a.bid}"
        print(f"=== 订单询价 === {title}")

        if c.is_owned(a.bid):
            print("\n状态        已拥有，无需购买。")
            return

        # --ignore-coupon：不下满减券，按活动价全额用代金券买
        cp = None if a.ignore_coupon else q2["coupon"]
        # 满减券要按折后价（活动价）判断门槛：服务端的 coupon 字段是「理论可用」，
        # 但活动价可能已低于门槛，此时券其实用不上，得自己再判一次。
        if cp and q2["dis_price"] < (cp.get("threshold") or 0):
            cp = None
        amount = q2["dis_price"]
        if cp:
            amount = max(q2["dis_price"] - cp["amount"], 0)
        voucher = min(amount, q2["voucher"]) if q2["voucher"] else amount
        yb_need = max(amount - q2["voucher"], 0)

        have_v = c.usable_total()[0]
        enough = have_v >= amount

        print(f"标价        {q2['price']:.0f} 阅饼")
        if q2["dis_price"] != q2["price"]:
            print(f"活动价      {q2['dis_price']:.0f} 阅饼")
        if cp:
            print(f"满减券      {cp['amount']:.0f} 阅饼"
                  f"（满{cp['threshold']:.0f}可用，code={cp['code']}）")
        print(f"折后应付    {amount:.0f} 阅饼")
        print(f"  ├ 代金券  {min(amount, have_v):.0f} 阅饼")
        print(f"  └ 阅饼    {yb_need:.0f} 阅饼")
        print(f"账上代金券  {have_v:.0f} 阅饼")

        if not enough:
            print(f"\n[中止] 余额不足：折后应付 {amount:.0f}，"
                  f"代金券只有 {have_v:.0f}，还差 {amount - have_v:.0f} 阅饼。",
                  file=sys.stderr)
            if cp:
                print("       注：满减券已算在内。若不用券，应付 "
                      f"{q2['dis_price']:.0f} 阅饼。", file=sys.stderr)
            sys.exit(1)

        if a.max_voucher is not None and amount > a.max_voucher:
            print(f"\n[中止] 需支付 {amount:.0f} > 上限 {a.max_voucher:.0f}",
                  file=sys.stderr)
            sys.exit(1)

        if not q2["token"]:
            print("\n[中止] 未取到下单令牌", file=sys.stderr)
            sys.exit(1)

        if not a.confirm:
            print(f"\n[dry-run] 仅询价，未下单。确认无误后加 --confirm 再跑一次。")
            print(f"        python picker.py buy {a.bid} --confirm")
            return

        pay_q = dict(q2)
        pay_q["bid"] = a.bid
        if not cp:
            pay_q["coupon"] = None
        print(f"\n>>> 提交订单（将扣 {amount:.0f} 代金券"
              + ("，已使用满减券" if cp else "") + "）…")
        r = c.pay_v2(pay_q)
        if r.get("code") != 0:
            print(f"[失败] {json.dumps(r, ensure_ascii=False)[:220]}", file=sys.stderr)
            sys.exit(1)
        print(f"✅ 购买成功：{r.get('msg', '') or 'ok'}")

        time.sleep(2)
        c._shelf = None
        chk = c.is_owned(a.bid)
        print(f"买后校验：{'✅ 已拥有' if chk else '❌ 仍未拥有，请检查'}")

        if a.no_shelf:
            print("（--no-shelf：跳过加书架）")
            return
        name = q2["name"] or c.detail(a.bid).get("name") or f"book {a.bid}"
        name = re.sub(r"^《|》$", "", name).strip() or name
        sr = c.shelf_add(a.bid, name, folder=a.folder)
        if sr.get("code") == 0:
            rows, _ = c._shelf_rows()
            on = a.bid in {str(x.get("book_id")) for x in rows}
            dest = f"（已归入「{a.folder}」）" if a.folder else ""
            print(f"加入云书架：{sr.get('before_total', '?')} → {len(rows)} 本  "
                  f"{'✅ 已加入' if on else '⚠️ 复核未在书架'}{dest}")
        else:
            print(f"⚠️ 加书架失败（书已购买）："
                  f"{json.dumps(sr, ensure_ascii=False)[:150]}\n"
                  f"   可手动重试：python picker.py shelf {a.bid} --name \"{name}\"")
        return

    # ---------------- shelves（只读：书架结构） ----------------
    if a.cmd == "shelves":
        auth = need_auth(auth)
        c = Client(auth, workers=a.workers)
        lay = c.shelf_layout()
        if a.json:
            print(json.dumps(lay, ensure_ascii=False, indent=1))
            return
        print(f"书架 {lay['total']} 本，{len(lay['folders'])} 个文件夹，"
              f"version {lay['version']}\n")
        for f in lay["folders"]:
            print(f"  {f['count']:>4} 本   {f['name']}")
        if lay["loose"]:
            print(f"\n未归类 {len(lay['loose'])} 本（不在任何文件夹里）")
        if a.books or a.folder is not None:
            want = a.folder
            groups: dict[str, list[dict]] = {}
            for b in lay["books"]:
                groups.setdefault(_folder_of(b), []).append(b)
            keys = ([want] if want not in (None, "") else
                    [f["name"] for f in lay["folders"]]) + ([""] if want is None else [])
            for k in keys:
                rows = groups.get(k) or []
                if not rows:
                    continue
                print(f"\n【{k or '未归类'}】{len(rows)} 本")
                for b in rows:
                    print(f"  {str(b.get('book_id')):<12} {b.get('book_name', '')}")
        return

    # ---------------- move（⚠️ 写操作） ----------------
    if a.cmd == "move":
        auth = need_auth(auth)
        c = Client(auth, workers=a.workers)
        r = c.shelf_move(a.bids, a.to, create=a.create, dry=a.dry)
        if a.json:
            print(json.dumps(r, ensure_ascii=False, indent=1))
            return
        if r.get("code") != 0:
            print(f"[失败] {r.get('msg', json.dumps(r, ensure_ascii=False)[:200])}",
                  file=sys.stderr)
            if r.get("folders"):
                print("现有文件夹：" + "、".join(r["folders"]), file=sys.stderr)
            sys.exit(1)
        for bid in r.get("missing") or []:
            print(f"⚠️  {bid} 不在书架里，跳过")
        for bid in r.get("already") or []:
            print(f"—  {bid} 已在该文件夹，跳过")
        if r.get("dry"):
            print(f"[dry] 将移动 {len(r.get('moved') or [])} 本 → {r['folder']}")
            for row in r.get("row") or []:
                print(f"   {row['book_id']}  {row['book_name']}  →  "
                      f"{row['folder_hierarchy']}")
            return
        if r.get("folder_created"):
            print(f"✅ 新建文件夹「{r['folder_created']}」")
        moved = r.get("moved") or []
        if not moved:
            print("无需改动。")
            return
        # 复核：重新读书架确认字段真的落库了
        time.sleep(1)
        lay = c.shelf_layout()
        idx = {str(b.get("book_id")): _folder_of(b) for b in lay["books"]}
        ok = [b for b in moved if idx.get(b) == a.to]
        print(f"✅ 已移动 {len(ok)}/{len(moved)} 本 → {r['folder']}")
        bad = [b for b in moved if b not in ok]
        if bad:
            print(f"⚠️  以下未确认落库：{' '.join(bad)}", file=sys.stderr)
        return

    # ---------------- mkdir / rmdir（⚠️ 写操作） ----------------
    if a.cmd in ("mkdir", "rmdir"):
        auth = need_auth(auth)
        c = Client(auth, workers=a.workers)
        if a.dry:
            lay = c.shelf_layout()
            present = a.folder in {f["name"] for f in lay["folders"]}
            if a.cmd == "mkdir":
                print("[dry] " + ("该文件夹已存在，无需建" if present
                                  else f"将新建文件夹「{a.folder}」"))
            else:
                cnt = next((f["count"] for f in lay["folders"]
                            if f["name"] == a.folder), None)
                print("[dry] " + ("没有这个文件夹" if cnt is None else
                                  f"将删除「{a.folder}」"
                                  + (f"，内有 {cnt} 本书"
                                     + ("（--force：先移出到未归类）" if a.force
                                        else "，需 --force 或先移走") if cnt else "")))
            return
        r = (c.shelf_mkdir(a.folder) if a.cmd == "mkdir" else
             c.shelf_rmdir(a.folder, force=a.force))
        if a.json:
            print(json.dumps(r, ensure_ascii=False, indent=1))
            return
        if r.get("code") not in (0, None):
            print(f"[失败] {r.get('msg', json.dumps(r, ensure_ascii=False)[:200])}",
                  file=sys.stderr)
            if r.get("books"):
                print("夹内书目：" + "、".join(
                    b["name"] for b in r["books"][:8]), file=sys.stderr)
            sys.exit(1)
        if r.get("skipped"):
            print(r["msg"])
            return
        if a.cmd == "mkdir":
            print(f"✅ 已新建文件夹「{a.folder}」")
        else:
            extra = (f"，{r['moved_out']} 本书已移出到未归类"
                     if r.get("moved_out") else "")
            print(f"✅ 已删除文件夹「{a.folder}」{extra}")
        return

    # ---------------- shelf（写操作） ----------------
    if a.cmd == "shelf":
        auth = need_auth(auth)
        c = Client(auth, workers=a.workers)
        name = a.name or c.detail(a.bid).get("name") or f"book {a.bid}"
        pre, _ = c._shelf_rows()
        print(f"当前书架 {len(pre)} 本")
        sr = c.shelf_add(a.bid, name, dry=a.dry, folder=a.folder)
        if sr.get("skipped"):
            print(f"《{name}》已在书架，无需添加")
            return
        if sr.get("dry"):
            print(f"[dry] 将写入：{json.dumps(sr['row'], ensure_ascii=False)[:200]}")
            return
        if sr.get("code") != 0:
            print(f"[失败] {json.dumps(sr, ensure_ascii=False)[:200]}", file=sys.stderr)
            sys.exit(1)
        rows, ver = c._shelf_rows()
        on = a.bid in {str(x.get("book_id")) for x in rows}
        print(f"书架 {sr.get('before_total')} → {len(rows)} 本，version {sr.get('before_version')} → {ver}")
        print(f"《{name}》{'✅ 已加入书架' if on else '❌ 复核未在书架'}")
        return

    # ---------------- info ----------------
    if a.cmd == "info":
        d = c.detail(a.bid)
        own = c.is_owned(a.bid) if auth else None
        ov = c.order_quote(a.bid) if auth else {}
        # 单本查豆瓣很便宜（1 次请求），--douban 才发，避免默认打第三方
        db = douban_by_isbn(d.get("isbn", ""), d.get("name", "")) if want_douban else {}
        if a.json:
            print(json.dumps({"detail": d, "owned": own, "order": ov,
                              "douban": db}, ensure_ascii=False, indent=1))
            return
        print(fmt_detail(d))
        if db:
            if db.get("rating") is not None:
                print(f"豆瓣   {db['rating']:.1f} 分"
                      + (f"（{db['rating_count']} 人评价）" if db.get("rating_count")
                         else "")
                      + f"   {db.get('url', '')}")
            else:
                print(f"豆瓣   —（{db.get('note', '无评分')}）")
            if db.get("title_match") is False:
                print(f"注意   {db.get('note', '')}")
        elif d.get("isbn"):
            print("豆瓣   （加 --douban 可查豆瓣评分）")
        if d["free"]:
            print("价格   免费")
        elif d["price"]:
            print(f"价格   {d['price']:.0f} 阅饼")
        elif d["per_k"]:
            print(f"价格   {d['per_k']:g} 阅饼/千字（连载中，无整本价）")
        elif d.get("status") == "连载中":
            print("价格   无整本价（连载中，按章订阅；以订单页报价为准）")
        else:
            print("价格   无（可能已下架）")
        if d["special"]:
            print("标记   特价")
        if own is True:
            print("拥有   ✅ 已拥有")
        elif own is False:
            print("拥有   ❌ 未拥有")
        else:
            print("拥有   ?（提供凭证可判断）")
        if ov.get("ok") and own is not True:
            price, dis = ov.get("price") or 0, ov.get("dis_price") or 0
            cp = ov.get("coupon") or {}
            # 活动价低于门槛时满减券用不上，不计入
            use_cp = bool(cp) and dis >= (cp.get("threshold") or 0)
            amount = max(dis - (cp.get("amount") or 0), 0) if use_cp else dis
            have = c.usable_total()[0]
            print(f"下单   标价 {price:.0f} 阅饼"
                  + (f"，活动价 {dis:.0f}" if dis != price else ""))
            if use_cp:
                print(f"       满减券 减 {cp.get('amount'):.0f}"
                      f"（满{cp.get('threshold'):.0f}，code={cp.get('code')}）"
                      f"   → 应付 {amount:.0f} 阅饼")
            gap = max(amount - have, 0)
            print(f"       代金券 {have:.0f}"
                  + (f"，还差 {gap:.0f} 阅饼  ❌ 余额不足" if gap > 0
                     else "  ✅ 券够，可 0 元买下"))
        return

    # ---------------- categories ----------------
    if a.cmd == "categories":
        cats = c.categories(a.channel)
        print(f"{CHANNELS.get(a.channel, a.channel)}频道共 {len(cats)} 个分类：\n")
        for cid, nm in cats:
            print(f"  {nm:<8} cid={cid}")
        return

    # ---------------- 求可用券额（afford/recommend/category/search 共用） ----------------
    _vtotal: list[float | None] = [None]

    def real_vouchers() -> float | None:
        """真实可用券额（用于「能否零付」判断）；拿不到返回 None。"""
        if _vtotal[0] is not None:
            return _vtotal[0]
        if not auth:
            return None
        try:
            total, _ = c.usable_total()
        except Exception:
            return None
        _vtotal[0] = total
        return total

    def resolve_limit(explicit):
        """价格筛选上限：显式 --limit 优先，否则用真实券额。"""
        if explicit is not None:
            return explicit
        total = real_vouchers()
        if total is None:
            print("⚠️  未提供凭证，无法知道你有多少券 → 默认按 100 阅饼筛选。"
                  "\n   想看「零付能买啥」，请提供凭证或显式 --limit。", file=sys.stderr)
            return 100.0
        return total if total > 0 else 100.0

    # ---------------- afford ----------------
    if a.cmd == "afford":
        limit = resolve_limit(a.limit)
        coupon = None
        ceiling = limit
        if a.coupon:
            try:
                avail = [v for v in c.usable_coupons("book") if v.get("amount")]
            except Exception:
                avail = []
            usable = [v for v in avail
                      if (v.get("threshold") or 0) <= limit + v["amount"]]
            if usable:
                coupon = max(usable, key=lambda v: (v["amount"], -v.get("threshold", 0)))
                ceiling = limit + coupon["amount"]
                print(f"满减券「{coupon['name']}」满{coupon['threshold']:.0f}减"
                      f"{coupon['amount']:.0f} → 上限提到 {ceiling:.0f} 阅饼",
                      file=sys.stderr)
            elif avail:
                b = max(avail, key=lambda v: v["amount"])
                print(f"满减券用不上：可用券 {limit:.0f} + 面额 {b['amount']:.0f} = "
                      f"{limit + b['amount']:.0f}，仍够不到门槛 {b['threshold']:.0f} 阅饼。",
                      file=sys.stderr)
            else:
                print("没有可用的书籍满减券，按原上限查。", file=sys.stderr)

        def net_price(r: dict) -> float:
            p = r.get("price") or 0
            if coupon and p and p >= (coupon.get("threshold") or 0):
                return p - coupon["amount"]
            return p

        chs = [x.strip() for x in a.channels.split(",") if x.strip()]
        pages = 999 if a.full else 3
        targets: list[tuple[str, str]] = []
        for ch in chs:
            targets += [(ch, cid) for cid, _ in c.categories(ch)]
        print(f"扫描 {len(targets)} 个分类（上限 {ceiling:.0f} 阅饼）…", file=sys.stderr)
        cands = c.cat_many(targets, status=a.status, order="download", pages=pages)
        print(f"候选 {len(cands)} 本，查价中…", file=sys.stderr)
        uniq = {x["id"]: x for x in cands}
        hits = c.filter_buyable(list(uniq.values()), ceiling,
                                top=None if a.full else a.top)
        if coupon:
            hits = [r for r in hits if net_price(r) <= limit]
        hits.sort(key=net_price)
        enrich_douban(hits)
        if a.json:
            out = {"limit": limit, "hits": hits}
            if coupon:
                out["coupon"] = coupon
                out["ceiling"] = ceiling
            print(json.dumps(out, ensure_ascii=False, indent=1))
            return
        if coupon:
            print(f"\n=== 用券后自付 ≤ {limit:.0f} 阅饼：{len(hits)} 本 ===\n")
        else:
            print(f"\n=== 未拥有 且 售价 ≤ {limit:.0f} 阅饼：{len(hits)} 本 ===\n")
        for i, r in enumerate(hits[:60], 1):
            line = fmt_book(i, r, real_vouchers(), show_intro)
            if coupon and (r.get("price") or 0) >= (coupon.get("threshold") or 0):
                line += (f"\n       券后 {net_price(r):.0f} 阅饼"
                         f"（满{coupon['threshold']:.0f}减{coupon['amount']:.0f}，buy 下单自动抵扣）")
            print(line)
        if len(hits) > 60:
            print(f"\n… 其余 {len(hits) - 60} 本省略（--json 可看全部）")
        if coupon:
            print("\n注意：这里按标价估算券后价。实际上满减券门槛比的是**活动价**，"
                  "部分书活动价已低于门槛、券用不上；\n"
                  "     准确结果以 buy / info 的试算为准（它们走新版通道，价格是实时的）。")
        if hits:
            douban_ask()
        return

    # ---------------- recommend ----------------
    if a.cmd == "recommend":
        limit = resolve_limit(a.limit)
        chs = [x.strip() for x in a.channels.split(",") if x.strip()]
        targets: list[tuple[str, str]] = []
        for ch in chs:
            targets += [(ch, cid) for cid, _ in c.categories(ch)]
        print(f"按「{ORDERS[a.sort]}」并发抓取 {len(targets)} 个分类…", file=sys.stderr)
        cands = c.cat_many(targets, status="2", order=a.sort, pages=a.per_cat)
        uniq = {x["id"]: x for x in cands}
        hits = c.filter_buyable(list(uniq.values()), limit, top=a.top)
        # 保持抓取顺序 = 热度顺序
        order_map = {x["id"]: i for i, x in enumerate(uniq.values())}
        hits.sort(key=lambda r: order_map.get(r["id"], 10**9))
        enrich_douban(hits)
        if a.json:
            print(json.dumps({"sort": a.sort, "limit": limit, "hits": hits},
                            ensure_ascii=False, indent=1))
            return
        print(f"\n=== 按「{ORDERS[a.sort]}」推荐 · 未拥有 且 ≤ {limit:.0f} 阅饼："
              f"{len(hits)} 本 ===\n")
        for i, r in enumerate(hits[:40], 1):
            print(fmt_book(i, r, real_vouchers(), show_intro))
        if len(hits) > 40:
            print(f"\n… 其余 {len(hits) - 40} 本省略")
        if hits:
            douban_ask()
        return

    # ---------------- category ----------------
    if a.cmd == "category":
        name = a.name.strip()
        hit = CATEGORY_ALIAS.get(name)
        if not hit:
            # 在所有频道里按名字找
            found = None
            for ch in ("92", "10", "68"):
                for cid, nm in c.categories(ch):
                    if nm == name or name in nm:
                        found = (ch, cid)
                        break
                if found:
                    break
            if not found:
                print(f"未找到分类「{name}」。用 `python picker.py categories` "
                      f"查看可用分类名。", file=sys.stderr)
                sys.exit(1)
            hit = found
        ch, cid = hit
        limit = resolve_limit(a.limit)
        print(f"分类「{name}」（频道 {CHANNELS.get(ch, ch)}）抓取中…", file=sys.stderr)
        cands = c.cat_pages(ch, cid, status=a.status, order=a.sort,
                            pages=a.per_cat)
        hits = c.filter_buyable(cands, limit, top=a.top)
        order_map = {x["id"]: i for i, x in enumerate(cands)}
        hits.sort(key=lambda r: order_map.get(r["id"], 10**9))
        enrich_douban(hits)
        if a.json:
            print(json.dumps({"category": name, "limit": limit, "hits": hits},
                            ensure_ascii=False, indent=1))
            return
        print(f"\n=== 「{name}」· {ORDERS[a.sort]} · 未拥有 且 ≤ {limit:.0f} 阅饼："
              f"{len(hits)} 本 ===\n")
        for i, r in enumerate(hits[:40], 1):
            print(fmt_book(i, r, real_vouchers(), show_intro))
        if not hits:
            print("  该分类下没有价格合适的未拥有书，可试 --limit 调高或 --status 0")
        else:
            douban_ask()
        return

    # ---------------- search ----------------
    if a.cmd == "search":
        limit = resolve_limit(a.limit)
        print(f"搜索「{a.keyword}」…", file=sys.stderr)
        cands = c.search(a.keyword, max_pages=a.pages)
        if not cands:
            print(f"没有找到与「{a.keyword}」相关的书。")
            return
        if a.exact:
            kw = a.keyword.lower()
            cands = [x for x in cands
                     if kw in x["name"].lower() or kw in x["author"].lower()]
        hits = c.filter_buyable(cands, limit, top=a.top)
        enrich_douban(hits)
        # 同名归组：按归一化书名聚，组内按价升序
        def norm(s):
            s = re.sub(r"[\[【(（][^\]】)）]{0,12}[\]】)）]", "", s or "")
            return re.sub(r"[\s\-—–:：,，.。、]+", "", s).lower()
        groups: dict[str, list[dict]] = {}
        for r in hits:
            groups.setdefault(norm(r["name"]), []).append(r)
        if a.json:
            print(json.dumps({"keyword": a.keyword, "limit": limit,
                              "hits": hits}, ensure_ascii=False, indent=1))
            return
        print(f"\n=== 「{a.keyword}」未拥有 且 ≤ {limit:.0f} 阅饼："
              f"{len(hits)} 本 / {len(groups)} 组 ===\n")
        i = 0
        for key, items in sorted(groups.items(),
                                 key=lambda kv: min(x["price"] for x in kv[1])):
            items.sort(key=lambda x: x["price"])
            if len(items) > 1:
                print(f"◆ 同名 {len(items)} 个版本，最低 {items[0]['price']:.0f} 阅饼")
            for r in items:
                i += 1
                print(fmt_book(i, r, real_vouchers(), show_intro))
        if not hits:
            print("  没有价格合适的未拥有书。可试 --limit 调高，或去掉 --exact。")
        else:
            douban_ask()
        return


if __name__ == "__main__":
    main()
