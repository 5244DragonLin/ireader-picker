---
name: ireader-picker
description: 掌阅书城选书、比价与购书助手。用于查阅饼余额、代金券与满减券，按可用券额筛出能零付拿下的书，按热度/好评/分类推荐，按书名检索并对比同名版本，按 ISBN 查豆瓣评分，以及下单购买。附带云书架整理能力（查看文件夹结构、移动书籍、新建删除文件夹、买完自动归夹）。当用户询问掌阅余额、书价、书目信息、选书建议，或要求购买、加书架、整理书架归类时使用本技能。下单默认只询价，须经确认才扣券。
license: MIT
author: DragonLin
agent_created: true
---

# ireader-picker：掌阅选书购书助手

## 用途

把「账上有多少钱 → 这些钱能白拿哪些书 → 值不值得买 → 直接买下」串成一条命令链路；买完可顺手归到书架对应文件夹，但那是附带能力，不是主线。

核心脚本 `scripts/picker.py`，纯 Python 标准库；仅密码登录需要 `cryptography`，查书、查价、下单都不需要。除价格外，每本书还能取到作者、译者、出版社、ISBN、字数、文件大小、上架时间、评分与评价人数、章节数、连载状态、推荐语、内容简介、封面链接、版权方。

查询类命令只读。`buy` 是唯一涉及钱的写操作，默认只询价，必须 `--confirm` 才扣券。`shelf` / `move` / `mkdir` / `rmdir` 改书架结构，都支持 `--dry` 预览。

## 何时使用

- 查掌阅阅饼余额、代金券与满减券余额及到期日。
- 按可用券额筛出能零付买下的书，按热度、好评、分类或书名找书。
- 查某本书的价格、书目信息、是否买过；对比同名书的不同版本。
- 按 ISBN 查豆瓣评分，交叉验证口碑。
- 下单购买、把已购书补进云书架。
- 查看书架文件夹结构与各夹书数，把书移动到文件夹，新建或删除文件夹，买完自动归到指定文件夹。
- 登录、换账号、刷新失效凭证。

## 前置：凭证

| 命令 | 凭证 |
|------|------|
| `category` / `search` / `categories` / `info` 的价格 | 不需要（匿名可查） |
| `balance` / `coupons` / `afford` / `recommend` 的默认额度与已拥有判断 | 需要 |
| `buy` / `shelf` / `shelves` / `move` / `mkdir` / `rmdir` | 需要 |

没有凭证、凭证过期或换账号时执行 `python scripts/picker.py login <手机号>`，密码隐藏输入，成功后自动写入 config.json。`config.json` 含凭证，不要提交到任何仓库（已在 `.gitignore`）。zysid 有有效期，失效后重新登录一次。

其余提供方式（命令行 `--auth`、环境变量 `IREADER_USR` / `IREADER_ZYSID`、config.json）的优先级、登录私钥要求与退出码见 `references/commands.md` 第 1 节。

## 按意图选命令

```
登录/换号/凭证过期          → login <手机号>
有多少钱/券啥时候过期       → balance
有满减券吗/满多少减多少     → coupons
这些钱能买啥/能白拿哪些     → afford [--coupon]；再加 recommend 按热度排序
有什么推荐/哪个分类好看     → recommend --sort download|score|update；category <分类名>
《某书》多少钱/我买过没     → info <book_id>；不知道 id 时先 search <关键词>
买下这本/下单              → buy <book_id> 询价 → 报给用户 → 确认后 buy <book_id> --confirm
                            买完直接归夹：在 --confirm 后加 --folder <夹名>
书架有哪些文件夹/各夹几本   → shelves；shelves --folder 科幻 --books
把书移到某夹               → move <book_id> --to <夹名> --dry 预览 → 去掉 --dry 写入
                            --to 留空表示移出到未归类
新建/删除文件夹            → mkdir <名> / rmdir <名> [--force]
```

## 命令速查

所有命令以技能根目录为工作目录执行；加 `--json` 得结构化结果。完整参数、输出示例与常见问题见 `references/commands.md`。

