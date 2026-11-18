---
name: ireader-picker
description: 掌阅书城选书、比价与购书助手。用于查阅饼余额、代金券与满减券，按可用券额筛出能零付拿下的书，按热度/好评/分类推荐，按书名检索并对比同名版本，按 ISBN 查豆瓣评分，推荐淘书市当期活动书目中叠加满减券后可购买的书，下单购买，查看/清理/加入购物车（含下架书标记）。附带云书架整理能力（查看文件夹结构、移动书籍、新建删除文件夹、买完自动归夹）。也支持「我的书单」全套管理：查看我创建/收藏的书单、创建与编辑书单、往书单加书或移出、删除书单、收藏别人的书单。当用户询问掌阅余额、书价、书目信息、选书建议、淘书市活动券后可买书目，或要求购买、加书架、整理书架归类、加购物车、清理购物车，或要求创建/编辑/管理书单时使用本技能。下单默认只询价，须经确认才扣券。
license: MIT
author: DragonLin
agent_created: true
---

# ireader-picker：掌阅选书购书助手

## 用途

把「账上有多少钱 → 这些钱能白拿哪些书 → 值不值得买 → 直接买下」串成一条命令链路；买完可顺手归到书架对应文件夹，但那是附带能力，不是主线。

核心脚本 `scripts/picker.py`，纯 Python 标准库；仅密码登录需要 `cryptography`，查书、查价、下单都不需要。除价格外，每本书还能取到作者、译者、出版社、ISBN、字数、文件大小、上架时间、评分与评价人数、章节数、连载状态、推荐语、内容简介、封面链接、版权方。

查询类命令只读。`buy` 是唯一涉及钱的写操作，默认只询价，必须 `--confirm` 才扣券。`shelf` / `move` / `mkdir` / `rmdir` 改书架结构，都支持 `--dry` 预览。买完书会自动从书架里已存在的自建文件夹中挑最合适的一个归类；没有文件夹或没有明确合适的，保持未归类。

## 何时使用

- 查掌阅阅饼余额、代金券与满减券余额及到期日。
- 按可用券额筛出能零付买下的书，按热度、好评、分类或书名找书。
- 查淘书市当期活动（约一月两期）：列出当期满减券面额与门槛，推荐活动书目里「叠加淘书市券 + 账上代金券」后自付 ≤ 券额（含 0 元）能买的书。领券本身走姊妹技能 ireader_welfare（`taoshushi` 命令）。
- 查某本书的价格、书目信息、是否买过；对比同名书的不同版本。
- 按 ISBN 查豆瓣评分，交叉验证口碑。
- 按作者的任一作品查作者主页：确认作者身份、看名下全部作品（比按作者名搜索更全，能带出搜索漏掉的挂名书）。
- 搜用户创建的书单：书单 tab 的数据（书单名/描述/标签/收藏数/含书数），并可看某个书单里收了哪些书。
- 管理「我的书单」：查看我创建/我收藏的书单，创建书单（晒书单/求书单）、改名称与描述、往书单加书（可带推荐理由）、把书移出书单、删除书单、收藏别人的书单。
- 下单购买、把已购书补进云书架。
- 查看书架文件夹结构与各夹书数，把书移动到文件夹，新建或删除文件夹，买完自动归到指定文件夹。
- 查看购物车（含下架/失效标记）、清理购物车里的死书、把书加入购物车。
- 登录、换账号、刷新失效凭证。

## 前置：凭证

| 命令 | 凭证 |
|------|------|
| `category` / `search` / `categories` / `info` 的价格 | 不需要（匿名可查） |
| `balance` / `coupons` / `afford` / `recommend` 的默认额度与已拥有判断 | 需要 |
| `taoshu` 活动解析与书价 | 不需要；有凭证时可排除已拥有、且默认额度取真实券额 |
| `buy` / `shelf` / `shelves` / `move` / `mkdir` / `rmdir` | 需要 |
| `cart` / `cartdel` / `cartadd` | 需要（另需 cryptography：签名用） |
| `mybl` / `blnew` / `bledit` / `bladd` / `blrm` / `bldel` / `blfav` / `blsuggest` | 需要（另需 cryptography：签名用） |

