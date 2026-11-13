# 命令参考

需要查某个命令的参数、输出示例、排队规则或常见问题时读这份。接口实现与实测证据在 `api.md`，豆瓣细节在 `douban.md`。

所有命令均以技能根目录为工作目录执行。加 `--json` 得结构化结果；`--json` / `--auth` / `--workers` / `--douban` 写在子命令前后都行。

## 1. 凭证与登录

命令对凭证的要求：

| 命令 | 需要凭证 |
|------|---------|
| `category` / `search` / `categories` / `info` 的价格 | 不需要（匿名可查） |
| `balance`（余额/券） | 需要 |
| `coupons`（满减券） | 需要 |
| `afford` / `recommend` 的默认额度、已拥有判断 | 需要（否则默认按 100 阅饼猜） |
| `buy` / `shelf` / `shelves` / `move` / `mkdir` / `rmdir` | 需要 |

首选手机号 + 密码登录，成功后自动写入 config.json：

```bash
python scripts/picker.py login <手机号>                     # 密码隐藏输入，不留在命令历史
python scripts/picker.py login <手机号> --password XXX       # 自动化场景
python scripts/picker.py login <手机号> --password XXX --no-save   # 只验证不落盘
python scripts/picker.py login <手机号> --password XXX --json      # 输出 usr/zysid/nick
```

- 走 `uc.ireader.com/user/slogin/passwd/v2`，AES+RSA 加密握手，签名用 `scripts/native_keys.json` 里的客户端私钥（服务端只认第 4 把，下标 3，脚本已固定）。
- 依赖 `cryptography` 库：`python -m pip install cryptography`；其余命令不需要。
- 错误密码返回 `[失败] 登录失败：密码错误`，退出码 1，不会写坏 config.json。
- `config.json` 含凭证，不要提交到任何仓库（已在 `.gitignore`）。
- zysid 有有效期，失效后重新 `login` 一次即可刷新。

其余提供方式（优先级从高到低）：

```bash
python scripts/picker.py balance --auth "usr=i123456&zysid=abcdef..."

set IREADER_USR=i123456
set IREADER_ZYSID=abcdef...

{"usr": "i123456", "zysid": "abcdef..."}     # config.json，技能根目录或 scripts/ 下都行
```

脚本缺失凭证时给出提示并以退出码 2 结束。

## 2. 按意图选命令

```
登录/换号/凭证过期            → login <手机号>
有多少钱/券啥时候过期         → balance
有满减券吗/满多少减多少       → coupons
这些钱能买啥/能白拿哪些       → afford [--coupon]；再加 recommend 按热度排序
有什么推荐/哪个分类好看       → recommend --sort download|score|update；category <分类名>
《某书》多少钱/我买过没       → info <book_id>；不知道 id 时先 search <关键词>
买下这本/下单                → buy <book_id> 询价 → 用户确认 → buy <book_id> --confirm
                             想买完直接归夹，在 --confirm 后加 --folder <夹名>
书架有哪些文件夹/各夹几本     → shelves；shelves --folder 科幻 --books
把书移到某夹/买完自动归位     → move <book_id> --to <夹名> --dry 预览 → 去掉 --dry 写入
                             新建/删除文件夹：mkdir <名> / rmdir <名> [--force]
```

## 3. 查询类命令

### balance

```bash
python scripts/picker.py balance
```

输出阅饼余额、代金券总额、每张券的到期日与剩余天数，并给出下一步命令建议。有券即将过期会显式提醒，这是最该优先处理的情况。末尾附满减券摘要。

### coupons

```bash
python scripts/picker.py coupons                  # 书籍优惠券
python scripts/picker.py coupons --kind goods     # 实物商品优惠券
```

代金券与满减券是两套完全不同的东西：

| | 代金券 | 满减券（优惠券） |
|---|---|---|
| 用法 | 面额 1:1 抵阅饼 | 「满 X 减 Y」，达到门槛才可用 |
| 生效方式 | 自动优先扣除 | 需在订单页手动选择 |
| 接口 | `/zyuc/gift/ajaxrequest?index=2` | `/zyuc/coupon/ajaxrequest?index=1` |
| 能否脚本下单时自动用 | 能 | 不能 |

输出示例：

