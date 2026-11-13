# 掌阅选书接口参考

排查异常或扩展功能时读这份。所有结论均为实测，覆盖 2026-10-28 至 2026-11-11。命令用法见 `commands.md`，豆瓣细节见 `douban.md`。

## 域名分工

| 域名 | 用途 | 需要凭证 |
|------|------|---------|
| `ah2.zhangyue.com` | App H5：余额、券、书籍详情、下单试算 | 详情页不需要；余额/券/拥有状态需要 |
| `m.zhangyue.com` | 手机站：**按书名搜索** | 不需要 |
| `ireader.com.cn` | 官网书城：**分类页（全量枚举来源）** | 不需要 |
| `api-pc.zhangyue.com` | PC 接口：书架列表 | 需要 |

> 最大的坑：搜索接口在 `m.zhangyue.com`，**不在 `ah2`**。在 `ah2` 上试
> `search.php?key=1S1` 恒 404，导致长期误判「掌阅没有搜索接口」。

## 1. 余额

```http
GET https://ah2.zhangyue.com/zybook3/u/p/api.php?Act=getUserInfo&usr=&zysid=
```

```json
{"remain_sum":0, "remain_sum_yb":"0", ...}
```

`remain_sum` = **阅饼**（现金等价，充值所得）。注意「阅饼」与「代金券」是两套东西。

账户页（含代金券总额，服务端渲染）：

```http
GET https://ah2.zhangyue.com/zybook3/app/app.php?ca=Account.Index&usr=&zysid=
```

```html
<div class="notice" data-js="expire"><em></em>您有200代金劵即将到期</div>
<div class="account_top point">
  <div class="item1"><p class="t2" data-js="num">0</p><p class="t1">阅饼</p></div>
  <div class="item2"><p class="t2" data-js="num">200</p><p class="t1">代金券 | 有效期</p></div>
</div>
```

## 2. 代金券明细（含到期日）

```http
GET https://ah2.zhangyue.com/zyuc/gift/ajaxrequest?index=2&usr=&zysid=
```

`index`：`1` 未领取 / `2` 已获得（含有效期） / `3` 礼卡兑换。

返回 HTML 片段，单张券：

```html
<div class="card_useless" data-js="voucherDetail" data-id="i0000000000-261030">
  <div class="num">60</div><div class="sub">阅饼</div><div class="tag">代金券</div>
  <div class="name">获得30阅饼 | 签到送礼</div>
  <div class="txt">有效期至2026-10-30</div>
```

| 抓取项 | 正则 |
|--------|------|
| 面额 | `<div class="num">([0-9.]+)</div>` |
| 来源 | `<div class="name">(.*?)</div>` → 取 `|` 之后 |
| 有效期至 | `<div class="txt">有效期至(\d{4}-\d{2}-\d{2})</div>` |
| 已使用 | 分块开头是否 `card_useless used` |

**这是全量流水**（含已过期/已使用），必须按有效期自行过滤。`&status=` `&type=` `&page=` 均无效。

## 2b. 满减券（优惠券，与代金券无关）

```http
GET https://ah2.zhangyue.com/zyuc/coupon/ajaxrequest?index=1&usr=&zysid=
```

| `index` | 内容 |
|---------|------|
| `1` | 书籍优惠券（「版权允许范围内电子书籍均可使用」） |
| `2` | 实物商品优惠券 |

返回 `{"html": "...", "totalpage": 1, "code": 0}`。单张券：

```html
<div class="card_use" data-productid="20627" data-status="1">
  <div class="card"><div class="flex sup_info">
    <div class="price"><div class="num">200<span class="sub">阅饼</span></div>
      <div class="tag">优惠券</div></div>
    <div class="content"><div class="con">
      <div class="name">新满1000减200</div>
      <div class="txt p_line4">2026-11-10至 2026-11-13使用</div>
    </div></div>
  </div><div class="sub_warn">满1000阅饼使用</div></div>
</div>
```

