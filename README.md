# ireader-picker：掌阅书城选书购书助手

基于 Agent Skills 规范的 AI agent 技能，纯 Python 标准库实现。把「账上有多少钱 → 这些钱能零付拿下哪些书 → 值不值得买 → 直接买下并归到书架对应文件夹」串成一条命令链路，默认只询价、经确认才扣券。

这三个掌阅工具构成一条完整链路：[ireader_welfare](https://github.com/5244DragonLin/ireader_welfare) 负责领券，[ireader-picker](https://github.com/5244DragonLin/ireader-picker) 负责用券选书下单，[ireader_bookshelf_exporter](https://github.com/5244DragonLin/ireader_bookshelf_exporter) 负责把买下的书导出为 EPUB。各工具可单独使用，也可串起来覆盖从领券、购书到导出收藏的全过程。

## ✨ 亮点

- **零付选书**：按可用代金券总额筛出「售价 ≤ 券额、能 0 元拿下」的书，并可直接按热度、好评、分类或书名检索
- **淘书市券后书目**：自动追书城「淘书市」活动（约一月两期），列出当期满减券面额门槛，推荐活动书目里叠加当期券后能拿下的书
- **满减券自动使用**：下单时自动套用满减券，折后应付用「代金券 + 阅饼」混合付清，不用跳 App 手动下单
- **同名版本比价**：同名书聚成一组、组内按价升序，附作者、译者、出版社与评分人数，避免买错版本
- **豆瓣交叉验证**：按 ISBN 反查豆瓣评分与评价人数，与掌阅评分并列展示；豆瓣不可达时只丢该字段，不影响主流程
- **两次确认才花钱**：下单默认只询价，绝不扣券；可买条件不满足时自动拦停
- **书架归夹**：查看文件夹结构、把书移到指定夹、新建/删除文件夹，买完可一步归位，写操作均可先预览
- **书单管理**：查看我创建/收藏的书单，建单（晒/求）、改名称描述、逐本加书并写推荐理由、移出书单、删除、收藏别人的书单
- **查询只读 + 结构化输出**：查余额、查券、找书、看书架、看购物车全部不动账号，所有查询都能输出完整结构化字段

## 📦 安装

技能本体是一个目录，克隆后放进 agent 的技能目录即可。

```bash
# GitHub 原仓库
git clone https://github.com/5244DragonLin/ireader-picker.git

# Gitee 镜像（国内访问快）
git clone https://gitee.com/yhl5244/ireader-picker.git

# 放进技能目录（WorkBuddy 用 ~/.workbuddy/skills/，Claude Code 用 .claude/skills/）
mv ireader-picker ~/.workbuddy/skills/
```

重启会话后 agent 即可发现该技能。技能目录结构见「项目结构」。

## 🚀 快速开始

### 1. 首次登录

密码隐藏输入，成功后凭证写入技能根目录的 `config.json`：

```bash
python scripts/picker.py login <手机号>
```

### 2. 自然语言触发

装好后直接用自然语言提需求即可：

> 「我掌阅还有多少阅饼和代金券？」
> 「这些券能零元买下哪些书？」
> 「淘书市这期有什么值得买？券后多少？」
> 「有什么官场小说值得买？」
> 「帮我买下这本」
> 「帮我建个书单叫『硬科幻入门』，把三体加进去」

### 3. 命令行直接跑

```bash
python scripts/picker.py balance                      # 阅饼 + 代金券（含到期日）
python scripts/picker.py afford                       # 能零付买下的书
python scripts/picker.py taoshu                       # 淘书市当期：叠加满减券后能买的书
python scripts/picker.py buy <book_id>                # 下单：默认只询价
python scripts/picker.py buy <book_id> --confirm      # 确认后真扣券
```

完整参数、输出示例见 `references/commands.md`。

## ⚙️ 前置要求

| 项 | 要求 |
|---|---|
| Python | 3.8+；除密码登录与购物车/书单签名外全程仅用标准库 |
| 依赖 | 密码登录与购物车、书单签名需要 `pip install -r requirements.txt`（`cryptography`）；查书、查价、下单都不需要 |
| 登录 | `balance` / `coupons` / `buy` / 书架类 / 购物车类 / 书单类命令需要凭证，先执行上面的 `login` 一次 |
| 凭证有效期 | `zysid` 有有效期，失效后重跑 `login` 刷新即可 |
| 兼容性 | 遵循 Agent Skills 规范，WorkBuddy / Claude Code 等支持该规范的 agent 通用 |

`config.json` 含凭证，已在 `.gitignore` 中排除，不要提交到任何仓库。

## 📁 项目结构

```text
ireader-picker/
├── SKILL.md                  # 技能入口：agent 读这份决定何时触发、怎么干活
├── README.md                 # 人类门面：这是什么、怎么装、怎么触发
├── LICENSE                   # MIT 许可证
├── requirements.txt          # 仅签名相关功能需要的第三方依赖（cryptography）
├── scripts/
│   ├── picker.py             # 全部子命令实现，纯标准库
│   └── native_keys.json      # 掌阅客户端内置 RSA 密钥（登录/接口签名握手用）
└── references/
    ├── commands.md           # 命令完整参数、输出示例、FAQ
    ├── api.md                # 接口说明与字段语义（排查异常、扩展功能时读）
    ├── douban.md             # 豆瓣接入、限流与降级策略
    └── categories.md         # 全部分类 id 对照表
```

## ❓ FAQ

**不登录能用吗？**

可以查书和查价。`search` / `info` / `category` / `recommend` 的价格都是匿名可查的；只有余额、代金券明细、是否已拥有、下单、书架、购物车和书单操作需要登录。

**为什么代金券差一点也买不成 / 明明有「满 1000 减 200」还是余额不足？**

买书支持「代金券 + 阅饼」混合支付，只要加起来够折后应付就能买下；满减券会自动使用，但门槛比的是活动价而不是标价——活动价不够门槛券就下不去，扣掉券后超过代金券余额也会拦停。

**淘书市是什么？券怎么领？**

掌阅 App 书城顶部滚动 banner 里的运营活动（约一月换两次期），每期挂 3~4 张满减券（满 500 减 200 到满 10000 减 5000 不等）加约 150 本活动书目。本技能只负责「看」：找当期活动、推荐券后能买的书。**领券要用姊妹项目 [ireader_welfare](https://github.com/5244DragonLin/ireader_welfare)**，领到账户后下单自动抵扣。活动没换期时推荐会安静退出，属正常。

**同名书该买哪版？**

看列表第二行：作者、译者、出版社 + 评分人数。译著优先看译者，出版社影响排版校对质量，评价人数少的高分要打折看。拿不准就看豆瓣分——豆瓣样本通常大一个数量级。

**建书单时能一次把书带进去吗？**

`blnew --add <book_id>:<理由>` 支持，但内部是「先建空单、再逐本加」——掌阅原生建单接口的 `addBooks` 参数服务端解析有 bug，只能传空数组。单书单上限 100 本。

**豆瓣查不到分？**

三种原因都属正常：这是网文（没有 ISBN，直接跳过）；豆瓣有书但评价人数不足；豆瓣未收录该 ISBN。豆瓣不可达时也只影响豆瓣字段，掌阅数据照常返回。

## 🤝 贡献

欢迎提 Issue 和 PR！流程：Fork → 新建分支 → 提交改动 → 发起 Pull Request。

提交前请跑一遍 `git status --short` 核对，确认没有把 `config.json`、`.workbuddy/`、`archive/`、`__pycache__/` 等含凭据或本地记录的文件带进暂存区。

## 📜 更新日志

### v0.2

- **新增：** 淘书市券后书目推荐：自动追书城当期活动，列出当期满减券面额与门槛，推荐活动书目里叠加当期券后能拿下的书
- **新增：** 书单管理：看我创建/收藏的书单，建单（晒/求）、改名改描述、加书写理由、移出、删除、收藏别人的书单
- **新增：** 书单详情一次取全书目（原来只能取前 5 本），并显示每本书的推荐理由
- **新增：** 购物车查看与清理：标出下架/失效书，可移出死书、把书加入购物车
- **新增：** 按作者任一作品查作者主页，看简介与名下全部作品
- **优化：** 批量加书、移出书单、删除书单默认先预览，确认后才写入
- **优化：** 书籍搜索减少请求次数，搜索更快

### v0.1

- 首个版本：查余额与券、筛零付书目、按热度或分类找书、同名版本比价、豆瓣评分、询价确认后下单、书架归夹。

## ☕ 捐赠

如果这个技能帮你把临期的券变成了书架上的书，欢迎请作者喝杯咖啡！

| 支付宝 | 微信 |
|--------|------|
| ![支付宝](https://gitee.com/yhl5244/images/raw/master/donate_alipay.jpg) | ![微信](https://gitee.com/yhl5244/images/raw/master/donate_wechat.jpg) |

## ⚠️ 免责声明

- 本技能仅供个人学习研究与管理自己的掌阅账号使用，请勿用于批量下单、倒卖或其他违反掌阅服务条款的场景。
- `buy` / `shelf` / `move` / `mkdir` / `rmdir` / `cartdel` / `cartadd` / `blnew` / `bledit` / `bladd` / `blrm` / `bldel` / `blfav` 是会真实改变账号状态的操作（扣券、增删书架条目、增删书单）；使用产生的一切后果（含券与余额损失、账号风控、数据变更）由使用者自行承担。
- 本技能通过掌阅页面与 App 内置接口实现，无官方接口支持；页面改版或风控升级可能导致失效，作者不保证持续可用。
- `scripts/native_keys.json` 为掌阅客户端内置的 RSA 密钥（签名握手用），版权归原厂所有，本项目仅作技术研究引用，不代表任何授权关系。
- 请严格按「先询价、确认后再 `--confirm`」的流程操作，`buy` 的每一次 `--confirm` 都是真实扣券，不要用来测试。
- 本技能与掌阅（iReader）官方无任何关联。

## 📃 许可证

本项目基于 [MIT](LICENSE) 协议开源。