```
    200 阅饼  满1000阅饼      2026-11-10 至 2026-11-13  ✅ 可用  新满1000减200
    200 阅饼  满1000阅饼      2026-10-29 至 2026-11-01  ❌ 已过期/已用  新满1000减200
```
脚本 `buy` 走新版订单通道，满减券自动抵扣。旧通道（`Order.Create` + `Order.Pay`）才用不了券——三个试算入口都不带优惠券，`couponId`、`couponProductId` 等参数逐个注入 `需支付` 金额都不变，支付时带 `couponProductId` 也仍按原价扣券。脚本已弃用旧通道，改走 `/trade/order/pay`（详见 `api.md` 第 9b 节）。

结论：`buy` 下单时满减券自动生效，折后应付 = 活动价 − 满减券面额，由代金券与阅饼共同抵扣。查券用 `coupons`，避免用券加 `--ignore-coupon`。

### afford

```bash
python scripts/picker.py afford                        # 上限 = 可用券额，扫出版频道
python scripts/picker.py afford --limit 300            # 显式指定上限
python scripts/picker.py afford --coupon --limit 1000  # 把满减券算进去
python scripts/picker.py afford --full --limit 300     # 穷举全部分类（约 10 分钟）
```

判断依据：未拥有 且 0 < 售价 ≤ 上限。结果按价格升序。

`--coupon` 把上限抬到「券额 + 满减面额」，并对过门槛的书标出券后价。这个价 `buy` 走新版订单通道自动用满减券抵扣，不用去 App 下单。券额 + 面额够不到门槛时不启用，会直接说明差多少。

默认只扫出版频道：出版类书最可能有整本价、适合花券；男频/女频多为连载按千字计价，没有整本价。要用全频道加 `--channels 92,10,68`。

券额小时 `afford` 返回 0 本是正常结果，不是故障。书城几乎没有几阅饼的书，等福利中心签到达标或攒够券再买。

### recommend / category / categories

```bash
python scripts/picker.py recommend                      # 按热门
python scripts/picker.py recommend --sort score         # 按好评
python scripts/picker.py recommend --sort update        # 按最新
python scripts/picker.py recommend --channels 92,10,68  # 三个频道都扫

python scripts/picker.py category 计算机
python scripts/picker.py category 推理悬疑        # 自动跨频道查找
python scripts/picker.py categories               # 列出所有分类名
```

`--sort` 对应官网分类页排序，三种结果完全不同（实测三套书单无重叠），值得都试。

官网分类页只给书名/作者/上架时间，价格要逐本回详情页查。`--top` 限制查价本数，默认按分类轮转取样（保证横跨各类，不是只查第一个分类）。分类 id 对照表见 `categories.md`。

官网分类页与 App 的推荐位/活动位不完全同步，结果反映官网分类页的当前快照。

### search / info

```bash
python scripts/picker.py search 乌合之众 --limit 400 --exact
python scripts/picker.py search 推理                      # 按题材关键词
python scripts/picker.py search 乌合之众 --douban         # 列表里附豆瓣评分
python scripts/picker.py info 10007034                    # 已知 book_id
```

`search` 按书名归组比价：同名多版本价格能差几倍，工具不按书名去重（否则会删掉最便宜那版），而是把同名版本聚成一组、按价升序。列表默认每本书三行：第一行价格与书名，第二行版本辨识三件套 `作者 · 译者 · 出版社` + ISBN + 掌阅评分（含评价人数），第三行简介（原文截前 160 字，可能断在句中，呈现前需按 SKILL.md「简介的呈现纪律」整理）。列表末尾会问是否加 `--douban` 查豆瓣评分：

```
◆ 同名 2 个版本，最低 398 阅饼
  1.    398 阅饼  ✅ 券够，可 0 元  乌合之众
       古斯塔夫·勒庞[著] · 亦言[译] · 中国友谊出版公司  ISBN 9787505745681  7.4分(228人)
       群体无意识现象在心理学群体研究中具有决定性作用…
  2.    599 阅饼  ✅ 券够，可 0 元  乌合之众
       古斯塔夫·勒庞[著] · 秦传安[译] · 新世界出版社  ISBN 9787510442124  8.5分(4926人)
       古斯塔夫·勒庞最著名的作品，社会学里程碑著作…
```

`info` 给单本书的完整书目（价格另起一行，附拥有状态与券能否全额抵扣；加 `--douban` 再多一行豆瓣评分）：