没有凭证、凭证过期或换账号时执行 `python scripts/picker.py login <手机号>`，密码隐藏输入，成功后自动写入 config.json。`config.json` 含凭证，不要提交到任何仓库（已在 `.gitignore`）。zysid 有有效期，失效后重新登录一次。

其余提供方式（命令行 `--auth`、环境变量 `IREADER_USR` / `IREADER_ZYSID`、config.json）的优先级、登录私钥要求与退出码见 `references/commands.md` 第 1 节。

## 按意图选命令

```
登录/换号/凭证过期          → login <手机号>
有多少钱/券啥时候过期       → balance
有满减券吗/满多少减多少     → coupons
这些钱能买啥/能白拿哪些     → afford [--coupon]；再加 recommend 按热度排序
淘书市这期能买啥/券后书目   → taoshu；先看当期券 → taoshu --show-coupons
                              领券用 ireader_welfare 的 taoshushi 命令
有什么推荐/哪个分类好看     → recommend --sort download|score|update；category <分类名>
《某书》多少钱/我买过没     → info <book_id>；不知道 id 时先 search <关键词>
搜书带评分/分类（不查价）   → bsearch <关键词> [--page N|--all]
作者是谁/名下还有哪些书     → author <该作者任一 book_id>
有哪些相关书单/看某个书单   → blsearch <关键词> [--page N|--all] → booklist <书单id>
我的书单里都有啥            → mybl；mybl --books 连书目一起列
我收藏了哪些书单            → mybl --fav
建个书单/新建书单           → blnew <名称> --desc <描述> [--qiu] [--add bid:理由]
改书单名/描述               → bledit <书单id> --name 新名 --desc 新描述
往书单里加书                → blsuggest <关键词> 拿 id → bladd <书单id> <bid>... [--reason 理由]
                            批量加前先 bladd ... --dry 预览
把书移出书单                → blrm <书单id> <bid>... 预览 → 加 --yes 执行
删掉整个书单                → bldel <书单id>... 预览 → 加 --yes 执行
收藏/取消收藏别人的书单     → blfav <书单id> [--off]
买下这本/下单              → buy <book_id> 询价 → 报给用户 → 确认后 buy <book_id> --confirm
                            买完直接归夹：在 --confirm 后加 --folder <夹名>
书架有哪些文件夹/各夹几本   → shelves；shelves --folder 科幻 --books
把书移到某夹               → move <book_id> --to <夹名> --dry 预览 → 去掉 --dry 写入
                            --to 留空表示移出到未归类
新建/删除文件夹            → mkdir <名> / rmdir <名> [--force]
购物车有啥/哪些下架了      → cart；cart --recd 看基于购物车的推荐
把书移出购物车             → cartdel <book_id> 预览 → --yes 执行
把书加入购物车             → cartadd <book_id>（已在购物车会提示 201）
```

## 命令速查

所有命令以技能根目录为工作目录执行；加 `--json` 得结构化结果。完整参数、输出示例与常见问题见 `references/commands.md`。