| 抓取项 | 正则 |
|--------|------|
| 减免额 | `<div class="num">([0-9.]+)` |
| 门槛 | `满([0-9.]+)\s*阅饼使用` |
| 名称 | `<div class="name">([^<]+)</div>` |
| 有效期 | `(\d{4}-\d{2}-\d{2})\s*至\s*(\d{4}-\d{2}-\d{2})` |
| 已过期/已用 | 分块开头含 `expired` |

券详情（`适用范围`、`详细说明`）：

```http
GET https://ah2.zhangyue.com/zyuc/coupon/detail?productId=<data-productid>&status=1&usr=&zysid=
```

### 满减券在脚本这条链路上用不了（真实下单验证）

### 满减券必须走新版订单通道（2026-11-12 修正）

**旧通道用不了满减券**：`Order.Create` / `Order.ClientCreate` / `Api.InnerOrder` 都只返回「价格 / 余额 / 需支付」，页面里 `优惠券` 出现 0 次；`couponId`、`couponProductId`、`productId`、`useCoupon`、`couponAmount`、`couponSwitch` 等参数逐个注入过，`需支付` 金额一律不变；POST 方式提交也不被接受（404）。支付环节同样无效：`Order.Pay` 上带 `couponProductId=20627`，结果仍按**原价全额**扣券。根因是 `chargingStr` 在试算时生成，价格已封进签名令牌，支付时再传券参数改不了应付额。

**新版通道可以用满减券**，见下方第 9b 节。客户端页面已切到新版 Vue 订单页（`order-pro/market/order/wholeBk.html`），它走 `/trade/order/{volume,pay}`，试算返回完整的混合支付拆解，把 `coupon_code` 提交给 `pay` 即可用券。

代金券与满减券是两套：代金券走 `gift`，满减券走 `coupon`；只有代金券在 `getOrderTmpInfo` 的 `deductionInfo.coupon` 里体现。


## 3. 书籍详情（价格来源）

```http
GET https://ah2.zhangyue.com/zybook3/u/p/book.php?key=17B<bookId>&usr=&zysid=
```

`key=17B` 后**直接拼书号、无分隔符**。拼成 `key=17B&bookId=xxx` 会返回无数据骨架页。

页面里有四块结构化数据，一次请求全拿到（不用再调别的接口）：

```html
<dl class="main"><dt>乌合之众</dt>
  <dd class="d_author">                       <!-- 作者区 -->
    <span data-js="author-page">古斯塔夫·勒庞[著]</span>，
    <span data-js="author-page">亦言[译]</span><span class="line">|</span>
    <span data-js="url">创美时代</span>       <!-- 末位无标记 = 版权品牌方 -->
  </dd>
  <dd class="font_inof"><span class="font_num">连载中 20.6万字</span></dd>  <!-- 仅网文有 -->
  <dd class="price"><span class="dark_gray">398阅饼</span><del>796阅饼</del></dd>
</dl>
<div class="dt_info">讲述那些不吐不快的历史片段</div>              <!-- 一句话推荐语 -->
<p data-js="brief_intro_txt">本书讲述了…</p>                      <!-- 内容简介 -->
<div class="bookinfo">
  <p>字数：10万字</p><p>大小：417 KB</p><p>上架时间：2024-12-09</p>
  <p>出版社：中国友谊出版公司</p><p>书号：9787505745681</p>
</div>
```