```
《乌合之众》
作者   古斯塔夫·勒庞[著]   亦言[译]
出版   中国友谊出版公司   ISBN 9787505745681
规格   10万字   417 KB   2024-12-09   共19章
评分   7.4 分（228 人评价）
豆瓣   6.2 分（1863 人评价）   https://book.douban.com/subject/30457109/
版权   创美时代
简介   《乌合之众》是一部讲透政治、经济、管理的心理学巨著…（超 420 字截断，--json 看全文）
封面   https://bookbk.img.zhangyue01.com/...
价格   398 阅饼
拥有   ❌ 未拥有
下单   售价 398 阅饼，券抵 398，自付 0 阅饼  ✅ 可零付
```

`detail()` 返回的全部字段（`--json` 可直接拿）：

| 字段 | 含义 | 字段 | 含义 |
|------|------|------|------|
| `name` | 书名 | `rating` / `rating_count` | 评分 / 评价人数 |
| `author` | 作者（保留 `[著]` 标记） | `chapters` | 章节数 |
| `translator` | 译者（`xxx[译]`，无译者为空） | `status` | `连载中` / `已完结` |
| `publisher` | 出版社 | `blurb` | 一句话推荐语 |
| `isbn` | 书号（ISBN-13/10，网文为空） | `intro` | 内容简介（全文） |
| `words` / `size` | 字数 / 文件大小 | `cover` | 封面图 URL |
| `pub_date` | 上架时间 | `brand` | 版权/品牌方 |
| `price` | 现价（`orig_price` 划线原价仍保留在数据里，仅不再显示） | `per_k` | 按千字计价（网文） |

字段缺失是正常的：网文没有出版社/ISBN，部分书没有评分或推荐语，此时对应字段为空串或 `None`，不要当成解析失败。简介是列表默认字段（原文截前 160 字，不按句子截断），数据跟详情页一起抓到，不额外发请求，因此列表不会变慢。`detail()` 一次请求拿全书目，补这些字段没有增加请求数，速度不变。

### 关于 ISBN

拿到的是纸书 ISBN，来自详情页 `<p>书号：…</p>`，随 `detail()` 一起返回，不需要额外请求。

| 情况 | 结果 |
|------|------|
| 出版频道纸质书 | 约 80% 有 ISBN（实测热门 40 本里 32 本有） |
| 男频/女频网文 | 一律没有（无纸质出版，字段为空串），不是抓取失败 |
| 格式 | 标准 13 位（少见 10 位），无连字符，部分可过校验位验证 |
| 能否用 ISBN 搜书 | 不能，掌阅搜索不索引 ISBN，只能按书名/作者搜 |

ISBN 不是唯一键：同一纸书被拆成多个电子条目时共用一个 ISBN。例如《平凡的世界（全3册）》与《平凡的世界（第一部）》ISBN 都是 `9787530216781`，但 book_id 不同、章节数不同（174 章 vs 58 章）。因此 ISBN 只能用来核对「是不是同一本书的不同版本」，绝不能当去重或匹配依据——判断唯一性永远只认 `book_id`。

`isbn_valid()` 会做校验位验证（ISBN-13 加权和 / ISBN-10 含 X），不通过时 `info` 会多打一行提示，但不会删掉数据，先如实展示，由用户判断。

### 选版本的判断规则

《聊斋志异》实测从免费到 3900 阅饼有多个版本；《乌合之众》同一书名下有 5 个以上版本，译者从「亦言」到「秦传安」各不相同，评分从 7.4 到 8.5 差距明显。因此：

- 去重只按 book_id，绝不按书名删条目。
- 同名版本聚组展示，组内按价格升序，标出最低价。
- 光看价格会买错版本，用列表第二行的 `作者 · 译者 · 出版社` 加评分对比。译著优先看译者（名家译本差价通常值），出版社影响排版校对质量，评价人数少的高分要打折看。拿不准就加 `--douban` 看豆瓣分——豆瓣样本通常大一个数量级，更接近大众口碑。

### 豆瓣评分 `--douban`

按 ISBN 去豆瓣查评分，交叉验证值不值得买。任何列表命令都支持，`info` 也支持：

```bash
python scripts/picker.py search 乌合之众 --douban          # 列表里附豆瓣分
python scripts/picker.py info 10007034 --douban            # 单本追加豆瓣行
python scripts/picker.py recommend --douban --douban-top 30  # 限 30 本
```

实现：请求 `https://book.douban.com/isbn/<isbn>/`，豆瓣 302 跳到 `subject/<id>/` 页，从页面抓 `v:average`（分数）与 `v:votes`（人数）。不使用已废弃的 `api.douban.com/v2`（实测返回 400）。掌阅分与豆瓣分并列显示：

