# ireader-picker：掌阅书城选书购书助手

基于 Agent Skills 规范的 AI agent 技能，纯 Python 标准库实现。把「账上有多少钱 → 这些钱能零付拿下哪些书 → 值不值得买 → 直接买下并归到书架对应文件夹」串成一条命令链路，默认只询价、经确认才扣券。

## ✨ 亮点

- **零付选书**：按可用代金券总额筛出「售价 ≤ 券额、能 0 元拿下」的书，并可直接按热度、好评、分类或书名检索
- **同名版本比价**：同名书聚成一组、组内按价升序，附 `作者 · 译者 · 出版社` 与评分人数，避免买错版本
- **豆瓣交叉验证**：按 ISBN 反查豆瓣评分与评价人数，与掌阅评分并列展示；豆瓣不可达时只丢该字段，不影响主流程
- **两次确认才花钱**：`buy` 不带 `--confirm` 只打开订单页询价，绝不扣券；券不足以全额覆盖售价时自动拦停
- **书架归夹**：查看文件夹结构、把书移到指定夹、新建/删除文件夹，买完可一步归位，写操作均支持 `--dry` 预览
- **满减券自动使用**：下单时自动套用满减券，折后应付用「代金券 + 阅饼」混合付清，不用跳 App 手动下单
- **查询只读**：`balance` / `coupons` / `afford` / `recommend` / `category` / `search` / `info` / `shelves` 全部不动账号
- **结构化输出**：所有命令加 `--json` 得完整书目字段，方便二次处理

## ⚙️ 前置要求

| 项 | 要求 |
|---|---|
| Python | 3.8+；除密码登录外全程仅用标准库 |
| 依赖 | 仅密码登录需要 `pip install -r requirements.txt`（`cryptography`），查书、查价、下单都不需要 |
| 登录 | `balance` / `coupons` / `buy` / 书架类命令需要凭证，先用 `login` 登录一次；凭证写入 `config.json`（已在 `.gitignore`） |
| 凭证有效期 | `zysid` 有有效期，失效后重跑 `login` 刷新即可 |

## 🚀 快速开始

### 1. 克隆项目

```bash
git clone https://github.com/5244DragonLin/ireader-picker.git
# Gitee 镜像（国内访问快）
git clone https://gitee.com/yhl5244/ireader-picker.git
```

### 2. 安装到技能目录

技能本体是一个目录，把整个目录复制到 WorkBuddy 的 `~/.workbuddy/skills/` 或 Claude Code 的 `.claude/skills/`，重启会话即可被 agent 发现。

### 3. 运行

用自然语言触发即可，例如：

> 「我掌阅还有多少阅饼和代金券？」
> 「这些券能零元买下哪些书？」
> 「有什么官场小说值得买？」
> 「帮我买下这本」

手动方式：

```bash
# 1. 首次登录（密码隐藏输入，成功后写入 config.json）
python scripts/picker.py login <手机号>

# 2. 看看账上有多少钱、券什么时候过期
python scripts/picker.py balance

# 3. 列出能零付买下的书
python scripts/picker.py afford

# 4. 下单：先询价，确认后再真扣券
python scripts/picker.py buy <book_id>
python scripts/picker.py buy <book_id> --confirm
```

## 📁 项目结构

```text
ireader-picker/
├── SKILL.md                  # 技能入口：agent 读这份决定何时触发、怎么干活
├── README.md                 # 人类门面：这是什么、怎么装、怎么触发
├── LICENSE                   # MIT 许可证
├── requirements.txt          # 仅密码登录需要的第三方依赖（cryptography）
├── scripts/
│   ├── picker.py             # 全部子命令实现，纯标准库
│   └── native_keys.json      # 掌阅客户端内置登录密钥（登录签名握手用）
└── references/
    ├── commands.md           # 命令完整参数、输出示例、FAQ
    ├── api.md                # 接口说明与字段语义（排查异常、扩展功能时读）
    ├── douban.md             # 豆瓣接入、限流与降级策略
    └── categories.md         # 全部分类 id 对照表
```

运行期会在技能根目录生成 `config.json` 保存凭证，该文件已在 `.gitignore` 中排除。