| 抓取项 | 正则 / 方法 |
|--------|------|
| 书名 | `<dt>([^<]{1,80})</dt>` |
| 作者区整块 | `<dd class="d_author">(.*?)</dd>`（`re.S`） |
| 作者 / 译者 | 块内取所有 `<span[^>]*>([^<]+)</span>`：带 `[译]` 的为译者，其余为作者 |
| 版权品牌方 | 作者区末位无 `[著]/[译]` 标记的 span；取不到时回退 `数字版权由(.+?)提供` |
| 连载状态 + 字数 | `class="font_num">\s*(连载中\|已完结)\s*(.*?)</span>` |
| 现价（阅饼） | `<span class="dark_gray">\s*([0-9.]+)\s*阅饼\s*</span>` |
| 划线原价 | `<del>\s*([0-9.]+)\s*阅饼\s*</del>` |
| 按千字计价（连载） | `([0-9.]+)\s*阅饼/千字` |
| 免费 | `<span class="dark_gray">\s*免费\s*</span>` |
| 特价标记 | `特价` |
| 一句话推荐语 | `class="dt_info">\s*(.*?)</div>`（`re.S`） |
| 内容简介 | `data-js="brief_intro_txt">(.*?)</p>`（`re.S`） |
| 字数 / 大小 / 上架时间 / 出版社 / 书号 | `<p>(字数\|大小\|上架时间\|出版社\|书号)：(.*?)</p>` |
| 评分 / 评价人数 | `stars_box.*?custom-font'?>([0-9.]+)</strong>` / `(\d+)人评分` |
| 章节数 | `共(\d+)章` |
| 封面 | `class="bookcover" src="([^"]+)"` |

**字段是可选的**：网文没有 `bookinfo` 块（无出版社/书号），冷门书没有评分，很多书没有 `dt_info` 推荐语。解析出来是空串或 `None` 属正常，不要当成页面结构变了。

**推荐语与简介不要混淆**：`dt_info` 是一句营销文案（常带 emoji/书名号），`brief_intro_txt` 才是真正的正文简介。

### 书号（ISBN）的三个坑

1. **网文没有**。男频/女频书籍页不存在 `bookinfo` 块，`isbn` 与 `publisher` 同时为空。
   实测热门 40 本出版书有 32 本带 ISBN（约 80%），网文样本 8 本全部为空。
2. **不是唯一键**。同一纸书拆成多个电子条目时 ISBN 相同、book_id 不同。实测：
   `11787714`《平凡的世界（全3册）》与 `11817298`《平凡的世界（第一部）》
   ISBN 均为 `9787530216781`。**唯一性只认 book_id**。
3. **不能用来搜书**。掌阅搜索接口不索引 ISBN，用 ISBN 当关键词返回 0 条。

脚本内 `isbn_valid()` 做校验位验证（ISBN-13 加权和、ISBN-10 含 X），仅用于在 `info` 里给一行提示，不通过也不剔除数据。

**重要**：详情页**不反映是否已拥有**——已购书照样渲染原价。不要用详情页判断拥有状态。

单位换算：`1 元 = 100 阅饼`。

## 4. 是否已拥有（权威判据）

```http
GET https://ah2.zhangyue.com/zybook3/u/p/order.php?Act=getOrderTmpInfo&bid=<bookId>&usr=&zysid=
```

```json
{"Data":{
  "Charging":{"Price":"0.90","FeeType":3,"IsAsset":0},
  "deductionInfo":{"coupon":11,"yb":0},
  "tplInfo":{"couponDesc":"支持代金券全额支付"}
}}
```

| 字段 | 含义 |
|------|------|
| `Charging.IsAsset` | **`1` = 已拥有**（唯一可靠判据） |
| `Charging.FeeType` | `-1` 已拥有或免费；`2`/`3` 可购买 |
| `Charging.Price` | 售价（元） |
| `deductionInfo.coupon` | **券池上限，不代表本次真能扣** |

`IsAsset` / `FeeType` 组合语义：

| `IsAsset` | `FeeType` | 含义 |
|-----------|-----------|------|
| `1` | `-1` | 已拥有 |
| `0` | `3` | 可购买 |
| `0` | `-1` | 免费书（未拥有但无价） |

**同书多 ID 别名**：同一本书可能同时存在两个 `book_id`（如 `10121980` 与 `10122011`），书架只收录其中一个，但服务端对两者都返回 `IsAsset=1`。只用书架判断会误报「未拥有」。