```
  1.    398 阅饼  ✅ 券够，可 0 元  乌合之众
       古斯塔夫·勒庞[著] · 亦言[译] · 中国友谊出版公司  ISBN 9787505745681  7.4分(228人)  豆瓣 6.2(1863人)
```

掌阅 7.4 分（228 人）vs 豆瓣 6.2 分（1863 人），豆瓣样本大 8 倍，说明这本书在更广读者里评价平平；只信掌阅分会误判。优先看评价人数多的那个，再看分数。若列表出现「豆瓣匹配到不同版本」提醒，说明该 ISBN 跨卷册，豆瓣分只代表整套书，不能当这一版的分。

限制：

| 事项 | 说明 |
|------|------|
| 覆盖率 | 抽样 15 本，10 本拿到评分；无评分多为豆瓣评价人数不足 |
| 网文 | 无 ISBN，跳过查询（不会白跑请求），列表也不显示豆瓣列 |
| 限速 | 并发 4 + 每次 0.5s；默认只查前 20 本（`--douban-top` 可调） |
| 失败可降级 | 豆瓣不可达/被拦时只影响豆瓣字段，掌阅数据照常返回，不会整体失败 |
| 不使用 | 不登录、不用 Cookie、不写任何豆瓣数据，纯只读公开页 |

`book.douban.com/isbn/<isbn>/` 是 302 跳转，查 1 本书客户端会发出 2 次 HTTP 请求，`--douban-top 20` 大约发出 40 次请求。评分和简介都在 subject 页同一份 HTML 里、由同一次请求返回，但工具只解析评分、评价人数、书名、链接，不解析也不返回豆瓣简介；少解析一段正文不会减少请求数，限流风险不变。轻量替代通道 `j/subject_rating_info`、`j/subject_abstract`、`m.douban.com/rexxar/api/v2/book/*` 已验证全部不可用（限流期间 403，且 `api.douban.com/v2` 早已返回 400）。

豆瓣按 IP 限流且恢复极慢：一次集中测试约 60~80 次请求（含跳转约 120~160 次）后触发，冷却 20 秒 / 150 秒 / 5 分钟 / 16 分钟（4 次探测）/ 20 分钟（PC 站 + 移动站）/ 约 25 分钟复测，全部 `403`。表现有三种：`403`、`429`、或 `200` 但只有 3KB 的反爬壳页（正常页 11~13 万字节）。换 UA、换 `m.douban.com` 子域名都没用。脚本一旦发现限流就置 `limited=True` 并中断后续请求，默认限量 20 本，这个保护性默认值不要随手调到几百。命令行提示：

```
⚠️  3 本被豆瓣限流（403/429）。豆瓣按 IP 封，冷却往往要十几分钟以上，建议稍后再试或减少 --douban-top。
```

需要批量查几十本以上，自己加本地缓存（ISBN → 评分），别硬刷。

因为 ISBN 不是唯一键，《平凡的世界（第一部）》和《第二部》共用 ISBN，豆瓣只会返回整套书的评分 9.0，两本显示同一个分，这不是 bug。脚本会做书名比对（`_title_similar()`，去括号副标题与卷册后缀后互判包含），不一致时列表下方与 `info` 里都会打印提醒：

```
⚠️  《平凡的世界（第一部）》豆瓣匹配到不同版本：豆瓣同名书为《平凡的世界》，评分可能不是这一版
```

看到这类提醒时，豆瓣分只能当参考，不能当这一版的准确评分。完整接口与降级策略见 `douban.md`。

## 4. 写操作命令

### buy

分两步，先询价后下单：

```bash
python scripts/picker.py buy 10007034                          # 只看询价，不扣费
python scripts/picker.py buy 10007034 --confirm                # 真实下单，买后自动加书架
python scripts/picker.py buy 10007034 --confirm --max-voucher 100   # 限额保护
python scripts/picker.py buy 10007034 --confirm --no-shelf     # 下单但先不加书架
python scripts/picker.py buy 10007034 --confirm --folder 外国经典文学   # 买完直接归夹
python scripts/picker.py buy 10007034 --ignore-coupon          # 不使用满减券，按活动价原价买
```