| 命令 | 作用 | 常用参数 |
|------|------|---------|
| `login <手机号>` | 密码登录并写 config.json | `--password` / `--no-save` |
| `balance` | 阅饼 + 代金券（含到期日）+ 满减券摘要 | |
| `coupons` | 满减券门槛与有效期 | `--kind book\|goods` |
| `afford` | 列出可零付买下的书 | `--limit` / `--coupon` / `--full` / `--channels` |
| `taoshu` | 淘书市当期书目：叠加满减券后自付 ≤ 上限的书 | `--show-coupons` / `--limit` / `--act` / `--top` |
| `recommend` | 按热门、好评或最新推荐 | `--sort` / `--limit` / `--top` |
| `category <名>` / `categories` | 按分类推荐 / 列出分类名 | `--sort` / `--status` |
| `search <关键词>` | 按书名或题材检索，同名版本归组比价 | `--exact` / `--douban` |
| `buy <book_id>` | 询价；`--confirm` 才真扣券；买完自动归夹 | `--confirm` / `--max-voucher` / `--no-shelf` / `--folder` / `--no-auto-folder` / `--ignore-coupon` |
| `info <book_id>` | 单本完整书目、价格、拥有状态、折后应付与券抵扣 | `--douban` |
| `author <book_id>` | 按任一作品查作者主页：作者简介 + 名下全部书单（带价） | `--json` |
| `blsearch <关键词>` | 搜用户创建的书单（含书数/收藏数/标签/描述）+ 作者卡 + 相关搜索；可翻页 | `--page N` / `--all` / `--json` |
| `bsearch <关键词>` | 书城搜书（App 多栏接口：评分/分类/完结状态，不查价）；可翻页 | `--page N` / `--all` / `--json` |
| `booklist <书单id>` | 书单详情：书单元信息 + 全书目（书名/作者/评分/推荐理由，下架书打标） | `--sale`（只看在售） / `--json` |
| `mybl` | 我的书单列表（我创建 / 我收藏），自动翻页 | `--fav` / `--books` |
| `blnew <名称>` | 创建书单（晒书单；`--qiu` 求书单） | `--desc`（必填）/ `--qiu` / `--add bid:理由` |
| `bledit <书单id>` | 改书单名称/描述 | `--name` / `--desc` |
| `bladd <书单id> <bid>...` | 往书单加书（可统一写推荐理由） | `--reason` / `--dry` |
| `blrm <书单id> <bid>...` | 把书移出书单（默认预览） | `--yes` |
| `bldel <书单id>...` | 删除书单（默认预览） | `--yes` |
| `blfav <书单id>` | 收藏别人的书单 | `--off` 取消收藏 |
| `blsuggest <关键词>` | 书单加书时的联想搜索（在售 + 豆瓣 ISBN） | `--json` |
| `shelf <book_id>` | 把已购书补进云书架 | `--name` / `--folder` / `--dry` |
| `shelves` | 书架文件夹结构与各夹书数（只读） | `--books` / `--folder` |
| `move <book_id>...` | 把书移到文件夹 | `--to` / `--create` / `--dry` |
| `mkdir <夹名>` | 新建文件夹 | `--dry` |
| `rmdir <夹名>` | 删除文件夹 | `--force` / `--dry` |
| `cart` | 购物车列表（含下架/失效标记，只读） | `--recd` |
| `cartdel <book_id>...` | 移出购物车（默认预览） | `--yes` / `--category` |
| `cartadd <book_id>` | 加入购物车（重复加提示已在购物车） | `--category` |

列表命令通用开关：`--json` / `--auth` / `--workers` / `--douban` / `--douban-top`，写在子命令前后都行。列表默认给出书名、作者、出版社、简介、掌阅评分，并在末尾询问是否查豆瓣评分。

## 简介的呈现纪律

脚本输出的简介是原文硬截前 160 字，**经常断在句子中间**。直接照搬给用户是不可接受的，必须由你（大模型）判断后整理：

1. **判断是否完整**：读脚本给出的简介片段，看末字是否落在句末标点（`。！？…；` 等）上、语义是否收尾。落在句末且意思说圆了，可原样引用。
2. **断在句中就放宽窗口**：宁可多给几个字，也要让简介停在完整句子上。片段不够判断时，用 `--json` 取该书 `intro` 全文（`info <book_id> --json` 或列表 `--json`），从中摘出完整的 1~2 句。
3. **遵守长度预算**：单本简介呈现 100~160 字为宜，最多不超过 220 字；多本列表时按本数适当压缩，保证整体可读。
4. **不要编造**：只做截取、拼接、去口水话，不得添加原文没有的情节、评价或卖点。
5. **标注来源差异**：`blurb`（掌阅推荐语，多为营销文案）与 `intro`（内容简介，更客观）不是一回事，用户问"讲什么"时优先用 `intro`。
6. **可买/可推荐场景必须给简介**：当用户问「能买什么书」「有什么书可推荐」这类选书、推荐场景时，**每本书都要附简介**，不得为了列表简洁把简介省掉。仅纯比价、筛选核对（如「这几本我够不够券」）这类不涉及选书的纯核对场景，可只给价格与能否零付。
7. **书单书目先剔除下架书再推荐**：书单里下架书比例很高（实测 30%~67%），判据是 `is_removed=true`（这类书 `info` 查不到详情与价格，无法购买）。给用户推荐书单里的书时，默认只用 `booklist <id> --sale` 的在售书；全书目展示时下架书必须保留 `[已下架]` 标记，不得把下架书混进推荐清单。