| 命令 | 作用 | 常用参数 |
|------|------|---------|
| `login <手机号>` | 密码登录并写 config.json | `--password` / `--no-save` |
| `balance` | 阅饼 + 代金券（含到期日）+ 满减券摘要 | |
| `coupons` | 满减券门槛与有效期 | `--kind book\|goods` |
| `afford` | 列出可零付买下的书 | `--limit` / `--coupon` / `--full` / `--channels` |
| `recommend` | 按热门、好评或最新推荐 | `--sort` / `--limit` / `--top` |
| `category <名>` / `categories` | 按分类推荐 / 列出分类名 | `--sort` / `--status` |
| `search <关键词>` | 按书名或题材检索，同名版本归组比价 | `--exact` / `--douban` |
| `buy <book_id>` | 询价；`--confirm` 才真扣券 | `--confirm` / `--max-voucher` / `--no-shelf` / `--folder` / `--ignore-coupon` |
| `info <book_id>` | 单本完整书目、价格、拥有状态、折后应付与券抵扣 | `--douban` |
| `shelf <book_id>` | 把已购书补进云书架 | `--name` / `--folder` / `--dry` |
| `shelves` | 书架文件夹结构与各夹书数（只读） | `--books` / `--folder` |
| `move <book_id>...` | 把书移到文件夹 | `--to` / `--create` / `--dry` |
| `mkdir <夹名>` | 新建文件夹 | `--dry` |
| `rmdir <夹名>` | 删除文件夹 | `--force` / `--dry` |

列表命令通用开关：`--json` / `--auth` / `--workers` / `--douban` / `--douban-top`，写在子命令前后都行。列表默认给出书名、作者、出版社、简介、掌阅评分，并在末尾询问是否查豆瓣评分。

## 简介的呈现纪律

脚本输出的简介是原文硬截前 160 字，**经常断在句子中间**。直接照搬给用户是不可接受的，必须由你（大模型）判断后整理：

1. **判断是否完整**：读脚本给出的简介片段，看末字是否落在句末标点（`。！？…；` 等）上、语义是否收尾。落在句末且意思说圆了，可原样引用。
2. **断在句中就放宽窗口**：宁可多给几个字，也要让简介停在完整句子上。片段不够判断时，用 `--json` 取该书 `intro` 全文（`info <book_id> --json` 或列表 `--json`），从中摘出完整的 1~2 句。
3. **遵守长度预算**：单本简介呈现 100~160 字为宜，最多不超过 220 字；多本列表时按本数适当压缩，保证整体可读。
4. **不要编造**：只做截取、拼接、去口水话，不得添加原文没有的情节、评价或卖点。
5. **标注来源差异**：`blurb`（掌阅推荐语，多为营销文案）与 `intro`（内容简介，更客观）不是一回事，用户问"讲什么"时优先用 `intro`。

## 写操作纪律

`buy` 改账户余额；`shelf` / `move` / `mkdir` / `rmdir` 改书架结构。执行时守以下几条：

1. 先跑不带 `--confirm` 的询价，把售价、折后应付、代金券抵扣额报给用户看。
2. 拿到用户明确同意后再加 `--confirm`，不要自作主张下单。
3. 下单失败时如实报告返回的 `code` / `msg`，不要伪造成功。
4. 买后校验会打印 `IsAsset`，若仍显示未拥有要如实说明。
5. 不要用 `--confirm` 做测试，每一次都是真实扣券。
6. 批量整理书架前先跑 `--dry`，把要动的 book_id 与书名清单给用户过一遍；单个 `move` 也要先确认目标夹名（精确匹配，写错不会纠正）。
7. 删非空文件夹默认拒绝；确需 `--force` 时先说明这些书会被移到未归类。
8. `buy` 会自动使用满减券（走新版订单通道）。若想按原价购买、不下满减券，加 `--ignore-coupon`。只需向用户说明「本次用了满减券、省了多少」，无需再让用户去 App 操作。

## 关键约束