- 不加 `--confirm` 绝不扣券，只做试算询价。
- 已拥有的书会直接拦住，不会重复购买。
- **自动使用满减券**：走新版订单通道，达到门槛的满减券直接抵扣，无需手动勾选。
- 余额不足（代金券 + 阅饼 < 折后应付）时会拦住，并说明还差多少。
- 下单成功后自动调用加书架（掌阅「购买」与「加书架」是两步）。
- 这套下单流程已实测买下过书，完整接口细节见 `api.md` 第 9b 节。

**询价输出示例**（《深宅活寡》实测）：

```text
=== 订单询价 === 《深宅活寡》
标价        2499 阅饼
活动价      1299 阅饼
满减券      200 阅饼（满1000可用，code=630019）
折后应付    1099 阅饼
  ├ 代金券  1099 阅饼
  └ 阅饼    0 阅饼
账上代金券  1099 阅饼
```

**价格链路**：标价 → 活动价（平台折扣）→ 减满减券面额 → 折后应付；折后应付由代金券与阅饼共同抵扣。

**满减券按折后价判门槛**：门槛比的是活动价（`dis_price`），不是标价。例如某书活动价 999、门槛 1000，虽然标价 2799，这张券其实用不上，脚本会自动跳过。

**`--ignore-coupon`**：不使用满减券，按活动价全额扣代金券。想留券给别的书时用。

代金券必须全额覆盖售价：不能部分抵扣、也不能与阅饼/现金混合支付。券不足时订单页只显示「余额不足」，连支付按钮都不给。所以想 0 元买书，必须选售价 ≤ 手上券总额的书。满减券不改变这条：它不参与 `Order.Create` 的试算，页面显示的「需支付」永远等于售价全额。

新版通道返回的 `token` 是一次性询价令牌，价格封在服务端。试算与下单必须连续，中间别再试算。

已拥有状态必须用下单接口判断：书架（`bookshelf/list`）只收录同书多个 ID 中的一个，详情页也完全不反映拥有状态（已购书照样显示原价）。唯一可靠判据是 `order.php?Act=getOrderTmpInfo` 的 `Charging.IsAsset`：

| `IsAsset` | `FeeType` | 含义 |
|-----------|-----------|------|
| `1` | `-1` | 已拥有 |
| `0` | `3` | 可购买 |
| `0` | `-1` | 免费书 |

脚本已内置这层复核。

### shelf

```bash
python scripts/picker.py shelf 10007034                      # 加进云书架
python scripts/picker.py shelf 10007034 --dry                # 只预览
python scripts/picker.py shelf 10007034 --name "历史的荒谬"   # 指定显示名
python scripts/picker.py shelf 10007034 --folder 外国经典文学 # 一步到位直接归夹
```

已购但漏了加书架时用，幂等——已在书架会直接跳过。`--folder` 指定的夹不存在时会自动建。

### shelves

```bash
python scripts/picker.py shelves                       # 文件夹清单 + 各夹书数 + 未归类数
python scripts/picker.py shelves --books               # 连每本书名一起列
python scripts/picker.py shelves --folder 科幻 --books # 只看某个夹
python scripts/picker.py shelves --json                # 拿全量结构（含每本书的 book_id）
```

输出示例（结构示意）：

```
书架 200 本，13 个文件夹，version N

    54 本   外国经典文学
    42 本   已阅
    30 本   中国当代文学
   ...
未归类 4 本（不在任何文件夹里）
```

`shelves --books` 能列出每本书的 `book_id`，这个 id 就是 `move` 要用的参数。

书架的数据结构：`cloud/bookshelf/list` 返回的 `body.data` 是一个扁平数组，书和文件夹混在一起，靠 `dtype` 区分。

| 条目 | `dtype` | 识别特征 | 归属字段 |
|------|---------|----------|----------|
| 书 | `0` | 有 `book_name`；站内书是数字 `book_id`，本地导入书是 64 位 hash | `folder_hierarchy` = `"[\"外国经典文学\"]"` 或 `"[]"` |
| 文件夹 | `1` | `book_name` 为空、8 位十六进制 `book_id` | `folder_hierarchy` 即夹名本身 |

判据只认 `dtype`，不要拿 `mark` 判断：文件夹节点带 `mark="A_1"`，但本地导入书也带 `A_1`，站内书才是 `mark=""`。本地导入书（`book_type=1`、`is_local_book=true`）同样能用 `move` 改归属，已实测通过。