## 写操作纪律

`buy` 改账户余额；`shelf` / `move` / `mkdir` / `rmdir` 改书架结构；`cartdel` / `cartadd` 改购物车；`blnew` / `bledit` / `bladd` / `blrm` / `bldel` / `blfav` 改书单。执行时守以下几条：

1. 先跑不带 `--confirm` 的询价，把售价、折后应付、代金券抵扣额报给用户看。
2. 拿到用户明确同意后再加 `--confirm`，不要自作主张下单。
3. 下单失败时如实报告返回的 `code` / `msg`，不要伪造成功。
4. 买后校验会打印 `IsAsset`，若仍显示未拥有要如实说明。
5. 不要用 `--confirm` 做测试，每一次都是真实扣券。
6. 批量整理书架前先跑 `--dry`，把要动的 book_id 与书名清单给用户过一遍；单个 `move` 也要先确认目标夹名（精确匹配，写错不会纠正）。
7. 删非空文件夹默认拒绝；确需 `--force` 时先说明这些书会被移到未归类。
8. `buy` 会自动使用满减券（走新版订单通道）。若想按原价购买、不下满减券，加 `--ignore-coupon`。只需向用户说明「本次用了满减券、省了多少」，无需再让用户去 App 操作。
9. 购物车写操作（`cartdel` 默认预览、`cartadd` 单本即生效）：批量加购前先把 book_id 与书名清单给用户过一遍；重复加购会提示「已在购物车」（服务端 201），不是错误；下架书（`state=2`）加不回购物车，属服务端规则。
10. `buy` 成功后自动归夹（默认开启，`--no-auto-folder` 关闭）：只从书架里已存在节点的自建文件夹中挑，绝不新建；夹名出现在书名或夹名等于作者记 100 分，夹内已有 ≥2 本同系列书记 80 分，最高分须 ≥80 且领先第二名 ≥20 分才移动，并列、无候选、状态/评价类夹或读取失败一律保持未归类。显式 `--folder` 优先。询价时会先打印归夹决定，确认下单后按该决定一次写入。脚本只做确定性匹配，不理解题材语义；判定「不移动」时，若依据 `shelves --books` 与书目信息能确认有明确更合适的夹，按第 6 条用 `move --dry` 复核后再补移，没有把握就不要移动。
11. 书单写操作（`blnew` / `bledit` / `bladd` / `blrm` / `bldel` / `blfav`）：创建/改名/加书前先把「名称、描述、要加哪些书」报给用户确认，描述由你按用户意图起草（1~200 字，别拿书名或简介原文硬凑）。批量加书先 `bladd ... --dry`，批量移出/删除先跑不带 `--yes` 的预览，把 id 与书名清单给用户过一遍。**`bldel` 不可恢复**（书单里的书本身不会被删），没有明确指令不要删；`bledit` 只改传了的那一项，没传的保持原值，不要为了"顺手统一"改动用户原有的描述。

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
| 淘书市活动约一月换两次期 | `taoshu` 靠滚动栏现场找当期 act_id（banner 名称→正文→券组件三级判定），未换期时返回 0 本属正常，不是故障。领券不归本技能：用 ireader_welfare 的 `taoshushi` 命令领到账户后，`buy` 自动抵扣；淘书市券与普通满减券同一套 `/zyuc/coupon` 账目。活动页（h5.zhangyue.com/opr/<act_id>.html）与频道滚动栏接口匿名可访问；券面额/门槛在 SSR HTML 的 amp_coupon 块，券与书目的 id 在每期一个的 JS bundle 里（`req_type:"coupon"` / `"book"` 的 req_params.ids），详见 `api.md` 13 节 |
| 购物车有两套且互不相通 | App 购物车页显示的是「新版购物车」（`zyuc/api/cart/cart`，上限 50，`state=2` 下架/`3` 失效不支持结算）；旧版购物车（`Cart.Num`）已废弃不可见。`cart`/`cartdel`/`cartadd` 操作新版，全部实测可用。**`cartadd` 要求请求带非空 `p1`/`p3` 设备参数**（脚本已内置 `CART_DEVICE_PARAMS`），缺失返回 53002；重复加返回 201 已在购物车。下架书无法加回（服务端拒）。详见 `api.md` 10b 节 |
| 书单有两套接口 | 我的书单走 App 原生 `/zyus/booklist/*`（`mybl`/`booklist`/`bldel`/`blfav`），签名规则**每个接口不一样**（`myList` 只签 `timestamp`+`usr`，`info` 签全部，`operate` 签 `operate`+`bookListId`），且 `zysid` 必须放 query 且不参与签名，缺了返回 `50000 未登录`。加书/改单走 H5 `app.php?ca=Booklist.*`。详见 `api.md` 11 节 |
| 建书单的 `addBooks` 用不了 | `/zyus/booklist/add` 的 `addBooks` 无论传什么结构都报 `invalid literal for int() with base 10: ''`（服务端拿空 id 做 int 转换）。**建单只能先建空单，再用 `bladd` 逐本加**；脚本的 `blnew --add` 已按这个顺序实现 |
| 书单名称/描述有硬限 | 名称 1~40 字、描述 1~200 字；超长或命中敏感词统一返回 `31215 文字内容违规，请修改后发布`（**不含具体是哪个字段超限**，别把这条当成"内容违规"去改词）。脚本已在本地先挡超长 |
| 书单加书是「不可重复」不是「覆盖」 | 同一本书重复加返回 `31206 该图书已存在`。想改推荐理由只能先 `blrm` 移出再加，或走 H5 `Booklist.UpdateOneBook`（实测返回「无数据返回」，不可靠） |
| `bledit` 有副作用 | `/zyus/booklist/update` 会把书单置为**审核态**（`status=check`，此时 `booklist` 的 `info` 接口恒返回 `53002`，`mybl` 仍可读，约 1~2 分钟恢复），并**清空自动生成的标签**（只有重新加书才会重算回来）。所以只在用户明确要改名称/描述时调用，别顺手"统一"描述 |
| 书单搜索有两种形态 | `blsearch` 默认 = App 首屏（3 个书单 + 作者卡 + 同页书籍 + 相关搜索）；`--page N` / `--all` 走原生「加载更多」请求（`type=bkList`，逆向自 App），**只返回书单列表**，作者卡等同页节点不返回（接口本身如此）。翻页接口细节见 `api.md` 11.7 |
| 书籍搜索（bsearch）与 search 分工 | `search` 走 H5 页（m.zhangyue.com），结果接 `info`/`buy` 选书比价流程；`bsearch` 走 App 多栏接口（`type=book`），带评分/分类/完结状态但**不查价**，适合发现式查询。`completeState` 是 `Y`/`N` 字符串，`bookRating` 为 0 表示无评分 |
| 书单书目普遍含下架书 | 原生接口书目条目的 `is_removed=true` 即下架（实测书单下架比例 30%~67%），这类书 `info` 查不到详情与价格、无法购买；`readable` 全为 true，**不能**当在售判据。脚本 `booklist` 已自动打标，`--sale` 只看在售 |