**代金券与阅饼可混合支付（新版通道）**，条件为「代金券 + 阅饼 ≥ 折后应付」。旧通道才要求代金券全额覆盖售价。

## 5. 书架（排除集）

```http
GET https://api-pc.zhangyue.com/bookstore/open/cloud/bookshelf/list
    ?usr=&zysid=&p29=zye5b814&p2=104583&p3=18070403&p4=501603&p33=com.chaozh.iReaderFree
```

`body.data` 是数组，条目可能带 `children`（嵌套），需展开取 `book_id`。
`body.current_version` 是**乐观锁**，所有写操作都要带回当前值，每写一次 +1。

### 5.1 书架结构与文件夹（已实测）

`body.data` 是**扁平数组**，书与文件夹混在一起，靠 `dtype` 区分：

| 条目 | `dtype` | `book_id` | `book_name` | `mark` | `folder_hierarchy` |
|------|---------|-----------|-------------|--------|--------------------|
| 书 | `0` | 数字（或本地书的长 hash） | 书名 | `""`，本地书为 `A_1` | 所属夹：`["外国经典文学"]` / 未归类 `[]` |
| 文件夹 | `1` | 8 位十六进制 | `""` | `A_1` | 夹自身名字：`["已阅"]` |

- **`dtype` 是唯一判据**，`mark` 不是：本地导入书（`book_type=1`、`is_local_book=true`、
  64 位 hash `book_id`）也带 `mark="A_1"`，与文件夹节点相同，按 mark 判断会误判。
- 本地导入书同样可以用 `upsert type=3` 改 `folder_hierarchy` 归夹，已实测通过
  （两本长 hash id 的本地书移入新建的「本地导入」夹，写回后复核落库成功）。

- `folder_hierarchy` 是 **JSON 字符串**（不是数组对象），也可能已是 list，解析时两种都要兼容。
- 多级目录形如 `["一级","二级"]`，一级目录最常见。
- `folder` 字段恒为 `""`，**不参与归类**，真正的归属只看 `folder_hierarchy`。
- 文件夹节点的 `order` 常见 1000003 / 1000005 / … 这类 1000000 起的递增段，
  也见过负数（老数据），新建节点沿用 `max(已有 >= 1000000 的 order) + 1` 即可。
- `book_type`：书常见 24（整本电子书）/5/9/0，文件夹节点固定 0；`btype_ext` 恒 0。

示例（`list` 里的一个文件夹节点）：

```json
{
  "book_id": "1807f572", "book_name": "", "cover_name": "",
  "book_type": 0, "is_local_book": false, "book_file_id": "",
  "book_file_size": 0, "cover_file_id": "", "cover_file_size": 0,
  "folder_hierarchy": "[\"外国经典文学\"]", "dtype": 1, "order": -1094,
  "folder": "", "top": 0, "top_sort": 0, "mark": "A_1", "btype_ext": 0
}
```

**文件夹不是容器**：书不会挂在文件夹节点的 `children` 下，而是平铺在数组里、
各自带一个 `folder_hierarchy`。所以「移动书到某夹」= 改该书条目的
`folder_hierarchy`，再用 `upsert type=3` 写回；书的位置、`order` 都不用动。

## 6. 分类页（全量枚举来源）★

```http
GET https://ireader.com.cn/index.php?ca=booksort.index&pca=bookrank.index
    &pid=<频道>&cid=<分类>&order=<排序>&status=<筛选>&page=<页码>
```

| 参数 | 取值 | 含义 |
|------|------|------|
| `pid` | `10` / `68` / `92` | 男频 / 女频 / **出版** |
| `cid` | 见 `categories.md` | 分类 id（三频道各一套，不重叠） |
| `status` | `0`/`1`/`2`/`3`/`4` | 全部 / **免费** / **特价** / 完结 / VIP |
| `order` | `download`/`score`/`update` | **热门** / **好评** / 最新 |
| `page` | 1..N | 每页 **60 本** |