因此「移动书」不是搬节点，只是把书那一条的 `folder_hierarchy` 改掉再写回去。多级目录用 `["一级","二级"]` 表示，本机账号实测只有一级。

### move

```bash
python scripts/picker.py move 11582366 --to 科幻 --dry   # 只预览
python scripts/picker.py move 11582366 --to 科幻          # 确认后写入
python scripts/picker.py move 11582366                   # --to 留空 = 移出到未归类
python scripts/picker.py move 111 222 333 --to 已阅       # 一次移多本
python scripts/picker.py move 11582366 --to 新夹 --create # 夹不存在时自动新建
```
- 目标夹不存在会直接报「没有「X」这个文件夹」并列出全部现有夹名，不会偷偷建夹；要建就加 `--create` 或先 `mkdir`。
- 书已在目标夹、或 book_id 不在书架，会分别标 `已在该文件夹` / `不在书架里` 跳过，不写入。
- 一次移动多本时只发一次 upsert 请求。
- 写完会重新读书架复核 `folder_hierarchy` 是否真的落库，并打印 `已移动 N/M 本`。
- `--to` 是精确夹名，留空表示移出到未归类（`folder_hierarchy` 写成 `[]`）。

### mkdir / rmdir

```bash
python scripts/picker.py mkdir 待读
python scripts/picker.py rmdir 待读
python scripts/picker.py rmdir 待读 --force   # 夹里还有书时，先把书移出到未归类再删
python scripts/picker.py rmdir 待读 --dry     # 预览
```

`rmdir` 默认拒绝删非空文件夹：只删节点不删书，会让那些书带着一个已不存在的夹名，比留着更乱。`--force` 会先把夹里的书全部移到未归类、再删节点，不会丢书。幂等：重复 `mkdir` 直接跳过，删不存在的夹会明确报错。

### 买完直接归到对应文件夹

`buy` 和 `shelf` 都支持 `--folder`。买书成功后自动加书架的那一步会直接带上 `folder_hierarchy`，等于「加书架 + 移书」一次做完，不用再补一次 `move`。夹不存在会自动建。

### 书架写入的实测结论

| 事项 | 结论 |
|------|------|
| `upsert` 的 `type` | `1` 新增插入、`2` 删除、`3` 更新，三个都真实跑通过 |
| `current_version` | 乐观锁，每写一次 +1。连续写之间必须重新读书架拿新版本，否则返回 `100006 version not equal error` |
| 服务端自动建夹？ | 不会。把某本书的 `folder_hierarchy` 写成一个不存在的夹名，服务端能存下，但 `dtype=1` 节点不存在，书架里看不到这个夹。建夹必须显式插节点 |
| 夹名匹配 | 精确匹配，不做模糊；写错名字不会自动纠正，建议先 `shelves` 拿准确名字 |
| 已有夹的 `id` | 不必关心，移动只用名字；`shelves` 里 `id` 为空说明该夹只是书上挂的名字、没有独立节点（不该出现，除非手工写坏） |

移动是纯归类调整，不涉及钱、不改变已购状态，但仍是写操作：批量整理前先跑一次 `--dry` 看清单。

## 5. 输出格式约定

- 默认人类可读文本；加 `--json` 得结构化结果（含全部书目字段）。
- 列表每本书三行：第一行价格与书名；第二行 `作者 · 译者 · 出版社  ISBN  评分  [豆瓣分]`；第三行简介（原文截前 160 字，无简介的书没有第三行）。第三行常断在句中，向用户呈现前必须按 SKILL.md「简介的呈现纪律」整理成完整句子。
- 列表不显示划线原价和 book_id（数据仍在 `--json` 里，只是不占版面）；书名重复时靠第二行区分版本。
- ISBN 只有出版类纸质书才有，网文第二行不会出现 ISBN，属正常。
- 列表末尾会提示可加 `--douban` 查豆瓣评分（`--json`、已加 `--douban`、无命中时不提示）。
- 想看全量书目用 `info <book_id>`（简介超 420 字会截断，`--json` 拿全文）。
- 想看豆瓣分用 `--douban`（`--json` 里在 `douban` 字段，含分数/人数/链接/同名提醒）。
- `--douban` 是在原有流程之后串行追加的，不影响掌阅侧的抓取速度。

## 6. 速度参考（8 并发）

