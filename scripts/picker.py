#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""掌阅选书助手：查余额 / 找能零付买下的书 / 按热度或分类推荐 / 按类型检索 / 下单购买。

设计要点
--------
* 查询类只读：`balance` / `coupons` / `afford` / `recommend` / `category` /
  `search` / `info` / `shelves` / `mybl` / `blsuggest` / `taoshu` 绝不动账号。
* 写操作有两类，都要显式确认：
  `buy` 扣券购买（必须 `--confirm`，否则只询价）；
  `shelf` 加书架、`move` 移书、`mkdir` / `rmdir` 建删文件夹（均有 `--dry` 预览）；
  `cartdel` 移出购物车、`blrm` 移出书单、`bldel` 删书单（默认预览，`--yes` 执行）；
  `blnew` / `bledit` / `bladd` / `blfav` 直接生效（批量加书可用 `--dry` 预览）。
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
    python picker.py taoshu                       # 淘书市当期书目：叠满减券后能买啥
    python picker.py taoshu --show-coupons        # 只看当期券面额/门槛（不查价）
    python picker.py taoshu --limit 600           # 自付上限显式指定
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
    python picker.py cart                         # 购物车列表（含下架/失效标记，只读）
    python picker.py cart --recd                  # 同时看基于购物车的推荐
    python picker.py cartdel 10007034             # ⚠️ 移出购物车（默认预览，--yes 执行）
    python picker.py mybl                         # 我的书单（我创建的，只读）
    python picker.py mybl --books                 # 连每个书单里的书一起列
    python picker.py mybl --fav                   # 我收藏的书单
    python picker.py blnew 硬科幻 --desc 十本够读一年   # ⚠️ 建书单（--qiu 求书单）
    python picker.py bledit 42379591 --name 新名   # ⚠️ 改书单名称/描述
    python picker.py bladd 42379591 10007034      # ⚠️ 往书单加书（--dry 预览）
    python picker.py blrm 42379591 10007034       # ⚠️ 移出书单（默认预览，--yes 执行）
    python picker.py bldel 42379591               # ⚠️ 删书单（默认预览，--yes 执行）
    python picker.py blfav 3264827                # ⚠️ 收藏别人的书单（--off 取消）
    python picker.py blsuggest 三体                # 书单加书联想（只读）
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
# 购物车 add 的设备参数：服务端要求请求带非空的 p1（设备指纹占位）与 p3（客户端版本号），
# 值本身任意（实测旧版本号/任意 hex 均可），缺任一参数业务层返回 53002 系统异常。
# 与 App 真实请求对齐（DeviceInfor.setURL 构建的 pc/p1..p34 全家桶里只取必需的两个）。
CART_DEVICE_PARAMS = "&p1=ffffffffffffffffffffffff&p3=18080103"

# 频道 / 筛选 / 排序的语义（实测确认）
CHANNELS = {"10": "男频", "68": "女频", "92": "出版"}
STATUS = {"0": "全部", "1": "免费", "2": "特价", "3": "完结", "4": "VIP"}
ORDERS = {"download": "热门", "score": "好评", "update": "最新"}

# ================= 淘书市活动（与 ireader_welfare/taoshushi.py 同源链路） =================
# 活动入口：书城「出版/精选」频道页顶部滚动 banner（约一月换两次期）。
# 领券由 ireader_welfare 负责；本文件只做「读」：把当期活动页里的
# 满减券（面额/门槛/product_id）与活动书目（book ids）抓出来，
# 用于「叠加淘书市券后能买哪些书」的推荐。协议细节见
# ireader_welfare/docs/掌阅逆向笔记.md 第二十一节。

H5_BASE = "https://h5.zhangyue.com"
TSS_CHANNEL_KEYS = ("ch_publish", "ch_feature")   # 滚动栏挂过的频道
TSS_KEYWORDS = ("淘书",)                          # banner 名称/活动页正文识别词


def _tss_fetch(url: str, timeout: int = 20) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": APP_UA})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read().decode("utf-8", "ignore")


def tss_banner_items(channel_key: str) -> list[tuple[str, str]]:
    """频道页滚动栏 → [(跳转url, banner名称)]（匿名）。"""
    try:
        j = json.loads(_tss_fetch(
            f"{APP_BASE}/zybk/channel/ajaxrequest?page=1&key={channel_key}&index=0"))
    except (ValueError, OSError):
        return []
    html = (j.get("blockData") or "") if isinstance(j, dict) else ""
    items = []
    for m in re.finditer(r'<li[^>]*class="slider-item[^"]*"[^>]*>', html):
        tag = m.group(0)
        u = re.search(r'data-url="([^"]+)"', tag)
        if not u:
            continue
        name = ""
        pm = re.search(r"data-point='([^']*)'", tag)
        if pm:
            try:
                name = (json.loads(pm.group(1)) or {}).get("name") or ""
            except ValueError:
                pass
        items.append((u.group(1), name))
    return items


def tss_find_activities(channel_keys=TSS_CHANNEL_KEYS) -> list[tuple[str, str]]:
    """在滚动栏里找淘书市/券活动页，返回 [(act_id, 来源)]。

    与 ireader_welfare 同款三级判定，专为换期自适应：
      ① banner 名称带「淘书」→ 直接认定
      ② 抓活动页正文确认带「淘书」→ 认定
      ③ 兜底：有券组件（amp_coupon）的 opr 活动页 → 认定
    没有运营活动页（未换期）返回空列表。
    """
    named, to_check = [], []
    seen: set[str] = set()
    for key in channel_keys:
        for url, name in tss_banner_items(key):
            m = re.match(r"https?://h5\.zhangyue\.com/opr/([A-Za-z0-9]+)\.html", url)
            if not m or m.group(1) in seen:
                continue
            seen.add(m.group(1))
            if any(kw in name for kw in TSS_KEYWORDS):
                named.append((m.group(1), f"banner「{name}」"))
            else:
                to_check.append(m.group(1))
    if named:
        return named
    for act_id in to_check:
        try:
            html = _tss_fetch(f"{H5_BASE}/opr/{act_id}.html?act_id={act_id}&launch=inside")
        except OSError:
            continue
        if any(kw in html for kw in TSS_KEYWORDS):
            named.append((act_id, "活动页正文含淘书"))
        elif "amp_coupon" in html:
            named.append((act_id, "滚动栏券活动（兜底）"))
        time.sleep(0.5)
    return named


def tss_bundle_url(act_id: str, html: str) -> str:
    """从活动页 HTML 抠出当期 bundle 地址（券与书目的 product_id 都在里面）。"""
    m = re.search(rf'src="[^"]*/opr/js/{re.escape(act_id)}\.([0-9a-f]+)\.js"', html)
    if m:
        return f"https://static-tos-front-h.zhangyuecdn.com/opr/js/{act_id}.{m.group(1)}.js"
    for m in re.finditer(r'src="([^"]*/opr/js/[a-z0-9]+\.[0-9a-f]+\.js)"', html):
        name = m.group(1).rsplit("/", 1)[-1]
        if not name.startswith("chunk-"):
            return m.group(1) if m.group(1).startswith("http") else f"https:{m.group(1)}"
    return ""


def tss_parse_coupons(bundle_js: str, html: str) -> list[dict]:
    """券列表 [{product_id, amount, quota, valid}]。

    product_id 在 bundle 的 req_params.ids（req_type:"coupon"，按组件顺序）；
    面额/门槛在 SSR 的 amp_coupon 块，两边都自上而下 → 顺序配对。
    数量对不上时以 ids 为准、面额留空（宁可少显示不错配）。
    """
    ids: list[str] = []
    for m in re.finditer(r'req_params:\{ids:\[([^\]]*)\]\},req_type:"coupon"', bundle_js):
        ids.extend(re.findall(r'"(\d+)"', m.group(1)))
    infos = []
    for b in re.split(r'(?=<div id="anchor_\d+" class="amp_coupon)', html)[1:]:
        amounts = re.findall(r"<b[^>]*>(?:<[^>]+>)*([\d.]+)", b)
        quotas = re.findall(r"<p[^>]*>(满[\d.]+阅饼[^<]*)</p>", b)
        valid = re.findall(r'class="time"[^>]*>([^<]+)<', b)
        for i, amt in enumerate(amounts):
            infos.append({"amount": float(amt),
                          "quota": quotas[i] if i < len(quotas) else "",
                          "valid": valid[0] if valid else ""})
    return [{"product_id": pid, **(infos[i] if i < len(infos) else
             {"amount": None, "quota": "", "valid": ""})}
            for i, pid in enumerate(ids)]


def tss_parse_books(bundle_js: str) -> list[str]:
    """活动书目 ids（bundle 的 req_type:"book" 组件，去重保序，约 150 本/期）。"""
    seen: set[str] = set()
    out: list[str] = []
    for m in re.finditer(r'req_params:\{cart_id:"\d+",ids:\[([^\]]*)\]\},'
                         r'req_type:"book"', bundle_js):
        for x in re.findall(r'"(\d+)"', m.group(1)):
            if x not in seen:
                seen.add(x)
                out.append(x)
    return out


def tss_load(act_id: str) -> dict:
    """当期活动全量：{act_id, coupons, book_ids, found}。"""
    html = _tss_fetch(f"{H5_BASE}/opr/{act_id}.html?act_id={act_id}&launch=inside")
    bundle = ""
    bu = tss_bundle_url(act_id, html)
    if bu:
        bundle = _tss_fetch(bu)
    return {
        "act_id": act_id,
        "coupons": tss_parse_coupons(bundle, html) if bundle else [],
        "book_ids": tss_parse_books(bundle) if bundle else [],
    }


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


def _auth_field(auth: str, name: str) -> str:
    """从 "usr=iXXX&zysid=YYY" 凭证串里取单个字段。"""
    for part in auth.split("&"):
        k, _, v = part.partition("=")
        if k.strip() == name:
            return v.strip()
    return ""


_CART_KEY: list = []