## ❓ FAQ

**不登录能用吗？**

可以查书和查价。`search` / `info` / `category` / `recommend` 的价格都是匿名可查的；只有余额、代金券明细、是否已拥有、下单和书架操作需要登录。

**为什么代金券差一点也买不成？**

那是旧订单页的规则。现在 `buy` 走的是新版订单通道，**代金券与阅饼可以混合支付**，只要「代金券 + 阅饼 ≥ 折后应付」就能买下。折后应付 = 活动价 − 满减券面额。

**我明明有「满 1000 减 200」，为什么还是余额不足？**

`buy` 会自动使用满减券，但门槛比的是**活动价**而不是标价。如果活动价已 ≥ 1000 且券后价仍在你代金券额度内，下单会自动用上这张券；仍提示余额不足，说明「活动价 − 200」超过了你手上的代金券。查券用 `coupons`。

**同名书该买哪版？**

看列表第二行：`作者 · 译者 · 出版社` + 评分人数。译著优先看译者，出版社影响排版校对质量，评价人数少的高分要打折看。拿不准就加 `--douban` 看豆瓣分——豆瓣样本通常大一个数量级。

**豆瓣查不到分？**

三种原因都属正常：这是网文（没有 ISBN，直接跳过）；豆瓣有书但评价人数不足；豆瓣未收录该 ISBN。豆瓣不可达时也只影响豆瓣字段，掌阅数据照常返回。

**`afford` 返回 0 本是故障吗？**

不是。书城几乎没有几阅饼的书，券额小时返回 0 本是正常结果。等福利中心签到达标或攒够券再买。

## 🤝 贡献

欢迎提 Issue 和 PR！流程：Fork → 新建分支 → 提交改动 → 发起 Pull Request。提交前请确认没有把 `config.json`、`.workbuddy/`、`archive/` 等含凭据或本地记录的文件带进暂存区（`git status --short` 核对）。

## 📜 更新日志

### v0.1

- 首个版本：查余额与券、筛零付书目、按热度或分类找书、同名版本比价、豆瓣评分、询价确认后下单、书架归夹。

## 🔗 关联项目

- [**ireader_welfare**](https://github.com/5244DragonLin/ireader_welfare) — 上游福利中心，产出代金券
  - GitHub：https://github.com/5244DragonLin/ireader_welfare
  - Gitee：https://gitee.com/yhl5244/ireader_welfare
- [**ireader_bookshelf_exporter**](https://github.com/5244DragonLin/ireader_bookshelf_exporter) — 下游：已购书导出 EPUB
  - GitHub：https://github.com/5244DragonLin/ireader_bookshelf_exporter
  - Gitee：https://gitee.com/yhl5244/ireader_bookshelf_exporter

## ☕ 捐赠

如果这个技能帮你把临期的券变成了书架上的书，欢迎请作者喝杯咖啡！

| 支付宝 | 微信 |
|--------|------|
| ![支付宝](https://gitee.com/yhl5244/images/raw/master/donate_alipay.jpg) | ![微信](https://gitee.com/yhl5244/images/raw/master/donate_wechat.jpg) |

## ⚠️ 免责声明

- 本技能仅供个人学习研究与管理自己的掌阅账号使用，请勿用于批量下单、倒卖或其他违反掌阅服务条款的场景。
- `buy` / `shelf` / `move` / `mkdir` / `rmdir` 是会真实改变账号状态的操作（扣券、增删书架条目）；使用产生的一切后果（含券与余额损失、账号风控、数据变更）由使用者自行承担。
- 本技能通过掌阅 H5 页面实现，无官方接口支持；页面改版或风控升级可能导致失效，作者不保证持续可用。
- `scripts/native_keys.json` 为掌阅客户端内置的 RSA 密钥（登录签名握手用），版权归原厂所有，本项目仅作技术研究引用，不代表任何授权关系。
- 请严格按「先询价、确认后再 `--confirm`」的流程操作，`buy` 的每一次 `--confirm` 都是真实扣券，不要用来测试。
- 本技能与掌阅（iReader）官方无任何关联。

## 📃 许可证

本项目基于 [MIT](LICENSE) 协议开源。