| 操作 | 耗时 |
|------|------|
| `login`（密码登录） | ~3 秒 |
| `balance` | ~2 秒 |
| `coupons` | ~2 秒 |
| `category`（单分类） | ~9 秒 |
| `recommend --top 200` | ~15 秒 |
| `afford --top 600` | ~40 秒 |
| `afford --full`（全 42 分类 ≈9200 本） | ~10 分钟 |
| `buy`（询价或下单） | ~5 秒 |
| `shelves` / `move`（单次） | ~2 秒 |
| `--douban` 附加 | 每本约 0.3 秒（并发 4 + 限速 0.5s；查 20 本约 +6 秒） |

## 7. 常见问题

券不够任何书怎么办？先跑 `balance` 看可用总额。书城几乎没有几阅饼的书，券额小时 `afford` 返回 0 本是正常结果，不是故障。等福利中心签到达标、或攒够券再买。

我明明有「满 1000 减 200」，为什么还是显示余额不足？先看活动价够不够门槛——满减券门槛比的是活动价（`dis_price`），不是标价。若活动价已 ≥ 1000 且券后价仍在代金券额度内，`buy` 会自动用上这张券；提示余额不足说明「活动价 − 200」超过了你手上的代金券。查券用 `coupons`。

为什么 `afford` 默认只扫出版频道？出版类书最可能有整本价、适合花券；男频/女频多为连载按千字计价，没有整本价。要用全频道加 `--channels 92,10,68`。

结果和 App 里看到的不一致？官网分类页与 App 的推荐位/活动位不完全同步。本工具反映官网分类页的当前快照。

登录报「签名私钥不匹配」？说明请求用的私钥不对。登录签名必须用 `scripts/native_keys.json` 里的第 4 把客户端私钥（下标 3），这是掌阅客户端实测唯一通过校验的一把，脚本已固定。

书目里有字段是空的（没出版社/没译者/没评分）？正常。网文（男频/女频）没有出版社和 ISBN；没人评分的书 `rating` 为空；不是每本书都有官方推荐语。空值不等于抓取失败。

怎么判断同名书该买哪版？看列表第二行：`作者 · 译者 · 出版社` + 评分人数。译著优先看译者（名家译本差价通常值），出版社影响排版校对质量，评价人数少的高分要打折看。拿不准就加 `--douban` 看豆瓣分——豆瓣样本通常大一个数量级，更接近「大众口碑」。

豆瓣查不到分 / 显示「—」？三种原因，都不是故障：① 这是网文，没 ISBN，直接跳过；② 豆瓣有这本书但评价人数不足，页面写「评价人数不足」；③ 豆瓣未收录该 ISBN（返回 404）。豆瓣不可达时也只影响豆瓣字段，其余数据照常显示。

豆瓣分和掌阅分差很多，信哪个？优先看评价人数多的那个，再看分数。掌阅评分常只有几十到几百人，豆瓣往往上千人。实测《乌合之众》掌阅 7.4 分（228 人）、豆瓣 6.2 分（1863 人）——样本差 8 倍时，豆瓣更接近真实口碑。若列表出现「豆瓣匹配到不同版本」提醒，说明该 ISBN 跨卷册，豆瓣分只代表整套书，不能当这一版的分。

移动书会重复购买 / 会扣券吗？不会。`move` 只调 `cloud/bookshelf/upsert` 改 `folder_hierarchy`，不碰订单和余额，也不改变已购状态。但它确实是写操作，批量整理前用 `--dry` 看清清单。

为什么 `move` 报「没有这个文件夹」？夹名是精确匹配，错一个字都不行。跑 `shelves` 看准确名字。想让脚本顺手建夹就加 `--create`。

把书移到一个不存在的夹名会怎样？书上的字段能写进去，但服务端不会补建 `dtype=1` 节点，`shelves` 里会看到一个 `id` 为空的「幽灵夹」，掌阅 App 里也看不到它。所以要先 `mkdir` 或用 `--create`。发现这种残留可以用 `rmdir <夹名> --force` 把书移出并清干净。

删文件夹会不会把书一起删掉？不会。`rmdir` 只删文件夹节点，书仍在书架里。非空夹默认直接拒绝；`--force` 会把夹里的书移到未归类再删节点，一本都不会丢。

连续移动/建夹时报 `100006 version not equal error`？`current_version` 是乐观锁，每写一次 +1。脚本内部连续写之间已重新读书架取新版本；手动拼请求时容易漏这一步。

凭证突然失效（查余额变匿名页）？zysid 有有效期，过期后重新 `login` 一次即可刷新 config.json。