def _cart_private_key():
    """客户端签名用的 RSA 私钥（与登录同族，服务端只认第 4 把）。

    购物车（`/zyuc/api/cart/cart`）与书单（`/zyus/booklist/*`）共用这把。
    """
    if _CART_KEY:
        return _CART_KEY[0]
    try:
        import base64
        from cryptography.hazmat.primitives.serialization import load_der_private_key
    except ImportError:
        raise RuntimeError(
            "该接口需要 cryptography 库：python -m pip install cryptography")
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                        "native_keys.json")
    with open(path, "r", encoding="utf-8") as f:
        raw = json.load(f)
    key = load_der_private_key(base64.b64decode(raw[3]["der_b64"]), password=None)
    _CART_KEY.append(key)
    return key


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

    # ---------- 购物车（新版，zyuc/api/cart/cart）----------

    def _cart_signed_url(self, act: str, extra: str = "") -> str:
        """购物车接口 URL：sign = SHA1withRSA("act=..&timestamp=..&usr=.."，客户端私钥第 4 把)。

        实测签名串固定只含 act/timestamp/usr 三个参数（多一个都返回 53001 签名错误）；
        bookId/books 等业务参数拼在签名之后，不参与签名。需要 cryptography 库。
        另拼 CART_DEVICE_PARAMS：add 动作服务端要求 p1/p3 非空，缺了返回 53002。
        """
        from cryptography.hazmat.primitives import hashes
        from cryptography.hazmat.primitives.asymmetric import padding
        import base64
        key = _cart_private_key()
        ts = str(int(time.time() * 1000))
        usr = _auth_field(self.auth, "usr")
        msg = f"act={act}&timestamp={ts}&usr={usr}"
        sign = base64.b64encode(
            key.sign(msg.encode(), padding.PKCS1v15(), hashes.SHA1())).decode()
        dev = CART_DEVICE_PARAMS if act == "add" else ""
        q = (f"act={act}&timestamp={ts}&usr={usr}"
             f"&sign={urllib.parse.quote(sign, safe='')}{extra}"
             f"&{self.auth}&pluginVersion=34{dev}")
        return f"{APP_BASE}/zyuc/api/cart/cart?{q}"

    def cart_request(self, act: str, extra: str = "") -> dict:
        """调购物车接口并解析 JSON。code!=0 时抛 RuntimeError 带原始 code/msg。"""
        t = _fetch(self._cart_signed_url(act, extra), APP_UA)
        try:
            j = json.loads(t)
        except ValueError:
            raise RuntimeError(f"购物车接口返回异常：{t[:200] or '(空)'}")
        if j.get("code") != 0:
            raise RuntimeError(f"购物车接口 code={j.get('code')} msg={j.get('msg')}")
        return j.get("body") or {}

    def cart_list(self) -> dict:
        """购物车列表：分组（type/typeName/couponInfo）+ 书目（BookInCart）。

        书目字段：bookId/bookName/author/price/priceDesc/state/selectStatus/
        buyDesc/isDiscount/diff/voucherDesc/picUrl/url。
        state：0=正常 1=免费 2=下架 3=失效（下架/失效不支持结算）。
        """
        body = self.cart_request("list")
        groups = []
        for g in body.get("books", []):
            groups.append({
                "type": g.get("type"),
                "type_name": g.get("typeName", ""),
                "coupon_info": g.get("couponInfo") or {},
                "books": g.get("bookList", []),
            })
        return {"groups": groups, "limit": body.get("booksLimit"),
                "rule_url": body.get("ruleUrl", "")}

    def cart_count(self) -> int | None:
        """旧通道购物车数量（app.php?ca=Cart.Num）。与新版购物车是两套库。"""
        t = _fetch(f"{APP_BASE}/zybook3/app/app.php?ca=Cart.Num&{self.auth}", APP_UA)
        try:
            return int(json.loads(t).get("num"))
        except (ValueError, TypeError):
            return None

    def cart_recd(self) -> list[dict]:
        """基于购物车的推荐书目（bookId/bookName/picUrl）。"""
        body = self.cart_request("recd")
        return body.get("list", [])

    def cart_del(self, bids: list[str], category: int = 1) -> dict:
        """从购物车删除书目。books=[{"bookId":..,"bookCategory":..}] JSON，不参与签名。"""
        books = json.dumps([{"bookId": int(b), "bookCategory": category} for b in bids],
                           separators=(",", ":"))
        return self.cart_request("del", f"&books={urllib.parse.quote(books, safe='')}")

    def cart_add(self, bid: str, category: int = 1) -> dict:
        """加入购物车（act=add&bookId=..&bookCategory=..）。

        服务端要求请求携带非空的 p1（设备指纹）与 p3（客户端版本号），
        由 CART_DEVICE_PARAMS 提供；缺了返回 53002 系统异常（已实测破案）。
        幂等性差：重复加同一本返回 53002，调用前先查 cart_list。
        """
        return self.cart_request("add", f"&bookId={bid}&bookCategory={category}")

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

    # ---------- 作者主页 ----------

    _RE_AUTHOR_ROLE = re.compile(
        r'<span class="it red" data-js="author-page" data-un="([^"]+)"'
        r' data-url="([^"]+)">([^<]+)</span>')

    def author_page(self, bid: str) -> dict:
        """按任一作品抓作者主页：作者简介 + 名下全部作品。

        数据源是掌阅作者主页（书籍详情页作者区带 data-un，指向
        /zyuc/homepage/），不是 App 搜索里的作者卡片；调用链：
        书籍页拿 data-un -> 主页拿简介与作品数 -> 全部作品分页。
        名下作品不区分[著]/[译]挂名，也不区分出版/网文。
        """
        book_html = _fetch(f"{APP_BASE}/zybook3/u/p/book.php?key=17B{bid}&rgt=", APP_UA)
        roles = [{"un": un, "display": name.strip(), "url": url}
                 for un, url, name in self._RE_AUTHOR_ROLE.findall(book_html)]
        if not roles:
            return {"ok": False, "msg": "该书详情页没有作者主页入口",
                    "source_book": str(bid)}
        role = next((r for r in roles if "[著]" in r["display"]), roles[0])
        un = role["un"]
        source_name = ""
        mn = re.search(r"<dt>([^<]{1,80})</dt>", book_html)
        source_name = mn.group(1).strip() if mn else f"book {bid}"

        home = _fetch(f"{APP_BASE}/zyuc/homepage/home/index?pk=17B{bid}"
                      f"&visitorName={un}&rgt=", APP_UA)
        mn = re.search(r'data-nick="([^"]*)"\s*data-utag="([^"]*)"', home)
        name = mn.group(1) if mn else ""
        utag = mn.group(2) if mn else ""
        strip = lambda s: re.sub(r"\s+", " ", re.sub(r"<[^>]+>", "", s or "")).strip()
        mi = re.search(r'<div class="user_brif[^"]*"[^>]*>(.*?)</div>', home, re.S)
        mt = re.search(r'data-js="allmybook"[^>]*>\s*([^<]+?)\s*<', home)
        mw = re.search(r'<em class="sub_title">([^<]*)</em>', home)

        booklist_url = (f"{APP_BASE}/zyuc/homepage/booklist"
                        f"?group=author&visitorName={un}&rgt=")
        bl = _fetch(booklist_url, APP_UA)
        mp = re.search(r'totalpage="(\d+)"', bl)
        pages = int(mp.group(1)) if mp else 1
        works, seen = [], set()
        for page in range(1, pages + 1):
            if page == 1:
                html = bl
            else:
                raw = _fetch(f"{booklist_url}&currentPage={page}", APP_UA)
                try:
                    html = (json.loads(raw) or {}).get("html") or ""
                except ValueError:
                    break
            for wbid, wname in re.findall(r'data-bid="(\d+)"\s+data-bname="([^"]*)"', html):
                if wbid not in seen:
                    seen.add(wbid)
                    works.append({"bid": wbid, "name": wname})
        return {
            "ok": True, "un": un, "role": role["display"], "roles": roles,
            "source_book": str(bid), "source_book_name": source_name,
            "name": name, "utag": utag,
            "intro": strip(mi.group(1)) if mi else "",
            "total_books": len(works),
            "all_books_label": mt.group(1).strip() if mt else "",
            "total_words": mw.group(1).strip() if mw else "",
            "works": works,
        }

    # ---------- 书单搜索与详情 ----------

    def search_booklist(self, keyword: str, page: int = 1,
                        page_size: int = 3, paginated: bool = False) -> dict:
        """书城搜索结果里的「书单」页签 + 作者卡 + 相关搜索。

        数据源：/zybook3/u/p/api.php?Act=searchMultiple（App 搜索多栏接口）。
        两种模式（对应 App 的两种请求）：
          paginated=False（默认）：首屏请求（不带 type），返回第一屏书单
            （App 固定 pageSize=3）+ 作者卡 + 同页书籍 + 相关搜索。
          paginated=True：书单 tab「加载更多」请求（App 原生拼法，逆向自
            classes6.dex 的 Lih/b;->j）：type=bkList&pageSize=N&currentPage=M，
            只返回书单列表，book/relatedSearch 节点不返回（App 同样如此）。
        翻页实测：未登录（usr/zysid 空）可用；pageSize 100 实测有效；
        currentPage 超界不报错、返回空 datas，page.currentPage 被服务端
        纠正为最后实际页。
        """
        def _req(extra: dict) -> dict:
            q = {"Act": "searchMultiple", "keyWord": keyword,
                 "usr": _auth_field(self.auth, "usr") or "",
                 "zysid": _auth_field(self.auth, "zysid") or "",
                 "p29": "zye5b814", "p2": "104583", "p3": "18070403",
                 "p4": "501603", "p33": "com.chaozh.iReaderFree"}
            q.update(extra)
            raw = _fetch(f"{APP_BASE}/zybook3/u/p/api.php"
                         f"?{urllib.parse.urlencode(q)}", APP_UA)
            try:
                return (json.loads(raw).get("body") or {})
            except ValueError:
                return {}

        def _parse_bl(d: dict) -> dict:
            return {
                "id": d.get("id"), "name": d.get("name"),
                "description": d.get("description"),
                "tags": d.get("tags") or [], "count": d.get("count"),
                "fav_num": d.get("fav_num"), "like": d.get("like"),
                "user_nick": d.get("user_nick"), "fullUrl": d.get("fullUrl"),
            }

        out = {"ok": False, "keyword": keyword, "booklists": [],
               "author_card": None, "books": [], "related": []}

        if paginated:
            bl = _req({"type": "bkList",
                       "pageSize": max(1, min(page_size, 100)),
                       "currentPage": max(1, page)}).get("bkList") or {}
            out["ok"] = bool(bl)
            out["mode"] = f"page:{page}"
            out["bk_page"] = bl.get("page") or {}
            for d in bl.get("datas") or []:
                out["booklists"].append(_parse_bl(d))
            return out

        body = _req({})
        out["ok"] = True
        bl = body.get("bkList") or {}
        out["bk_page"] = bl.get("page") or {}
        for d in bl.get("datas") or []:
            out["booklists"].append(_parse_bl(d))
        book = body.get("book") or {}
        if isinstance(book, str):
            try:
                book = json.loads(book)
            except ValueError:
                book = {}
        for d in book.get("datas") or []:
            info = d.get("data_info") or {}
            if str(d.get("data_type")) == "1":
                out["author_card"] = {
                    "authorName": info.get("authorName"),
                    "synopsis": info.get("synopsis"),
                    "usr": info.get("usr"),
                    "fullUrl": d.get("fullUrl"),
                }
            else:
                out["books"].append(self._parse_book_entry(d))
        rs = body.get("relatedSearch") or {}
        out["related"] = rs.get("datas") if isinstance(rs, dict) else (rs if isinstance(rs, list) else [])
        return out

    @staticmethod
    def _parse_book_entry(d: dict) -> dict:
        """searchMultiple 的书籍条目（data_type=0）→ 统一字段。"""
        info = d.get("data_info") or {}
        cats = info.get("leafCategoryName") or []
        return {
            "bid": info.get("bookId"),
            "name": info.get("displayBookName") or info.get("bookName"),
            "author": info.get("bookAuthor"),
            "rating": info.get("bookRating"),
            "tag": info.get("tag"),
            "category": cats[0] if cats else "",
            "complete": info.get("completeState"),
            "fullUrl": d.get("fullUrl"),
        }

    def search_booklist_all(self, keyword: str, page_size: int = 50,
                            max_records: int = 200) -> dict:
        """书单搜索自动翻页：按 type=bkList 模式逐页抓取并去重聚合。

        page_size 默认 50（实测可用，一次能覆盖大多数关键词的全部结果），
        命中 max_records 上限或没有新 id 时停止。author_card/books/related
        在该模式下接口不返回，恒为空。
        """
        seen, all_bls = set(), []
        pages_meta: dict = {}
        page, total = 1, 0
        while True:
            r = self.search_booklist(keyword, page=page, page_size=page_size,
                                     paginated=True)
            if not r.get("ok"):
                break
            pages_meta = r.get("bk_page") or {}
            total = int(pages_meta.get("totalRecord") or 0)
            new = 0
            for b in r.get("booklists") or []:
                if b.get("id") not in seen:
                    seen.add(b.get("id"))
                    all_bls.append(b)
                    new += 1
            cur = int(pages_meta.get("currentPage") or 0)
            total_pg = int(pages_meta.get("totalPage") or 0)
            if (not new or len(all_bls) >= max_records
                    or len(all_bls) >= total or cur >= total_pg):
                break
            time.sleep(self.delay)
            page = cur + 1
        return {
            "ok": True, "keyword": keyword, "mode": "all",
            "booklists": all_bls, "bk_page": pages_meta,
            "fetched": len(all_bls), "total": total,
            "author_card": None, "books": [], "related": [],
        }

    def search_book(self, keyword: str, page: int = 1,
                    page_size: int = 20) -> dict:
        """书城搜索结果「书籍」页签（searchMultiple 的 type=book 模式）。

        逆向自 classes6.dex 的 Lih/b;->n，App「加载更多」拼法：
        type=book&pageSize=N&currentPage=M&filterAuthor=1&suggestType=S。
        filterAuthor=1 会把作者卡（data_type=1）滤掉，只返回书籍条目；
        body 只返回 book 节点（含自身 page 元信息），无书单/相关搜索。
        实测边界与书单 tab 一致：未登录可用、pageSize 100 有效、
        currentPage 超界返回空 datas。
        """
        q = {"Act": "searchMultiple", "keyWord": keyword,
             "usr": _auth_field(self.auth, "usr") or "",
             "zysid": _auth_field(self.auth, "zysid") or "",
             "p29": "zye5b814", "p2": "104583", "p3": "18070403",
             "p4": "501603", "p33": "com.chaozh.iReaderFree",
             "type": "book", "pageSize": max(1, min(page_size, 100)),
             "currentPage": max(1, page), "filterAuthor": 1,
             "suggestType": 0}
        raw = _fetch(f"{APP_BASE}/zybook3/u/p/api.php"
                     f"?{urllib.parse.urlencode(q)}", APP_UA)
        book = {}
        try:
            book = (json.loads(raw).get("body") or {}).get("book") or {}
        except ValueError:
            pass
        if isinstance(book, str):
            try:
                book = json.loads(book)
            except ValueError:
                book = {}
        out = {"ok": bool(book), "keyword": keyword,
               "mode": f"page:{page}", "book_page": book.get("page") or {},
               "books": []}
        for d in book.get("datas") or []:
            out["books"].append(self._parse_book_entry(d))
        return out

    def search_book_all(self, keyword: str, page_size: int = 50,
                        max_records: int = 200) -> dict:
        """书籍搜索自动翻页：按 type=book 模式逐页抓取并去重聚合。

        page_size 默认 50，命中 max_records 上限、没有新 id 或抓满
        totalRecord 时停止。作者卡在该模式下不返回（filterAuthor=1），
        要作者卡用 blsearch 默认模式或 author 命令。
        """
        seen, all_books = set(), []
        pages_meta: dict = {}
        page, total = 1, 0
        while True:
            r = self.search_book(keyword, page=page, page_size=page_size)
            if not r.get("ok"):
                break
            pages_meta = r.get("book_page") or {}
            total = int(pages_meta.get("totalRecord") or 0)
            new = 0
            for b in r.get("books") or []:
                if b.get("bid") not in seen:
                    seen.add(b.get("bid"))
                    all_books.append(b)
                    new += 1
            cur = int(pages_meta.get("currentPage") or 0)
            total_pg = int(pages_meta.get("totalPage") or 0)
            if (not new or len(all_books) >= max_records
                    or len(all_books) >= total or cur >= total_pg):
                break
            time.sleep(self.delay)
            page = cur + 1
        return {
            "ok": True, "keyword": keyword, "mode": "all",
            "books": all_books, "book_page": pages_meta,
            "fetched": len(all_books), "total": total,
        }

    def booklist_detail(self, blid: str) -> dict:
        """书单详情：书单内书列表（H5 页，每页 5 本；更多书的翻页接口未公开）。"""
        q = urllib.parse.urlencode({
            "ca": "Booklist.Detail", "id": blid, "key": f"4B552_{blid}",
            "pk": "CLI_SEARCH",
            "usr": _auth_field(self.auth, "usr") or "",
            "zysid": _auth_field(self.auth, "zysid") or "",
            "p29": "zye5b814", "p2": "104583", "p3": "18070403",
            "p4": "501603", "p33": "com.chaozh.iReaderFree",
        })
        t = _fetch(f"{APP_BASE}/zybook3/app/app.php?{q}", APP_UA)
        out = {"ok": bool(t.strip()), "id": str(blid), "books": [],
               "like": None, "title": "", "description": ""}
        m = re.search(r"var _likeNumber = (\d+)", t)
        if m:
            out["like"] = int(m.group(1))
        mt = re.search(r"<h1[^>]*>([^<]{2,50})</h1>", t)
        if mt:
            out["title"] = mt.group(1).strip()
        md = re.search(r'class="user_brif[^"]*"[^>]*>(.*?)</div>', t, re.S)
        if md:
            out["description"] = re.sub(
                r"\s+", " ", re.sub(r"<[^>]+>", "", md.group(1))).strip()
        for mm in re.finditer(
                r"openBookPage\('(\d+)'[^>]*>(.*?)<dt[^>]*>([^<]+)</dt>\s*"
                r'<dd class="author">([^<]*)</dd>(.*?)</dl>', t, re.S):
            reason = ""
            mr = re.search(r"推荐理由：</span>\s*(.*?)</p>", mm.group(5), re.S)
            if mr:
                reason = re.sub(r"<[^>]+>", "", mr.group(1)).strip()
            out["books"].append({"bid": mm.group(1), "name": mm.group(3).strip(),
                                 "author": mm.group(4).strip(), "reason": reason})
        mpage = re.search(r'totalPage="(\d+)"', t)
        if mpage:
            out["total_pages"] = int(mpage.group(1))
        return out

    # ---------- 我的书单（原生 /zyus/booklist/*，写操作）----------

    def _bl_request(self, path: str, params: dict, signed: list[str] | None = None,
                    post: bool = False) -> dict:
        """调 `/zyus/booklist/*` 并解析 JSON；code!=0 抛 RuntimeError（带原始 code/msg）。

        GET 接口（`myList`/`info`）参数放 query；POST 接口（`add`/`update`/`operate`/
        `book/operate`）**全部参数放 body**，`zysid` 单独留在 query。两种情况下
        `sign` 都随其它参数一起走，`signed` 决定签哪些 key（`None` = 签全部）。
        """
        from cryptography.hazmat.primitives import hashes
        from cryptography.hazmat.primitives.asymmetric import padding
        import base64
        key = _cart_private_key()
        p = {k: v for k, v in params.items() if v is not None}
        p["timestamp"] = str(int(time.time() * 1000))
        p["usr"] = _auth_field(self.auth, "usr")
        keys = sorted(p) if signed is None else sorted(signed)
        msg = "&".join(f"{k}={p[k]}" for k in keys if p.get(k) not in (None, ""))
        p["sign"] = base64.b64encode(
            key.sign(msg.encode(), padding.PKCS1v15(), hashes.SHA1())).decode()
        zysid = _auth_field(self.auth, "zysid")
        base = f"{APP_BASE}{path}?zysid={urllib.parse.quote(zysid, safe='')}"
        if post:
            t = _post(base, urllib.parse.urlencode(p).encode(),
                      "application/x-www-form-urlencoded", APP_UA)
        else:
            t = _fetch(f"{base}&{urllib.parse.urlencode(p)}", APP_UA)
        try:
            j = json.loads(t)
        except ValueError:
            raise RuntimeError(f"书单接口返回异常：{t[:200] or '(空)'}")
        if j.get("code") != 0:
            raise RuntimeError(f"书单接口 code={j.get('code')} msg={j.get('msg')}")
        return j.get("body") or {}

    def my_booklists(self, list_type: str = "1", size: int = 20) -> dict:
        """我的书单列表（`/zyus/booklist/myList`，自动翻页）。

        `list_type`：`1`=我创建的书单、`2`=我收藏的书单。`start` 是**页码**（从 1 起，
        不是 offset），服务端每页最多 20 条。返回 `{total, lists[]}`，每条含
        id/name/description/tags/count/like/fav_num/create_time/update_time/
        is_public/type/status/owner/user_nick/books[]（列表里带前若干本书）。
        """
        size = max(1, min(int(size), 20))
        lists, total, page = [], None, 1
        while True:
            b = self._bl_request("/zyus/booklist/myList",
                                 {"listType": list_type, "start": str(page),
                                  "size": str(size)},
                                 signed=["timestamp", "usr"])
            total = b.get("total", total)
            batch = b.get("book_lists") or []
            lists += batch
            if len(batch) < size or (total is not None and len(lists) >= int(total)):
                break
            page += 1
            if page > 50:      # 保险丝，防止 total 异常时死循环
                break
            time.sleep(self.delay)
        return {"total": total if total is not None else len(lists),
                "list_type": str(list_type), "lists": lists}

    def booklist_info(self, blid: str, page: int = 1, is_edit: bool = False) -> dict:
        """书单详情（原生接口，自动翻页取全书目）。

        比 H5 的 `booklist_detail` 强：一次能拿到书单元信息（名称/描述/标签/
        收藏数/是否可补书）+ 全部书目（含每本书的推荐理由 `book_desc`）。
        服务端每页 10 本；`is_edit=True` 时会带编辑态字段（`canAdd` 等）。

        **书单处于审核态（`status=check`，常见于刚建单或刚加过书）时，本接口
        一律返回 `53002 获取数据错误`**。这时抛出的 RuntimeError 里会带
        `under_review=True` 标记，调用方据此提示「审核中」而不是报故障。
        """
        meta: dict = {}
        books: list[dict] = []
        last: dict = {}
        for pg in range(1, 41):
            try:
                b = self._bl_request("/zyus/booklist/info",
                                     {"bookListId": str(blid),
                                      "isEdit": "1" if is_edit else "0",
                                      "page": str(pg)})
            except RuntimeError as e:
                if "53002" in str(e) and pg == 1:
                    raise RuntimeError(
                        f"书单 {blid} 读不到（多为审核中，稍后重试）：{e}"
                    ) from e
                break       # 后续页失败就当翻到头
            last = b
            meta = meta or (b.get("info") or {})
            batch = b.get("books") or []
            books += batch
            cnt = meta.get("count")
            if not batch or (cnt is not None and len(books) >= int(cnt)):
                break
            time.sleep(self.delay)
        out = dict(meta)
        out["id"] = str(blid)
        out["books"] = books
        out["user"] = last.get("user") or {}
        return out

    def booklist_create(self, name: str, desc: str, book_type: str = "1") -> dict:
        """创建书单（`/zyus/booklist/add`，⚠️ 写操作）。

        `book_type`：`1`=晒书单（默认）、`2`=求书单。服务端要求 `name` 1~40 字、
        `desc` 1~200 字（超出/含敏感词统一返回 `31215 文字内容违规`）。

        **`addBooks` 只能传空数组**：服务端会拿新建书单的空 id 去做 `int()` 转换，
        任何非空结构都报 `invalid literal for int() with base 10: ''`。想建单就带书，
        只能先建空单再逐本调 `booklist_add_book()`（CLI 的 `blnew --add` 即如此）。
        """
        payload = {
            "bookType": str(book_type),
            "name": name,
            "desc": desc,
            "addBooks": "[]",
        }
        b = self._bl_request("/zyus/booklist/add", payload, post=True)
        return {"id": str(b.get("id", "")), "name": name}

    def booklist_update(self, blid: str, name: str, desc: str,
                        add_books: list[dict] | None = None,
                        update_books: list[dict] | None = None) -> dict:
        """改书单名称/描述（`/zyus/booklist/update`，⚠️ 写操作）。

        签名只含 `bookListId`/`name`/`desc`/`timestamp`/`usr`；两个 JSON 字段
        （`addBooks` 补书、`updateBooks` 改推荐理由）随 body 一起发、**不参与签名**。
        两者传空列表也合法（服务端不会因此清空书目）。
        """
        params = {"bookListId": str(blid), "name": name, "desc": desc,
                  "addBooks": json.dumps(add_books or [], ensure_ascii=False),
                  "updateBooks": json.dumps(update_books or [], ensure_ascii=False)}
        self._bl_request("/zyus/booklist/update", params,
                         signed=["bookListId", "name", "desc", "timestamp", "usr"],
                         post=True)
        return {"id": str(blid), "name": name}

    def booklist_delete(self, blid: str) -> dict:
        """删除自己的书单（`/zyus/booklist/operate` operate=delete，⚠️ 写操作）。"""
        self._bl_request("/zyus/booklist/operate",
                         {"operate": "delete", "bookListId": str(blid)},
                         signed=["operate", "bookListId", "timestamp", "usr"],
                         post=True)
        return {"id": str(blid), "deleted": True}

    def booklist_favorite(self, blid: str, add: bool = True) -> dict:
        """收藏 / 取消收藏书单（operate=addFavorite / deleteFavorite，⚠️ 写操作）。"""
        act = "addFavorite" if add else "deleteFavorite"
        self._bl_request("/zyus/booklist/operate",
                         {"operate": act, "bookListId": str(blid)},
                         signed=["operate", "bookListId", "timestamp", "usr"],
                         post=True)
        return {"id": str(blid), "favorite": bool(add)}

    def booklist_remove_book(self, blid: str, bids: list[str]) -> dict:
        """把书移出书单（`/zyus/booklist/book/operate` operate=delete，⚠️ 写操作）。

        注意 `operate=add` 走不通（服务端返回 53002），加书只能用 `booklist_add_book`。
        """
        done = []
        for bid in bids:
            self._bl_request("/zyus/booklist/book/operate",
                             {"operate": "delete", "bookListId": str(blid),
                              "bookId": str(bid)},
                             signed=["operate", "bookListId", "bookId",
                                     "timestamp", "usr"],
                             post=True)
            done.append(str(bid))
            time.sleep(self.delay)
        return {"id": str(blid), "removed": done}

    def booklist_add_book(self, blid: str, bid: str, name: str = "",
                          author: str = "", desc: str = "", pic: str = "",
                          is_isbn: bool = False) -> dict:
        """往书单加一本书（H5 `Booklist.AddOneBook`，⚠️ 写操作）。

        原生 `book/operate` 的 `add` 动作服务端不认（53002），加书实际走 H5 这条，
        与 App 内置编辑页同源。同一本书重复加返回 `31206 该图书已存在`。
        `bid` 传数字 book_id 或 `ISBN:xxx`（`is_isbn=True` 时 `type=0`）。
        """
        body = {
            "id": str(blid), "bid": str(bid),
            "type": "0" if is_isbn else "1",
            "name": name, "author": author, "pic": pic, "desc": desc,
            "timestamp": str(int(time.time() * 1000)),
        }
        url = (f"{APP_BASE}/zybook3/app/app.php"
               f"?ca=Booklist.AddOneBook&{urllib.parse.urlencode(self._pc_auth_params())}")
        raw = _post(url, urllib.parse.urlencode(body).encode(),
                    "application/x-www-form-urlencoded", APP_UA)
        try:
            j = json.loads(raw)
        except ValueError:
            raise RuntimeError(f"加书接口返回异常：{raw[:200] or '(空)'}")
        if j.get("code") != 0:
            raise RuntimeError(f"加书接口 code={j.get('code')} msg={j.get('msg')}")
        return {"id": str(blid), "bid": str(bid), "added": True}

    def booklist_suggest(self, keyword: str, blid: str = "0") -> list[dict]:
        """书单加书时的联想搜索（H5 `Booklist.Suggest`，只读）。

        返回 `[{id, type, name, author, pic}]`；`type=1` 是掌阅在售书（`id` 为
        数字 book_id），`type=0` 是豆瓣 ISBN 书（`id` 形如 `ISBN:9787...`）。
        """
        q = urllib.parse.urlencode({"ca": "Booklist.Suggest", "keyword": keyword,
                                    "id": str(blid),
                                    **self._pc_auth_params()})
        t = _fetch(f"{APP_BASE}/zybook3/app/app.php?{q}", APP_UA)
        try:
            j = json.loads(t)
        except ValueError:
            return []
        return j if isinstance(j, list) else []

    def _pc_auth_params(self) -> dict:
        """H5 接口通用参数（页面参数 + 凭证）。"""
        return {"usr": _auth_field(self.auth, "usr"),
                "zysid": _auth_field(self.auth, "zysid"),
                "p29": "zye5b814", "p2": "104583", "p3": "18070403",
                "p4": "501603", "p33": "com.chaozh.iReaderFree"}

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