- 翻页超过末页时**钳制在最后一页**（内容重复），不会 404
- 每页 60 本**几乎零重复**（不像榜单页）
- **不含价格**，价格要逐本回第 3 节查
- `order` 三种排序返回**完全不同的书单**

书卡结构：

```html
<li>
  <a href="...?ca=bookdetail.index&pca=booksort.index&bid=13715675">
    <img src="..." alt="书名">
  </a>
  <div class="bookMation">
    <h3><a href="...bid=13715675">书名</a></h3>
    <p class="tryread">作者 <a href="...ca=Chapter.Index">试读</a></p>
    <span>2026-10-23上架</span>
  </div>
</li>
```

解析要点：**先筛含 `bookdetail.index` 的 `<li>`**，否则导航栏的 `<li>` 会被误算；每个 `<li>` 内有封面链接 + 书名链接**两个 bid**，按 `<li>` 块去重即可得 60 本/页。

## 7. 按书名搜索

```http
GET https://m.zhangyue.com/search?keyWord=<关键词>
GET https://m.zhangyue.com/search/more?keyWord=<关键词>&currentPage=<n>
```

- 翻页参数名是 **`currentPage`**（`page`/`pageNo`/`p` 一律无效，返回第 1 页）
- 首屏 HTML 里 `totalpage="(\d+)"` 给总页数，每页 20 条
- 卡片：`data-type="book" data-id="(\d+)"`、`<div class="name ellipsis">`、`<div class="author ellipsis">`
- **不含价格**，需回第 3 节查
- 无结果时页面含「未找到相关书籍」

## 8. 榜单（覆盖面小，仅作兜底）

```http
GET https://ah2.zhangyue.com/zybk/rank/booklist?pk=1P1&sectionId=<id>&type=normal&style=style1&nextRowId=<n>&usr=&zysid=
```

`html` 字段内嵌卡片，`"id":(\d{7,9})` 取 book_id。`pk` 是幌子（各 pk 内容一致），真正分区键是 `sectionId`（`40296` = 特价榜）。翻页用 `nextRowId` 游标。

**局限**：全分区合计仅约 1800~2000 本候选，且动态变化（实测同一天从 2028 降到 1795），冷门书会掉出。**优先用分类页（第 6 节）而非榜单。**

## 9. 下单购买（⚠️ 写操作，会真扣券）

两步：**询价**（不扣费）→ **支付**（扣券）。两步必须连续，令牌是一次性的。

### 9.1 询价

```http
GET https://ah2.zhangyue.com/zytc/public/index.php
    ?ca=Order.Create&alone=&bid=<bookId>&cid=0&pay_360=
    &pca=client_askOrder&pk=askOrder&projectSource=zybook3&usr=&zysid=
```

页面服务端渲染出：

```text
价格：810阅饼 / 99阅饼          ← 原价 / 现价
余额：0阅饼 200代金券            ← 阅饼余额 / 代金券余额
需支付：99代金券                 ← 券够时才有这一行
```

同时给出一个 **`chargingStr`**（1024-bit RSA 签名的一次性订单令牌）：

```html
... chargingStr=<很长的一串> ...
```

解析与判据：

| 抓取项 | 正则 / 判据 |
|--------|------------|
| 现价（阅饼） | `价格：\s*([0-9.]+)\s*阅饼\s*([0-9.]+)\s*阅饼` → 第 2 组 |
| 账上代金券 | `余额：\s*([0-9.]+)\s*阅饼\s*([0-9.]+)\s*代金券` → 第 2 组 |
| 需支付券数 | `需支付：\s*([0-9.]+)\s*代金券` |
| 已拥有 | 文本含 `已拥有` / `您已购买本书` |
| **券不足** | 文本含 `余额不足`（此时**没有**「需支付」行） |
| 令牌 | `chargingStr=([A-Za-z0-9%]+)`（HTML 原文，不是剥标签后的文本） |