以下条目直接影响判断，执行前先确认；接口证据与完整实测数据在 `references/api.md` / `references/douban.md`。

| 约束 | 内容 |
|------|------|
| 满减券可用（新版通道） | `buy` 走新版订单通道（`/trade/order/pay`），满减券自动抵扣，代金券与阅饼可混合支付。可买条件为「代金券 + 阅饼 ≥ 折后应付」。旧通道（`Order.Create`/`Order.Pay`）才必须券全额覆盖，脚本已不用它 |
| 满减券按折后价判门槛 | 满减券门槛比的是**活动价**（`dis_price`），不是标价。活动价已低于门槛时券用不上，`buy` / `info` 都已按此判断 |
| 新版下单不需要签名 | `POST /trade/order/pay` 的 body 只需 6 个字段（`type` / `token` / `price` / `dis_price` / `bid` / `coupon_code`），`usr`+`zysid` 放在 URL query 即可。签名逻辑虽在前端代码里引用（`do_sign` 调原生），但 Web 端链路并未实际校验 |
| `token` 一次性 | 新版试算返回的 `token` 是一次性询价令牌，价格封在服务端；试算与下单必须连续 |
| 拥有状态只认 `IsAsset` | 详情页不反映拥有状态，书架只收录同书多 ID 中的一个。唯一可靠判据是 `getOrderTmpInfo` 的 `Charging.IsAsset`，`1` 为已拥有 |
| 同名不等于同一本 | 去重只按 `book_id`，绝不按书名删条目；靠列表第二行的「作者 · 译者 · 出版社」与评分人数辨别版本。ISBN 也不是唯一键，只能用来核对版本，判断唯一性只认 `book_id` |
| 书架归类只看 `dtype` 与 `folder_hierarchy` | 书架是扁平数组，移动书只是改该书条目的 `folder_hierarchy`，不是搬节点。文件夹节点 `dtype=1`、书 `dtype=0`；`mark="A_1"` 两者都可能出现，不能当判据 |
| `current_version` 每写一次 +1 | 连续写之间必须重新读书架取新版本，否则返回 `100006 version not equal error`。`upsert` 的 `type`：`1` 新增、`2` 删除、`3` 更新 |
| 服务端不自动建文件夹 | 书的 `folder_hierarchy` 指向未登记的夹名时值能存下，但没有 `dtype=1` 节点，App 里看不到该夹。建夹须用 `mkdir` 或 `move --create` |
| 豆瓣按 IP 限流且恢复极慢 | 默认只查前 20 本（`--douban-top`），并发 4 + 每次 0.5s。触发限流后冷却十几分钟以上仍可能 403，不要调大限量；批量查询自行加本地缓存 |
| 满减券与代金券是两套 | 代金券 1:1 抵阅饼、自动扣；满减券「满 X 减 Y」、达到门槛才减，`buy` 下单时自动使用（新版通道），要按原价买加 `--ignore-coupon`。查券用 `coupons`，算券后价用 `afford --coupon` |

## 参考资料索引

按需读取，不要一次全部加载。

| 文件 | 何时读 |
|------|--------|
| `references/commands.md` | 查某个命令的完整参数、输出示例、版本挑选规则、速度表、常见问题 |
| `references/api.md` | 排查接口异常、扩展功能、确认字段语义与下单/书架写入细节 |
| `references/douban.md` | 豆瓣限流、抓取字段、返回结构、降级策略 |
| `references/categories.md` | 全部分类 id 对照表 |
| `scripts/picker.py` | 改逻辑时直接读。密码登录在 `password_login()`；豆瓣在 `douban_by_isbn()` / `douban_many()`；书架结构在 `shelf_tree()` / `shelf_layout()`，归夹在 `shelf_move()` / `shelf_mkdir()` / `shelf_rmdir()` / `_upsert_shelf()` |

`commands.md` 与 `api.md` 篇幅较长，用 `grep -n '^## ' references/commands.md` / `grep -n '^## ' references/api.md` 先定位小节，不要整份加载。