# 买完自动归夹的判定口径。状态/评价类文件夹不是按题材归类，不作为候选。
AUTO_FOLDER_STATUS_WORDS = (
    "已阅", "已读", "未读", "在读", "待读", "想读", "读完", "垃圾", "踩雷",
    "本地导入", "导入", "临时", "待整理", "其他", "收藏", "书架",
)
AUTO_FOLDER_MIN_SCORE = 80
AUTO_FOLDER_MIN_LEAD = 20


def _book_series(name: str) -> str:
    """书名里的系列前缀：去掉平台方括号后缀后，按常见分隔符取第一段。"""
    s = re.sub(r"[\[(（【].*?[\])）】]", "", name or "").strip()
    return re.split(r"[·:：\-—\s(（]", s)[0].strip()


def choose_folder(book: dict, layout: dict) -> dict:
    """为已购书挑一个最合适的自建文件夹；没有明确合适的返回 folder=""。

    候选只取书架里存在节点的自建文件夹（shelf_layout 的 folders 中 id 非空），
    不新建文件夹。信号取最高分，须 >= AUTO_FOLDER_MIN_SCORE 且领先第二名
    >= AUTO_FOLDER_MIN_LEAD；分数并列视为不确定，一律不移动。
      100  文件夹名出现在书名中，或文件夹名与作者相同
       80  该文件夹里已有 >= 2 本书与目标书共享系列前缀
    """
    name = book.get("name") or ""
    author = (book.get("author") or "").strip()
    series = _book_series(name)
    folders = [f["name"] for f in (layout.get("folders") or [])
               if f.get("name") and f.get("id")]
    books = layout.get("books") or []
    if not folders:
        return {"folder": "", "reason": "书架上没有自建文件夹",
                "score": 0, "candidates": []}

    scores: list[dict] = []
    for folder in folders:
        if any(w in folder for w in AUTO_FOLDER_STATUS_WORDS):
            continue
        score, why = 0, ""
        if len(folder) >= 2 and folder in name:
            score, why = 100, f"书名含「{folder}」"
        elif author and folder == author:
            score, why = 100, f"文件夹名与作者「{author}」相同"
        elif len(series) >= 2:
            same = [b for b in books
                    if _folder_of(b) == folder
                    and _book_series(b.get("book_name") or "") == series]
            if len(same) >= 2:
                score, why = 80, f"夹内已有 {len(same)} 本同系列书（{series}）"
        if score:
            scores.append({"folder": folder, "score": score, "reason": why})

    if not scores:
        return {"folder": "", "reason": "没有明确合适的文件夹",
                "score": 0, "candidates": []}
    scores.sort(key=lambda x: (-x["score"], x["folder"]))
    best = scores[0]
    second = scores[1]["score"] if len(scores) > 1 else 0
    if best["score"] < AUTO_FOLDER_MIN_SCORE or best["score"] - second < AUTO_FOLDER_MIN_LEAD:
        return {"folder": "", "reason": "匹配不够明确，保持未归类",
                "score": best["score"], "candidates": scores}
    return {"folder": best["folder"], "reason": best["reason"],
            "score": best["score"], "candidates": scores}