### 9.2 支付

```http
GET https://ah2.zhangyue.com/zytc/public/index.php
    ?ca=Order.Pay&pca=Order.Create&projectSource=zybook3
    &usr=&zysid=&chargingStr=<上一步令牌>&pk=askOrder&rgt=
```

成功返回：

```json
{"code":0, "msg":"购买成功",
 "downloadInfo":{"bookId":"10121980","bookName":"《某某书》.ebk3",
                 "orderId":"B000000000000000000","downloadUrl":"https://..."}}
```

### 9.3 铁律与坑（旧通道）

- **新版通道**（第 9b 节）支持满减券与代金券/阅饼混合支付；旧通道（本节）必须代金券全额覆盖售价。
- `chargingStr` 是一次性令牌，价格封在里面，客户端改不了金额；询价与支付之间别再询价。
- 支付时传 `couponProductId` 等券参数无效（已实测按原价扣券），满减券进不了这条链路。
- 已拥有的书订单页会提示「您已购买本书」，不该再调支付。
- 支付成功后再查 `getOrderTmpInfo`，会变成 `IsAsset=1 / Price=0 / FeeType=-1`。

## 9b. 新版订单通道（支持满减券 + 混合支付）★

新版 Vue 订单页 `order-pro/market/order/wholeBk.html` 走 `/trade/order/{volume,pay}` 两个接口。
`buy` 命令用的就是这条链路。实测 2026-11-12，Web 端可完整跑通。

### 9b.1 试算（不扣费）

```http
GET https://ah2.zhangyue.com/trade/order/volume
    ?bid=<bookId>&cid=0&vbuy=0&coupon_code=&time=<毫秒时间戳>
    &p29=zye5b814&p2=104583&p3=18070403&p4=501603&p33=com.chaozh.iReaderFree
    &usr=&zysid=
```

返回（`body`）：

```json
{
  "book_info": {"id":"10891439", "name":"《深宅活寡》", "author":"许开祯", "category":"都市"},
  "price": 24.99,            // 标价（元）
  "dis_price": 12.99,        // 活动价（元），即折后价
  "is_support_voucher": true,
  "coupon": {"code":"630019", "amount":200, "condition_amount":1000, "status":1},
  "pay": {
    "amount": 10.99,         // 折后应付（元）= dis_price - 满减券面额
    "coupon_amount": 10.99,  // 代金券抵扣额（元）
    "yb_amount": 0,          // 阅饼抵扣额（元）
    "gap_yb_amount": 0,      // 还差多少（元），够付时缺省
    "is_enough": true,       // 代金券 + 阅饼是否够付
    "token": "…",            // 下单令牌
    "is_fast_pay": true
  },
  "user": {"account_amount":0, "coupon_amount":10.99, "is_vip":false},
  "deductionInfo": {         // 抵扣顺序两套方案（App 有「优先使用代金券」勾选框）
    "voucherFirst": {"coupon":1099, "yb":0},
    "yuebingFirst": {"coupon":1099, "yb":0}
  },
  "variant": "0"
}
```

**单位换算**：接口价格是「元」，×100 = 阅饼。

**关键字段语义**：

| 字段 | 含义 |
|------|------|
| `price` | 标价（元） |
| `dis_price` | 活动价（元），无活动时等于标价 |
| `coupon` | 账户里可用的满减券（`code` + `amount` + `condition_amount` 门槛） |
| `pay.amount` | 实际应付（元）= `dis_price` − 满减券面额 |
| `pay.coupon_amount` | 其中代金券抵扣多少 |
| `pay.yb_amount` | 其中阅饼抵扣多少 |
| `pay.gap_yb_amount` | 还差多少才够付（有值说明余额不足） |
| `pay.is_enough` | 代金券 + 阅饼是否够付 |
| `pay.token` | 下单令牌，一次性 |