## 参考资料索引

按需读取，不要一次全部加载。

| 文件 | 何时读 |
|------|--------|
| `references/commands.md` | 查某个命令的完整参数、输出示例、版本挑选规则、速度表、常见问题 |
| `references/api.md` | 排查接口异常、扩展功能、确认字段语义与下单/书架/购物车/书单接口细节（购物车在 10b 节，书单在 11 节） |
| `references/douban.md` | 豆瓣限流、抓取字段、返回结构、降级策略 |
| `references/categories.md` | 全部分类 id 对照表 |
| `scripts/picker.py` | 改逻辑时直接读。密码登录在 `password_login()`；豆瓣在 `douban_by_isbn()` / `douban_many()`；书架结构在 `shelf_tree()` / `shelf_layout()`，归夹在 `shelf_move()` / `shelf_mkdir()` / `shelf_rmdir()` / `_upsert_shelf()`；书单在 `_bl_request()` / `my_booklists()` / `booklist_info()` / `booklist_create()` / `booklist_add_book()`；淘书市在 `tss_find_activities()` / `tss_load()` / `tss_parse_coupons()` / `tss_parse_books()` |

`commands.md` 与 `api.md` 篇幅较长，用 `grep -n '^## ' references/commands.md` / `grep -n '^## ' references/api.md` 先定位小节，不要整份加载。