def auto_folder_decision(client, bid: str, name: str) -> dict:
    """只读地取书架结构与书目，交给 choose_folder；异常时降级为不移动。"""
    try:
        layout = client.shelf_layout()
        detail = client.detail(bid)
        return choose_folder({"name": name or detail.get("name", ""),
                              "author": detail.get("author", "")}, layout)
    except Exception as exc:
        return {"folder": "", "reason": f"读取书架或书目失败，跳过自动归夹（{exc}）",
                "score": 0, "candidates": []}


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


def _split_add_spec(spec: str) -> tuple[str, str]:
    """拆 `blnew --add` 的 `BID[:理由]` 参数。

    `ISBN:` 自带冒号，不能直接 `partition(":")`——否则 `ISBN:9787…:理由` 会被
    切成 `ISBN` + `9787…:理由`。ISBN 条目跳过前 5 个字符再找分隔冒号。
    """
    s = spec.strip()
    start = 5 if s.upper().startswith("ISBN:") else 0
    i = s.find(":", start)
    if i < 0:
        return s, ""
    return s[:i], s[i + 1:]


def _bl_book_key(bid: str) -> str:
    """把书单里的书目 id 归一化成可比较的 key。

    数字 book_id 原样返回；`ISBN:xxx` 与 `xxx` 都归成 `xxx`——服务端在
    `booklist_info` 的 books[].id 里会把 ISBN 条目的 `ISBN:` 前缀去掉，
    直接按原始字符串比对会漏配。
    """
    s = str(bid).strip()
    return s[5:] if s.upper().startswith("ISBN:") else s


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

    p = sub.add_parser("taoshu", help="淘书市当期书目：叠加满减券后能买的书",
                       parents=[_common])
    p.add_argument("--limit", type=float, default=None,
                   help="自付上限（默认=可用代金券总额）")
    p.add_argument("--act", default="", help="指定活动 act_id（默认自动找滚动栏当期）")
    p.add_argument("--status", default="2", help="0全部/1免费/2特价/3完结/4VIP")
    p.add_argument("--top", type=int, default=200,
                   help="最多查价多少本（默认 200，活动书目约 150 本）")
    p.add_argument("--show-coupons", action="store_true", default=argparse.SUPPRESS,
                   help="只列当期券面额与门槛，不查价推荐")

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

    p = sub.add_parser("author", help="按任一作品查作者主页：简介 + 名下全部作品",
                       parents=[_common])
    p.add_argument("bid", help="该作者的任一 book_id")

    p = sub.add_parser("blsearch", help="搜用户创建的书单（书单 tab 数据，可翻页）",
                       parents=[_common])
    p.add_argument("keyword", help="关键词（书名/作者/主题均可）")
    p.add_argument("--page", type=int, default=1, metavar="N",
                   help="书单第 N 页（每页 20 个；只返回书单，无作者卡/同页书籍）")
    p.add_argument("--all", action="store_true",
                   help="自动翻页拿全部书单（每页 50 个，上限 200 个）")

    p = sub.add_parser("bsearch", help="书城搜书（App 搜索多栏接口，带评分/分类，可翻页）",
                       parents=[_common])
    p.add_argument("keyword", help="关键词（书名/作者/题材均可）")
    p.add_argument("--page", type=int, default=1, metavar="N",
                   help="书籍第 N 页（每页 20 本）")
    p.add_argument("--all", action="store_true",
                   help="自动翻页拿全部书籍（每页 50 本，上限 200 本）")

    p = sub.add_parser("booklist", help="书单详情：书单内书列表",
                       parents=[_common])
    p.add_argument("blid", help="书单 id（blsearch 结果里的 id）")
    p.add_argument("--sale", action="store_true",
                   help="只显示在售书（剔除 is_removed=true 的下架书）")

    p = sub.add_parser("mybl", help="我的书单列表（我创建的 / 我收藏的，只读）",
                       parents=[_common])
    p.add_argument("--fav", action="store_true", help="看我收藏的书单（默认看我创建的）")
    p.add_argument("--books", action="store_true", help="同时列出每个书单里的书")

    p = sub.add_parser("blnew", help="创建书单（⚠️ 写操作）", parents=[_common])
    p.add_argument("name", help="书单名称（1~40 字）")
    p.add_argument("--desc", required=True, help="书单描述（1~200 字，必填）")
    p.add_argument("--qiu", action="store_true", help="建成「求书单」（默认晒书单）")
    p.add_argument("--add", action="append", default=[], metavar="BID[:理由]",
                   help="建单时顺带加书，可重复：--add 10881716:很好看")

    p = sub.add_parser("bledit", help="改书单名称/描述（⚠️ 写操作）", parents=[_common])
    p.add_argument("blid", help="书单 id")
    p.add_argument("--name", default=None, help="新名称（不改就省略）")
    p.add_argument("--desc", default=None, help="新描述（不改就省略）")

    p = sub.add_parser("bladd", help="往书单加书（⚠️ 写操作）", parents=[_common])
    p.add_argument("blid", help="书单 id")
    p.add_argument("bids", nargs="+", help="book_id 或 ISBN:xxx")
    p.add_argument("--reason", default="", help="给这些书统一写一句推荐理由")
    p.add_argument("--dry", action="store_true", help="只预览要加什么，不写入")

    p = sub.add_parser("blrm", help="把书移出书单（⚠️ 写操作，默认预览）",
                       parents=[_common])
    p.add_argument("blid", help="书单 id")
    p.add_argument("bids", nargs="+", help="book_id")
    p.add_argument("--yes", action="store_true", help="真正移除；不加则只预览")

    p = sub.add_parser("bldel", help="删除书单（⚠️ 写操作，默认预览）", parents=[_common])
    p.add_argument("blid", nargs="+", help="书单 id，可给多个")
    p.add_argument("--yes", action="store_true", help="真正删除；不加则只预览")

    p = sub.add_parser("blfav", help="收藏/取消收藏别人的书单（⚠️ 写操作）",
                       parents=[_common])
    p.add_argument("blid", help="书单 id")
    p.add_argument("--off", action="store_true", help="取消收藏")

    p = sub.add_parser("blsuggest", help="书单加书时的联想搜索（只读）",
                       parents=[_common])
    p.add_argument("keyword", help="书名或作者关键词")

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
    p.add_argument("--no-auto-folder", action="store_true",
                   help="买完不自动归到书架文件夹（默认自动挑选已存在的自建文件夹）")
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

    p = sub.add_parser("cart", help="查看购物车（新版，含下架/失效标记，只读）",
                       parents=[_common])
    p.add_argument("--recd", action="store_true",
                   help="同时列出基于购物车的推荐书目")

    p = sub.add_parser("cartdel", help="从购物车删除书目（⚠️ 写操作，默认预览）",
                       parents=[_common])
    p.add_argument("bids", nargs="+", help="book_id，可给多个")
    p.add_argument("--category", type=int, default=1,
                   help="bookCategory（出版书籍=1，默认 1）")
    p.add_argument("--yes", action="store_true", help="真正删除；不加则只预览")

    p = sub.add_parser("cartadd", help="加入购物车（⚠️ 契约已破解，服务端暂拒，见文档）",
                       parents=[_common])
    p.add_argument("bid", help="book_id")
    p.add_argument("--category", type=int, default=1,
                   help="bookCategory（出版书籍=1，默认 1）")

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

        # 买完归夹：下单前判定一次，询价与确认下单共用同一决定。
        # 显式 --folder 优先；--no-shelf / --no-auto-folder 时不判定。
        decision = None
        if a.folder:
            decision = {"folder": a.folder, "reason": "命令行 --folder 指定"}
        elif not a.no_shelf and not a.no_auto_folder:
            decision = auto_folder_decision(
                c, a.bid, re.sub(r"^《|》$", "", title).strip())
        if decision is not None:
            dest = decision["folder"]
            print("买完归夹    " + (
                f"将归入「{dest}」（{decision['reason']}）" if dest
                else f"不移动：{decision['reason']}"))

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
        folder = decision["folder"] if decision else ""
        if folder and not a.folder:
            # 自动归夹只认下单前已存在的自建文件夹；夹若已被删就保持未归类，
            # 不能让 shelf_add 把它重新建出来。
            try:
                alive = {_folder_of(it) for it in c.shelf_tree()[0]
                         if it.get("dtype") == 1}
                if folder not in alive:
                    print(f"自动归夹    跳过：文件夹「{folder}」已不存在，保持未归类")
                    folder = ""
            except Exception:
                folder = ""
        sr = c.shelf_add(a.bid, name, folder=folder)
        if sr.get("code") == 0:
            rows, _ = c._shelf_rows()
            on = a.bid in {str(x.get("book_id")) for x in rows}
            dest = f"（已归入「{folder}」）" if folder else ""
            print(f"加入云书架：{sr.get('before_total', '?')} → {len(rows)} 本  "
                  f"{'✅ 已加入' if on else '⚠️ 复核未在书架'}{dest}")
            if folder and not a.folder and decision:
                print(f"自动归夹    ✅ 已归入「{folder}」：{decision['reason']}")
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

    # ---------------- cart（购物车，只读） ----------------
    if a.cmd == "cart":
        auth = need_auth(auth)
        c = Client(auth, workers=a.workers)
        data = c.cart_list()
        total = sum(len(g["books"]) for g in data["groups"])
        if a.json:
            print(json.dumps(data, ensure_ascii=False, indent=1))
            return
        if not total:
            print("购物车是空的。")
        else:
            state_txt = {0: "", 1: "免费", 2: "下架", 3: "失效"}
            print(f"购物车 {total} 本（上限 {data['limit']}）\n")
            for g in data["groups"]:
                tn = g["type_name"] or f"分类{g['type']}"
                print(f"【{tn}】{len(g['books'])} 本")
                for b in g["books"]:
                    st = state_txt.get(b.get("state", 0), f"state={b.get('state')}")
                    mark = f"  「{st}」" if st else ""
                    sel = "☑" if b.get("selectStatus") else "☐"
                    print(f"  {sel} [{b['bookId']}] 《{b['bookName']}》{mark}")
                    print(f"        {b.get('author', '')}  {b.get('priceDesc', '')}"
                          + (f"  {b['buyDesc']}" if b.get("buyDesc") else ""))
            dead = [b for g in data["groups"] for b in g["books"]
                    if b.get("state") not in (0, 1)]
            if dead:
                print(f"\n⚠️  {len(dead)} 本下架/失效（不支持结算）："
                      + "、".join(f"《{b['bookName']}》" for b in dead))
                print("    留着不影响其他书结算；要清掉可用 cartdel。")
        if a.recd:
            rows = c.cart_recd()
            if rows:
                print(f"\n基于购物车的推荐 {len(rows)} 本：")
                for b in rows:
                    print(f"  [{b['bookId']}] 《{b['bookName']}》")
        return

    # ---------------- cartdel（写操作，默认预览） ----------------
    if a.cmd == "cartdel":
        auth = need_auth(auth)
        c = Client(auth, workers=a.workers)
        data = c.cart_list()
        in_cart = {str(b["bookId"]): b for g in data["groups"] for b in g["books"]}
        known = [(str(bid), in_cart[str(bid)]) for bid in a.bids
                 if str(bid) in in_cart]
        unknown = [str(bid) for bid in a.bids if str(bid) not in in_cart]
        if a.json:
            print(json.dumps({"will_delete": [b for _, b in known],
                              "not_in_cart": unknown, "confirmed": bool(a.yes)},
                             ensure_ascii=False, indent=1))
            return
        print(f"将删除 {len(known)} 本：")
        for bid, b in known:
            print(f"  [{bid}] 《{b['bookName']}》")
        for bid in unknown:
            print(f"  [{bid}]（不在购物车里，跳过）")
        if not known:
            return
        if not a.yes:
            print("\n预览完毕；确认无误请加 --yes 执行删除。")
            return
        r = c.cart_del([bid for bid, _ in known], category=a.category)
        data2 = c.cart_list()
        in_cart2 = {str(b["bookId"]) for g in data2["groups"] for b in g["books"]}
        gone = [bid for bid, _ in known if bid not in in_cart2]
        print(f"\n✅ 已删除 {len(gone)}/{len(known)} 本，购物车现有 "
              f"{len(in_cart2)} 本（上限 {data2['limit']}）")
        left = [bid for bid, _ in known if bid in in_cart2]
        if left:
            print(f"⚠️  仍在购物车：{'、'.join(left)}（服务端可能未生效，如实上报）")
        return

    # ---------------- cartadd（写操作） ----------------
    if a.cmd == "cartadd":
        auth = need_auth(auth)
        c = Client(auth, workers=a.workers)
        name = ""
        try:
            name = c.detail(a.bid).get("name") or ""
        except Exception:
            pass
        print(f"加入购物车：[{a.bid}] 《{name}》（bookCategory={a.category}）",
              flush=True)
        try:
            r = c.cart_add(a.bid, category=a.category)
        except RuntimeError as e:
            if "code=201" in str(e):
                print("《%s》已在购物车，无需重复添加" % (name or a.bid))
                return
            print(f"[失败] {e}", file=sys.stderr)
            if "53002" in str(e):
                print("说明：加购要求请求带非空 p1/p3 设备参数（已内置）；"
                      "若仍报错见 references/api.md 10b 节。", file=sys.stderr)
            sys.exit(1)
        print(f"✅ 服务端返回：{json.dumps(r, ensure_ascii=False)[:200]}")
        data = c.cart_list()
        in_cart = {str(b["bookId"]) for g in data["groups"] for b in g["books"]}
        print(f"购物车现有 {len(in_cart)} 本，"
              f"{'✅ 已在购物车' if str(a.bid) in in_cart else '⚠️ 复核未在购物车'}")
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

    # ---------------- author（只读：作者主页） ----------------
    if a.cmd == "author":
        r = c.author_page(a.bid)
        if a.json:
            print(json.dumps(r, ensure_ascii=False, indent=1))
            return
        if not r.get("ok"):
            print("[失败] " + r.get("msg", ""), file=sys.stderr)
            sys.exit(1)
        print(f"=== 作者主页 ===（入口：《{r['source_book_name']}》 {r['source_book']}）")
        print(f"作者   {r['name']}"
              + (f"（{r['utag']}）" if r.get("utag") else "")
              + f"   入口署名：{r['role']}")
        if r.get("intro"):
            body = r["intro"]
            print("简介   " + (body if len(body) <= 300
                              else body[:300] + "…（--json 看全文）"))
        extra = []
        if r.get("all_books_label"):
            extra.append(r["all_books_label"])
        if r.get("total_words"):
            extra.append(r["total_words"])
        print(f"作品   共 {r['total_books']} 本"
              + ("（" + "，".join(extra) + "）" if extra else ""))
        priced = c.price_many([w["bid"] for w in r["works"]])
        for i, w in enumerate(r["works"], 1):
            d = priced.get(w["bid"]) or {}
            if d.get("price") is not None:
                ps = f"{d['price']:>6.0f} 阅饼"
            elif d.get("free"):
                ps = "  免费"
            else:
                ps = "  无整本价"
            print(f"  {i:>2}. {w['bid']:<10} {ps}  {w['name'].strip()[:36]}")
        return

    # ---------------- blsearch（只读：书单搜索） ----------------
    if a.cmd == "blsearch":
        if getattr(a, "all", False):
            r = c.search_booklist_all(a.keyword)
        elif a.page > 1:
            r = c.search_booklist(a.keyword, page=a.page, page_size=20,
                                  paginated=True)
        else:
            r = c.search_booklist(a.keyword)
        if a.json:
            print(json.dumps(r, ensure_ascii=False, indent=1))
            return
        if not r.get("ok"):
            print("[失败] 搜索接口无返回或格式异常", file=sys.stderr)
            sys.exit(1)
        bls = r.get("booklists") or []
        pg = r.get("bk_page") or {}
        mode = r.get("mode") or ""
        if pg and mode == "all":
            print(f"=== 书单搜索「{a.keyword}」=== 共 {pg.get('totalRecord', '?')} 个书单，"
                  f"已抓取 {len(bls)} 个")
        elif pg and mode.startswith("page:"):
            print(f"=== 书单搜索「{a.keyword}」=== 第 {pg.get('currentPage', '?')}"
                  f"/{pg.get('totalPage', '?')} 页，共 {pg.get('totalRecord', '?')} 个书单"
                  f"（本页 {len(bls)} 个）")
        elif pg:
            print(f"=== 书单搜索「{a.keyword}」=== 共 {pg.get('totalRecord', '?')} 个书单"
                  f"（首屏 {len(bls)} 个；--page 翻页 / --all 拿全部）")
        else:
            print(f"=== 书单搜索「{a.keyword}」===")
        if r.get("author_card"):
            ac = r["author_card"]
            body = ac.get("synopsis") or ""
            print(f"◆ 作者卡  {ac.get('authorName')}")
            print("    " + (body[:180] + "…（--json 看全文）" if len(body) > 180 else body))
        for b in bls:
            tags = "/".join(b.get("tags") or [])
            print(f"◆ {b.get('id')}  {b.get('name')}")
            meta = []
            if b.get("count") is not None:
                meta.append(f"含书 {b['count']} 本")
            if b.get("fav_num") is not None:
                meta.append(f"收藏 {b['fav_num']}")
            if b.get("like") is not None:
                meta.append(f"点赞 {b['like']}")
            if b.get("user_nick"):
                meta.append(f"创建人 {b['user_nick']}")
            if meta:
                print("    " + " · ".join(meta))
            if tags:
                print(f"    标签：{tags}")
            desc = b.get("description") or ""
            if desc:
                print("    " + (desc[:160] + "…（--json 看全文）" if len(desc) > 160 else desc))
            print(f"    详情：python picker.py booklist {b.get('id')}")
        if r.get("books"):
            print(f"--- 同页书籍 {len(r['books'])} 本 ---")
            for b in r["books"]:
                rt = f"{b['rating']:.1f}分" if b.get("rating") is not None else "—"
                print(f"    {b.get('bid')}  {b.get('name')}  {b.get('author')}  {rt}")
        if r.get("related"):
            print("相关搜索：" + " / ".join(r["related"][:6]))
        return

    # ---------------- bsearch（只读：书城搜书，App 多栏接口书籍 tab） ----------------
    if a.cmd == "bsearch":
        if getattr(a, "all", False):
            r = c.search_book_all(a.keyword)
        elif a.page > 1:
            r = c.search_book(a.keyword, page=a.page, page_size=20)
        else:
            r = c.search_book(a.keyword)
        if a.json:
            print(json.dumps(r, ensure_ascii=False, indent=1))
            return
        if not r.get("ok"):
            print("[失败] 搜索接口无返回或格式异常", file=sys.stderr)
            sys.exit(1)
        bks = r.get("books") or []
        pg = r.get("book_page") or {}
        mode = r.get("mode") or ""
        if pg and mode == "all":
            print(f"=== 书籍搜索「{a.keyword}」=== 共 {pg.get('totalRecord', '?')} 本，"
                  f"已抓取 {len(bks)} 本")
        elif pg and mode.startswith("page:"):
            print(f"=== 书籍搜索「{a.keyword}」=== 第 {pg.get('currentPage', '?')}"
                  f"/{pg.get('totalPage', '?')} 页，共 {pg.get('totalRecord', '?')} 本"
                  f"（本页 {len(bks)} 本）")
        else:
            print(f"=== 书籍搜索「{a.keyword}」=== 共 {pg.get('totalRecord', '?')} 本"
                  f"（本页 {len(bks)} 本；--page 翻页 / --all 拿全部）")
        if not bks and mode.startswith("page:"):
            print("（本页无结果——页码超出总页数）")
            return
        for b in bks:
            rt = f"{b['rating']:.1f}分" if b.get("rating") is not None else "—"
            comp = "已完结" if str(b.get("complete")).upper() == "Y" else "连载中"
            cat = b.get("category") or ""
            meta = " · ".join(x for x in (rt, cat, comp) if x)
            print(f"◆ {b.get('bid')}  {b.get('name')}  {b.get('author')}  {meta}")
            print(f"    详情：python picker.py info {b.get('bid')}")
        return

    # ---------------- booklist（只读：书单详情） ----------------
    if a.cmd == "booklist":
        # 优先走原生接口：一次拿全书目（每页 10 本、自动翻页），比 H5 只能取前 5 本强
        native = None
        try:
            native = c.booklist_info(a.blid)
        except RuntimeError as e:
            print(f"（原生接口不可用，退回 H5 页：{e}）", file=sys.stderr)
        if native:
            if a.json:
                print(json.dumps(native, ensure_ascii=False, indent=1))
                return
            u = native.get("user") or {}
            print(f"=== 书单 {a.blid}  {native.get('name') or ''} ===")
            meta = []
            if native.get("count") is not None:
                meta.append(f"含书 {native['count']} 本")
            if native.get("favNum"):
                meta.append(f"收藏 {native['favNum']}")
            if u.get("name") or native.get("user_nick"):
                meta.append(f"创建人 {u.get('name') or native.get('user_nick')}")
            if native.get("updateTime"):
                meta.append(f"更新 {native['updateTime']}")
            if native.get("isPublic"):
                meta.append("公开" if native["isPublic"] == "public" else native["isPublic"])
            if meta:
                print(" · ".join(meta))
            if native.get("desc"):
                d = native["desc"]
                print("描述   " + (d[:200] + "…（--json 看全文）" if len(d) > 200 else d))
            if native.get("tags"):
                print("标签   " + "/".join(native["tags"]))
            books = native.get("books") or []
            removed_n = sum(1 for b in books if b.get("is_removed"))
            # --sale 只看在售；H5 回退路径没有 is_removed 字段，不过滤
            shown = [b for b in books if not b.get("is_removed")] if a.sale else books
            head = f"书目 {len(shown)} 本"
            if a.sale:
                head += f"（已剔除下架 {removed_n} 本）" if removed_n else "（均在售）"
            elif removed_n:
                head += f"（其中已下架 {removed_n} 本，标 [已下架]）"
            print(head)
            for i, b in enumerate(shown, 1):
                rt = f"{b['bookRating']}分" if b.get("bookRating") else ""
                dead = "  [已下架]" if b.get("is_removed") else ""
                print(f"  {i:>2}. {b.get('id'):<12} {b.get('name')}  "
                      f"{b.get('author') or ''}  {rt}{dead}".rstrip())
                if b.get("book_desc"):
                    print(f"      理由：{b['book_desc'][:120]}")
            return
        r = c.booklist_detail(a.blid)
        if a.json:
            print(json.dumps(r, ensure_ascii=False, indent=1))
            return
        if not r.get("ok"):
            print("[失败] 书单详情页无返回", file=sys.stderr)
            sys.exit(1)
        if a.sale:
            print("（H5 回退路径无下架标记，--sale 未生效）", file=sys.stderr)
        print(f"=== 书单 {a.blid} ==="
              + (f"  点赞 {r['like']}" if r.get("like") is not None else ""))
        if r.get("description"):
            d = r["description"]
            print("描述   " + (d[:200] + "…（--json 看全文）" if len(d) > 200 else d))
        books = r.get("books") or []
        tp = r.get("total_pages")
        print(f"书列表 {len(books)} 本"
              + (f"（H5 共 {tp} 页，每页 5 本；更多书的翻页接口未公开，仅能取到第一屏）"
                 if tp and tp > 1 else ""))
        for i, b in enumerate(books, 1):
            print(f"  {i:>2}. {b.get('bid'):<10} {b.get('name')}  {b.get('author')}")
            if b.get("reason"):
                print(f"      理由：{b['reason'][:120]}")
        return

    # ---------------- 我的书单（原生接口） ----------------

    def _fmt_booklist_head(d: dict, i: int = 0) -> None:
        """打印一条书单的概要（mybl / bldel 预览共用）。"""
        tags = "/".join(d.get("tags") or [])
        cnt = d.get("count")
        meta = []
        if cnt is not None:
            meta.append(f"含书 {cnt} 本")
        if d.get("fav_num"):
            meta.append(f"收藏 {d['fav_num']}")
        if d.get("like"):
            meta.append(f"点赞 {d['like']}")
        if d.get("is_public") and d["is_public"] != "public":
            meta.append(d["is_public"])
        if d.get("update_time"):
            meta.append(f"更新 {d['update_time']}")
        prefix = f"{i:>2}. " if i else ""
        print(f"{prefix}{d.get('id')}  {d.get('name')}"
              + ("   " + " · ".join(meta) if meta else ""))
        if tags:
            print(f"    标签：{tags}")
        desc = d.get("description") or ""
        if desc:
            print("    " + (desc[:160] + "…（--json 看全文）" if len(desc) > 160 else desc))

    if a.cmd == "mybl":
        r = c.my_booklists("2" if a.fav else "1")
        if a.json:
            print(json.dumps(r, ensure_ascii=False, indent=1))
            return
        kind = "我收藏的书单" if a.fav else "我创建的书单"
        print(f"=== {kind} === 共 {r['total']} 个")
        lists = r.get("lists") or []
        if not lists:
            print("（还没有书单）" if not a.fav
                  else "（还没收藏别人的书单，用 blfav <书单id> 收藏）")
            return
        for d in lists:
            _fmt_booklist_head(d)
            if a.books:
                # myList 里的 books 只是预览（通常只回 1 本，且 description 不是推荐理由），
                # 要列全书目得单独打 info 接口
                try:
                    full = c.booklist_info(d.get("id"))
                    bl = full.get("books") or []
                except RuntimeError as e:
                    print(f"      （书目读取失败：{e}）", file=sys.stderr)
                    bl = d.get("books") or []
                for j, bk in enumerate(bl, 1):
                    reason = (bk.get("book_desc") or "").strip()
                    print(f"      {j}. {bk.get('id')}  {bk.get('name')}"
                          + (f"  理由：{reason[:60]}" if reason else ""))
            print(f"    详情：python scripts/picker.py booklist {d.get('id')}")
        return

    if a.cmd == "blsuggest":
        rows = c.booklist_suggest(a.keyword)
        if a.json:
            print(json.dumps(rows, ensure_ascii=False, indent=1))
            return
        if not rows:
            print(f"「{a.keyword}」没有联想结果", file=sys.stderr)
            return
        print(f"=== 联想「{a.keyword}」 === 共 {len(rows)} 条")
        for i, r0 in enumerate(rows, 1):
            kind = "在售" if str(r0.get("type")) == "1" else "ISBN(豆瓣)"
            print(f"  {i:>2}. {r0.get('id'):<18} {kind:<10} {r0.get('name')}"
                  f"  {r0.get('author') or ''}")
        print("\n加书：python scripts/picker.py bladd <书单id> <上面第一列的 id>")
        return

    if a.cmd == "blnew":
        # 服务端对名称/描述长度与敏感词统一返回 31215，本地先挡明显超限的
        if not a.name.strip():
            print("⚠️  书单名称不能为空", file=sys.stderr)
            sys.exit(2)
        if len(a.name) > 40:
            print(f"⚠️  书单名称最长 40 字（当前 {len(a.name)} 字）", file=sys.stderr)
            sys.exit(2)
        if len(a.desc) > 200:
            print(f"⚠️  书单描述最长 200 字（当前 {len(a.desc)} 字）", file=sys.stderr)
            sys.exit(2)
        # 建单时的 addBooks 服务端解析不过（空 id 触发 int('')），所以先建空单再加书
        try:
            r = c.booklist_create(a.name, a.desc,
                                  book_type="2" if a.qiu else "1")
        except RuntimeError as e:
            msg = str(e)
            if "31215" in msg:
                msg += ("（多为名称/描述超长或含敏感词：名称 1~40 字、"
                        "描述 1~200 字，且不能出现违规词）")
            print(f"[失败] {msg}", file=sys.stderr)
            sys.exit(1)
        added, failed = [], []
        for spec in a.add or []:
            bid, reason = _split_add_spec(spec)
            bid = bid.strip()
            if not bid:
                continue
            is_isbn = bid.upper().startswith("ISBN:")
            plain = bid[5:] if is_isbn else bid
            name = author = pic = ""
            try:
                d = c.detail(plain) if not is_isbn else {}
                name, author = d.get("name") or "", d.get("author") or ""
                pic = d.get("cover") or ""
            except Exception:  # noqa: BLE001
                pass
            if not name:
                for cand in c.booklist_suggest(plain) or []:
                    if str(cand.get("id")) == bid:
                        name = cand.get("name") or ""
                        author = cand.get("author") or ""
                        pic = cand.get("pic") or ""
                        break
            try:
                c.booklist_add_book(r["id"], bid, name=name, author=author,
                                    desc=reason.strip(), pic=pic, is_isbn=is_isbn)
                added.append({"bid": bid, "name": name})
            except RuntimeError as e:
                failed.append((bid, str(e)))
        if added:
            try:
                have = {_bl_book_key(b.get("id")): b
                        for b in (c.booklist_info(r["id"]).get("books") or [])}
                for x in added:
                    bk = have.get(_bl_book_key(x["bid"]))
                    if bk and not x["name"]:
                        x["name"] = bk.get("name") or ""
            except RuntimeError:
                pass
        if a.json:
            print(json.dumps({**r, "added": added,
                              "failed": [{"bid": b, "error": m} for b, m in failed]},
                             ensure_ascii=False, indent=1))
            return
        kind = "求书单" if a.qiu else "晒书单"
        print(f"✅ 已创建{kind} {r['id']}  {r['name']}")
        if added:
            print(f"   建单时带入了 {len(added)} 本书：")
            for x in added:
                print(f"     {x['bid']:<18} {x['name']}")
        for b, m in failed:
            print(f"⚠️  {b} 未加入：{m}", file=sys.stderr)
        print(f"   详情：python scripts/picker.py booklist {r['id']}")
        print(f"   加书：python scripts/picker.py bladd {r['id']} <book_id>")
        return

    if a.cmd == "bledit":
        if a.name is None and a.desc is None:
            print("⚠️  至少要给 --name 或 --desc 之一", file=sys.stderr)
            sys.exit(2)
        if a.name is not None and (not a.name.strip() or len(a.name) > 40):
            print(f"⚠️  书单名称需 1~40 字（当前 {len(a.name)} 字）", file=sys.stderr)
            sys.exit(2)
        if a.desc is not None and len(a.desc) > 200:
            print(f"⚠️  书单描述最长 200 字（当前 {len(a.desc)} 字）", file=sys.stderr)
            sys.exit(2)
        cur = c.booklist_info(a.blid)
        name = a.name if a.name is not None else (cur.get("name") or "")
        desc = a.desc if a.desc is not None else (cur.get("desc") or "")
        try:
            r = c.booklist_update(a.blid, name, desc)
        except RuntimeError as e:
            msg = str(e)
            if "31215" in msg:
                msg += "（名称/描述超长或含敏感词）"
            print(f"[失败] {msg}", file=sys.stderr)
            sys.exit(1)
        if a.json:
            print(json.dumps(r, ensure_ascii=False, indent=1))
            return
        print(f"✅ 已保存书单 {a.blid}  {r['name']}")
        if a.name is not None:
            print(f"   名称：{cur.get('name')} → {name}")
        if a.desc is not None:
            old = (cur.get("desc") or "")[:40]
            print(f"   描述：{old}… → {desc[:40]}")
        print("   注意：服务端会在保存后把书单置为审核态，并把自动生成的标签清空；"
              "标签由书目分类重算，通常要等审核结束或重新加书才会回来。")
        return

    if a.cmd == "bladd":
        targets = []
        for bid in a.bids:
            is_isbn = bid.upper().startswith("ISBN:")
            plain = bid[5:] if is_isbn else bid
            meta = {"name": "", "author": "", "pic": ""}
            if not is_isbn:
                try:
                    d = c.detail(plain)
                    meta = {"name": d.get("name") or "", "author": d.get("author") or "",
                            "pic": d.get("cover") or ""}
                except Exception:  # noqa: BLE001 - 书目抓取失败不该挡住加书
                    pass
            if not meta["name"]:
                # 详情页取不到（下架/仅试读）或 ISBN 书：退回联想接口补书名/作者
                for cand in c.booklist_suggest(plain) or []:
                    if str(cand.get("id")) == bid:
                        meta = {"name": cand.get("name") or "",
                                "author": cand.get("author") or "",
                                "pic": cand.get("pic") or ""}
                        break
            targets.append({"bid": bid, "is_isbn": is_isbn, **meta})
        if a.dry:
            print(f"（预览）将往书单 {a.blid} 加 {len(targets)} 本：")
            for t in targets:
                print(f"  {t['bid']:<18} {t['name'] or '(书名待补)'}"
                      f"  {t['author'] or ''}".rstrip())
            if a.reason:
                print(f"  推荐理由统一写：{a.reason}")
            print("去掉 --dry 才会真正写入。")
            return
        ok, fail = [], []
        for t in targets:
            try:
                c.booklist_add_book(a.blid, t["bid"], name=t["name"],
                                    author=t["author"], desc=a.reason,
                                    pic=t["pic"], is_isbn=t["is_isbn"])
                ok.append(t)
            except RuntimeError as e:
                fail.append((t, str(e)))
        if ok:
            # 加完后回读一次，用服务端解析出的书名/作者覆盖（详情页抓不到的靠这里补）。
            # 书单刚加过书会进入审核态（status=check），这时 info 读不到，跳过即可。
            try:
                have = {_bl_book_key(b.get("id")): b
                        for b in (c.booklist_info(a.blid).get("books") or [])}
                for t in ok:
                    bk = have.get(_bl_book_key(t["bid"]))
                    if bk:
                        t["name"] = bk.get("name") or t["name"]
                        t["author"] = bk.get("author") or t["author"]
            except RuntimeError:
                pass
        if a.json:
            print(json.dumps({"id": a.blid, "added": [t["bid"] for t in ok],
                              "failed": [{"bid": t["bid"], "error": m}
                                         for t, m in fail]},
                             ensure_ascii=False, indent=1))
            return
        if ok:
            print(f"✅ 已加入 {len(ok)} 本到书单 {a.blid}")
            for t in ok:
                print(f"   {t['bid']:<18} {t['name'] or ''}")
        for t, m in fail:
            print(f"⚠️  {t['bid']} 未加入：{m}", file=sys.stderr)
        if fail and not ok:
            sys.exit(1)
        print(f"   看书单：python scripts/picker.py booklist {a.blid}")
        return

    if a.cmd == "blrm":
        cur = c.booklist_info(a.blid)
        have = {_bl_book_key(b.get("id")): b for b in (cur.get("books") or [])}
        todo = [b for b in a.bids if _bl_book_key(b) in have]
        missing = [b for b in a.bids if _bl_book_key(b) not in have]
        for b in missing:
            print(f"⚠️  {b} 不在书单 {a.blid} 里，跳过", file=sys.stderr)
        if not todo:
            print("没有可移除的书。", file=sys.stderr)
            sys.exit(1)
        if not a.yes:
            print(f"（预览）将从书单 {a.blid}「{cur.get('name')}」移除 {len(todo)} 本：")
            for b in todo:
                bk = have[_bl_book_key(b)]
                print(f"  {b:<12} {bk.get('name')}")
            print("加 --yes 才真正移除。")
            return
        try:
            r = c.booklist_remove_book(a.blid, todo)
        except RuntimeError as e:
            print(f"[失败] {e}", file=sys.stderr)
            sys.exit(1)
        if a.json:
            print(json.dumps(r, ensure_ascii=False, indent=1))
            return
        print(f"✅ 已从书单 {a.blid} 移除 {len(r['removed'])} 本")
        return

    if a.cmd == "bldel":
        rows = []
        for blid in a.blid:
            try:
                d = c.booklist_info(blid)
                rows.append({"id": blid, "name": d.get("name"),
                             "count": d.get("count")})
            except RuntimeError as e:
                print(f"⚠️  书单 {blid} 读不到：{e}", file=sys.stderr)
                rows.append({"id": blid, "name": "(未知)", "count": None})
        if not a.yes:
            print("（预览）将删除以下书单：")
            for d in rows:
                print(f"  {d['id']}  {d['name']}"
                      + (f"  含书 {d['count']} 本" if d.get("count") is not None else ""))
            print("⚠️  删书单不可恢复（书单里的书本身不会被删）。加 --yes 才执行。")
            return
        done, fail = [], []
        for d in rows:
            try:
                c.booklist_delete(d["id"])
                done.append(d)
            except RuntimeError as e:
                fail.append((d, str(e)))
        if a.json:
            print(json.dumps({"deleted": [d["id"] for d in done],
                              "failed": [{"id": d["id"], "error": m}
                                         for d, m in fail]},
                             ensure_ascii=False, indent=1))
            return
        for d in done:
            print(f"✅ 已删除 {d['id']}  {d['name']}")
        for d, m in fail:
            print(f"⚠️  {d['id']} 删除失败：{m}", file=sys.stderr)
        if fail:
            sys.exit(1)
        return

    if a.cmd == "blfav":
        try:
            r = c.booklist_favorite(a.blid, add=not a.off)
        except RuntimeError as e:
            print(f"[失败] {e}", file=sys.stderr)
            sys.exit(1)
        if a.json:
            print(json.dumps(r, ensure_ascii=False, indent=1))
            return
        print(f"✅ 已{'取消收藏' if a.off else '收藏'}书单 {a.blid}")
        print("   查看：python scripts/picker.py mybl --fav")
        return

    # ---------------- categories ----------------
    if a.cmd == "categories":
        cats = c.categories(a.channel)
        print(f"{CHANNELS.get(a.channel, a.channel)}频道共 {len(cats)} 个分类：\n")
        for cid, nm in cats:
            print(f"  {nm:<8} cid={cid}")
        return

    # ---------------- 求可用券额（afford/recommend/category/search/taoshu 共用） ----------------
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

    # ---------------- taoshu（淘书市当期书目 × 叠加满减券推荐） ----------------
    if a.cmd == "taoshu":
        # ① 找当期活动（未换期时安静退出，与 ireader_welfare 口径一致）
        acts = [(a.act, "命令行指定")] if a.act else []
        if not acts:
            try:
                acts = tss_find_activities()
            except Exception as e:
                print(f"淘书市: 滚动栏拉取失败（{e}）", file=sys.stderr)
        if not acts:
            print("淘书市: 本期活动不在滚动栏里（未换期或已结束），"
                  "可过几天再试，或用 ireader_welfare 领完券再来。")
            return

        act_id, source = acts[0]
        if len(acts) > 1:
            print(f"淘书市: 滚动栏挂了 {len(acts)} 期，取第一个 {act_id}（{source}）"
                  f"，其余 {' '.join(x[0] for x in acts[1:])} 可用 --act 指定",
                  file=sys.stderr)

        try:
            act = tss_load(act_id)
        except Exception as e:
            print(f"淘书市: 活动页解析失败（{e}）", file=sys.stderr)
            sys.exit(1)
        act["source"] = source
        coupons = act["coupons"]
        show_coupons = bool(getattr(a, "show_coupons", False))
        if a.json and show_coupons:
            print(json.dumps({"act_id": act_id, "source": source,
                              "coupons": coupons}, ensure_ascii=False, indent=1))
            return
        print(f"淘书市: 活动 {act_id}（{source}）", file=sys.stderr)
        if not coupons:
            print("淘书市: 本期活动页里没有满减券组件，退化为纯书目推荐。", file=sys.stderr)
        else:
            print(f"淘书市: 本期 {len(coupons)} 张满减券：", file=sys.stderr)
            for cp in coupons:
                if cp.get("amount"):
                    print(f"  {cp['amount']:>5.0f} 券  {cp['quota']}  {cp['valid']}",
                          file=sys.stderr)
            print("  （领券走 ireader_welfare：python src/main.py taoshushi）",
                  file=sys.stderr)
        if show_coupons:
            for cp in coupons:
                print(f"{cp['amount']:g}\t{cp['quota']}\t{cp['valid']}\t"
                      f"#{cp['product_id']}")
            return
        if not act["book_ids"]:
            print("淘书市: 本期活动页里没有书目组件。")
            return

        # ② 选一张「叠得上去」的券：门槛 ≤ 自付上限 + 面额。多张时取
        #    面额最大者；够不上门槛则不启用（与 afford --coupon 同口径）。
        limit = resolve_limit(a.limit)
        coupon = None
        ceiling = limit
        if coupons:
            usable = [v for v in coupons if v.get("amount")
                      and (v.get("quota") and
                           float(re.search(r"([\d.]+)", v["quota"]).group(1) or 0)
                           or 0) <= limit + v["amount"]]
            if usable:
                coupon = max(usable, key=lambda v: v["amount"])
                thr = float(re.search(r"([\d.]+)", coupon["quota"]).group(1) or 0)
                coupon["threshold"] = thr
                ceiling = limit + coupon["amount"]
                print(f"选券「{coupon['amount']:g}券」{coupon['quota']} → "
                      f"总价上限提到 {ceiling:.0f}（自付 ≤ {limit:.0f}）",
                      file=sys.stderr)
            else:
                b = max(coupons, key=lambda v: v.get("amount") or 0)
                print(f"满减券用不上：自付 {limit:.0f} + 面额 {b['amount']:g} = "
                      f"{limit + (b['amount'] or 0):.0f}，够不到门槛 {b['quota']}。",
                      file=sys.stderr)

        # ③ 活动书目逐本查价（匿名可查；这里带着凭证是为了排除已拥有）
        print(f"活动书目 {len(act['book_ids'])} 本，查价中…", file=sys.stderr)
        cands = [{"id": bid} for bid in act["book_ids"]]
        if a.top and len(cands) > a.top:
            cands = cands[:a.top]
        hits = c.filter_buyable(cands, ceiling, top=None)
        order_map = {bid: i for i, bid in enumerate(act["book_ids"])}

        # ④ 券后自付：价 ≥ 门槛才减面额；再按「自付 ≤ limit」收口。
        def net_price(r: dict) -> float:
            p = r.get("price") or 0
            if coupon and p and p >= (coupon.get("threshold") or 0):
                return max(p - coupon["amount"], 0)
            return p

        if coupon:
            hits = [r for r in hits if net_price(r) <= limit]
        hits.sort(key=lambda r: (net_price(r), order_map.get(r["id"], 10**9)))

        # 未用券的书单独标出来（它们的价 ≤ limit 本身就买得起）
        for r in hits:
            r["coupon_used"] = bool(coupon and net_price(r) < (r.get("price") or 0))

        enrich_douban(hits)

        if a.json:
            out = {"act_id": act_id, "source": source, "coupons": coupons,
                   "limit": limit, "hits": hits}
            if coupon:
                out["coupon"] = coupon
                out["ceiling"] = ceiling
            print(json.dumps(out, ensure_ascii=False, indent=1))
            return

        head = (f"叠加「{coupon['amount']:g}券」后" if coupon else "")
        print(f"\n=== 淘书市 {act_id} {head}自付 ≤ {limit:.0f} 阅饼："
              f"{len(hits)} 本 ===\n")
        for i, r in enumerate(hits[:40], 1):
            line = fmt_book(i, r, real_vouchers(), show_intro)
            if coupon and r["coupon_used"]:
                line += (f"\n       券后自付 {net_price(r):.0f} 阅饼"
                         f"（满{coupon['threshold']:.0f}减{coupon['amount']:g}）")
            print(line)
        if len(hits) > 40:
            print(f"\n… 其余 {len(hits) - 40} 本省略（--json 可看全部）")
        if not hits:
            print("  本期书目没有「自付 ≤ 上限」的书。可 --limit 调高，"
                  "或先去 ireader_welfare 领当期券。")
        else:
            print("\n说明：券后价按标价估算；满减券门槛比的是活动价，"
                  "实际以 buy 试算为准。领券走 ireader_welfare（taoshushi）。")
            douban_ask()
        return

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