**注意**：`coupon` 字段只是「账户里有一张能用的券」，是否真能用要看 `dis_price ≥ condition_amount`。活动价低于门槛时券其实用不上，脚本已按此再判一次。

### 9b.2 下单（⚠️ 真扣券）

```http
POST https://ah2.zhangyue.com/trade/order/pay
     ?bid=<bookId>&cid=0&vbuy=0&pk=askOrder&rgt=<页面参数>
     &p29=zye5b814&p2=104583&p3=18070403&p4=501603&p33=com.chaozh.iReaderFree
     &usr=&zysid=
Content-Type: application/x-www-form-urlencoded

type=volume&token=<9b.1 的 token>&price=<标价元>&dis_price=<活动价元>
&bid=<bookId>&coupon_code=<满减券 code，不用券就留空>
```

**body 只需这 6 个字段**，签名参数一个都不要。`usr` / `zysid` 放在 URL query 里。

成功返回：

```json
{"body":{"pay_url":"https://ah2.zhangyue.com/trade/order/download?…&order_id=ZO<20位订单号>…",
         "download_url":"http://ah2.zhangyue.com/r/enc_dl?downInfo=…"},
 "code":0}
```

### 9b.3 实测记录（2026-11-12）

《深宅活寡》`book_id=10891439`，账户代金券 1099、阅饼 0：

| 项 | 值 |
|---|---|
| 标价 | 2499 阅饼（`price` 24.99 元） |
| 活动价 | 1299 阅饼（`dis_price` 12.99 元，5.2 折） |
| 满减券 | 满1000减200，`code=630019` |
| 折后应付 | 1099 阅饼（`pay.amount` 10.99 元） |
| 代金券抵扣 | 1099 阅饼（`coupon_amount`，全额） |
| 阅饼抵扣 | 0 |
| 结果 | `code=0` 下单成功（返回 `order_id`）；代金券 1099 → 0，`IsAsset` 变 1 |

**结论**：满减券在新版通道确实生效（标价 −1300 活动折扣 − 200 满减券 = 实付）。

### 9b.4 关于签名

前端代码里虽有 `z.sign`（内部调 `do_sign` 走原生 App），但 Web 端下单**实测不需要任何签名参数**：

```js
// 前端 signUrl：旧版 App（android p3<=6700 / ios p3<17000007）直接跳过签名
t.signUrl = function(t, n) {
  if (android && p3<=6700 || ios && p3<17000007) n(t);
  else c.default.sign({url: t}).then(...)
}
```

纯 HTTP 构造上面那 6 个字段即可下单，无需模拟原生签名。

## 10. 加入云书架（⚠️ 写操作）

掌阅「购买」与「加书架」是**两步**。下单成功只是获得阅读权，书架列表**不会自动多出这本书**（App 是客户端自己再补一次调用）。

```http
POST https://api-pc.zhangyue.com/bookstore/open/cloud/bookshelf/upsert
     ?usr=&zysid=&p29=zye5b814&p2=104583&p3=18070403&p4=501603&p33=com.chaozh.iReaderFree
Content-Type: multipart/form-data

usr=<usr>
current_version=<读书架时返回的 current_version>   ← 乐观锁，必须带对
type=<1 新增 / 2 删除 / 3 更新>                    ← 详见 10.1
data=[{ "book_id":"10121980", "book_name":"某某书", "book_type":24, ... }]
```

一本书的字段（照抄 `bookshelf/list` 里现有条目的结构）：

```json
{
  "book_id": "10121980", "book_name": "某某书", "cover_name": "",
  "book_type": 24, "is_local_book": false, "book_file_id": "", "book_file_size": 0,
  "cover_file_id": "", "cover_file_size": 0, "folder_hierarchy": "[]",
  "dtype": 0, "order": -241, "folder": "", "top": 0, "top_sort": 0,
  "mark": "", "md5": ""
}
```

| 要点 | 说明 |
|------|------|
| `book_type` | `24` = 站内整本电子书（序列化 EPUB），普通出版物用 24 |
| `order` | 越小越靠前；取「现有最小 order − 1」即插到书架最前 |
| `current_version` | 乐观锁，不匹配返回 `{"code":100006,"msg":"version not equal error"}` |
| `folder_hierarchy` | 加书时可直接写 `["夹名"]`，等于「加书架 + 归夹」一步做完 |
| 成功返回 | `{"body":null,"code":0,"msg":"ok"}` |

**幂等**：先读书架，若 `book_id` 已在其中就直接跳过，避免重复写入。

### 10.1 `type` 的三种取值（全部真实跑通）

同一个 `upsert` 端点，`type` 决定动作：

| `type` | 含义 | 用于 |
|--------|------|------|
| `1` | 新增插入 | 加书架、新建文件夹节点 |
| `2` | **删除** | 删除文件夹节点 |
| `3` | **更新** | 改书的 `folder_hierarchy`（即「移动」）、置顶等 |

`data` 都是**条目数组**，可一次提交多本（批量移动只发 1 个请求）。

**版本号的坑**：每成功写一次，`current_version` 就 +1。连续写（例如
「建文件夹 → 移动书」「把书移出夹 → 删夹」）之间**必须重新调 `list` 拿新版本**，
否则第二次直接 `100006 version not equal error`。实测一次 `mkdir + move` 会
把版本号连续推进两次（`N → N+1 → N+2`）。

### 10.2 新建 / 删除文件夹

新建：插一个 `dtype=1` 节点（`type=1`）。删除：把该节点原样传回（`type=2`）。

```json
{
  "book_id": "<8位十六进制，随机生成>", "book_name": "", "cover_name": "",
  "book_type": 0, "is_local_book": false, "book_file_id": "",
  "book_file_size": 0, "cover_file_id": "", "cover_file_size": 0,
  "folder_hierarchy": "[\"新夹名\"]", "dtype": 1, "order": 1000012,
  "folder": "", "top": 0, "top_sort": 0, "mark": "A_1", "btype_ext": 0
}
```

要点：

- `book_id` 用随机 8 位十六进制即可，服务端不校验生成规则（`zfolder01`、
  uuid 前 8 位都成功过）。
- **服务端不会自动建夹**：把某本书的 `folder_hierarchy` 写成未登记的夹名，
  值能存下，但没有 `dtype=1` 节点，书架里看不到这个夹。实测写完后
  `list` 里只多了一个带该字段的书条目，文件夹节点数不变。
- 删非空夹时应先把夹里的书 `folder_hierarchy` 改成 `[]`（`type=3`），
  再删节点（`type=2`）；否则书会带着一个不存在的夹名，App 里行为不可预期。
  两步之间同样要重取版本号。

### 10.3 移动书到文件夹（已实测往返）

```http
POST .../cloud/bookshelf/upsert?usr=&zysid&...
Content-Type: multipart/form-data

usr=<usr>
current_version=<当前版本>
type=3
data=[{ "book_id":"11582366", "book_name":"某某书",
        "folder_hierarchy":"[\"科幻\"]", ...其余字段照抄 list 原条目 }]
```

`data` 里给**完整原条目**（照抄 `list` 返回的那一条）最稳妥，只改
`folder_hierarchy`。实测把某本书在「外国经典文学」与「科幻」之间往返移动，
两次都返回 `code=0`，重新 `list` 后两个夹的计数正确变化并复原。

## 11. 速率与并发

- 分类页抓取：并发 8 稳定，无明显限流
- 详情页查价：并发 8 稳定；全量约 9200 本耗时约 10 分钟
- 建议所有请求 3 次重试 + 递增退避
- 搜索翻页之间加 0.1~0.2 秒间隔
- 下单/加书架/移书/建删文件夹都是写操作，**串行执行、不要并发**；下单成功后 sleep 2 秒再校验
- 书架类写操作之间留 1 秒并重取 `current_version`，避免乐观锁冲突
