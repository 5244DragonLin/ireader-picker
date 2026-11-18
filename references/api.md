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

## 10b. 购物车（新版，`/zyuc/api/cart/cart`）★

掌阅 App 书城的购物车（详情页右上角 🛒 图标，上限 50 本，支持出版/漫画）。**与书架、与旧版购物车（10 节之前那套 `app.php?ca=Cart.*`）互不相通**。结论均来自 APK 逆向（主 dex + `pluginwebdiff_bookdetail.apk` / `pluginwebdiff_bookstore4.apk` 两个内嵌插件）加真机实测，2026-11-14。

### 10b.1 端点与签名

```http
GET https://ah2.zhangyue.com/zyuc/api/cart/cart
    ?act=<动作>&timestamp=<毫秒时间戳>&usr=<usr>&sign=<签名>
    &zysid=<zysid>&pluginVersion=34
```

**签名算法**（逆向自 `PluginRely.addSignParam` → `account/d.a` → `Security.hash`）：

```text
待签串 = "act=<act>&timestamp=<ts>&usr=<usr>"     ← 按 key 字典序，固定就这 3 个参数
sign   = BASE64( SHA1withRSA(待签串) )             ← 客户端内置 RSA 私钥（native_keys.json 第 4 把）
```

铁律（全部实测验证）：

- **待签串只允许 act/timestamp/usr 三个参数**。多塞 `bookId`/`zysid`/`pluginVersion` 任何一个都返回 `53001 签名错误`（见 10b.5 变体矩阵）。
- 私钥与登录同族（`native_keys.json`，服务端只认下标 3 那把）。**购物车接口依赖 cryptography 库**。
- 业务参数（`bookId`/`books`/`orderId` 等）与设备参数拼在 `sign` 之后、**不参与签名**；`zysid` 必须在 query（缺了返回 `50000 未登录`）。
- `timestamp` 是毫秒。UA 版本对该接口无影响；**设备参数 `p1`/`p3` 仅 `act=add` 校验**（见 10b.4），其余动作不需要。

### 10b.2 动作（act）与参数

| `act` | 作用 | 附加参数 | 实测 |
|-------|------|---------|------|
| `list` | 购物车列表 | 无 | ✅ |
| `add` | 加入购物车 | `&bookId=<id>&bookCategory=<1出版/2漫画>` + **必需 `&p1=…&p3=…`（见 10b.4）**；重复加返回 `code=201 已加入购物车` | ✅ |
| `del` | 删除书目 | `&books=[{"bookId":<id>,"bookCategory":1}]`（URL 编码 JSON，来自 `DeleteBook{bookId, bookCategory}`） | ✅ |
| `change` | 改结算勾选状态 | `&books=[{"bookId":..,"bookCategory":..,"selectStatus":0/1}]` | ✅ |
| `recd` | 基于购物车的推荐 | 无 | ✅ |
| `coupon` | 购物车可用券 | `&orderId=` | 未实测 |

响应包装：`{"code":0,"msg":"ok","body":{...}}`。错误/状态码：`201 已加入购物车`（add 重复）、`50000 未登录`（缺 zysid）、`53000 参数错误：<字段>不能为空`、`53001 签名错误`、`53002 系统异常`。

### 10b.3 列表结构（`act=list` 的 body）

```json
{
  "books": [{
    "type": 1, "typeName": "出版书籍", "couponInfo": {},
    "bookList": [{
      "bookId": 11172277, "bookName": "西洋哲学史", "author": "冯友兰",
      "price": "599", "priceDesc": "599阅饼",
      "state": 0, "selectStatus": 0, "buyDesc": "", "isDiscount": 1,
      "diff": "", "voucherDesc": "", "picUrl": "…", "url": "…"
    }]
  }],
  "booksLimit": 50,
  "ruleUrl": "https://ah2.zhangyue.com/zyuc/cart/rule?…"
}
```

- 分组 `type`：`1`=出版书籍；漫画另成组（未实测）。**加购的 `bookCategory` 与分组 `type` 同源**（出版=1）。
- 书目 `state`（逆向自 `BookInCart` 常量 `STATE_*`）：`0`=正常、`1`=免费、`2`=**下架**、`3`=失效。**下架/失效的书不支持结算**（官方规则页明示），App 里置灰显示。实测 2 本下架书 `state=2`。
- `selectStatus`：结算勾选状态，App 加购的书自动置 1。
- 规则页 `ruleUrl`（`/zyuc/cart/rule`）匿名可访问，写明：单次结算上限 50 本、支持代金券及阅饼、下架/免费/不参与活动的书不支持结算。

### 10b.4 加购（`act=add`）的排障全记录（已破案 ✅）

契约逆向自 `pluginwebdiff_bookdetail` 的 `ui/presenter/a.a(boolean)`：

```text
URL = URL_BASE_PHP + "/zyuc/api/cart/cart?act=add"
      + "&timestamp=<N1>&bookId=<bookId>&bookCategory=<1或0>&"
      + getUrledParamStr({usr, timestamp, act:'add'} + addSignParam 追加的 sign)
备用通道（布尔参数为假时）：URL_BASE_PHP + "/webintf/api/cartAdd?bid=<id>&pk=client_shopCart"
```

**最终答案**：`act=add` 的业务层要求请求携带**非空的 `p1`（设备指纹）与 `p3`（客户端版本号）**两个设备参数。值本身任意（旧版本号、任意 hex 都行，顺序无关），但缺失或为空 → 业务层异常 `53002 系统异常 body=-1`。其他动作（list/del/change/recd）不校验设备参数，这就是「只有 add 失败」的原因。

```text
最小可用形态：
GET …/cart/cart?act=add&timestamp=<ms>&usr=<usr>&sign=<签名>
    &bookId=<id>&bookCategory=1&zysid=<zysid>&pluginVersion=34
    &p1=ffffffffffffffffffffffff&p3=18080103
```

排查过程（供未来类似问题参考）：

| 假设 | 实验 | 结论 |
|------|------|------|
| bookCategory 取值不对 | 暴力扫描 223 个值（1-150 + 全部分类 cid） | 全 53002，排除 |
| 会话类型歧视（密码登录 vs 真机） | 从模拟器 MMKV 提取 App 登录 blob（`AT@6 {"AesKey":…,"Data":…}`），用登录同款 RSA 公钥解密 + AES 还原 → **App 会话与脚本会话完全相同**（服务端按用户复用 zysid） | 排除，且证明差异在请求本身 |
| 请求方法/体/顺序 | POST、表单体、双时间戳复刻、参数重排 | 排除 |
| UA / Cookie / Referer | 多版本 UA、各种 Cookie、XHR 头 | 排除 |
| 设备参数集 | 从**抓包成功流**（`saad.ms.zhangyue.net/ad/cfg` 带 App 真实全参数）提取 `p1/pc/p2/p3/p4/p5/p7/p9/p16/p21/p22/p25/p28/p29/p31/p33/p34` 全套重放 → **成功** | 锁定方向 |
| 必需参数定位 | 二分 + 单变量：`p3` 缺失 ❌、`p1` 缺失 ❌、两者都在 ✅；`p7`（设备 ID）不需要；p1/p3 值任意（旧版本号、任意 hex、顺序无关），**空值不行** | **最小集 = 非空 p1 + p3** |

附带发现：

- **`code=201` = 已加入购物车**（对应 App 反编译里 `NetworkException.getmResponseCode()==201 → updateCartMenu2HasAdded`），是正常状态不是错误。
- App 每个请求都带全套设备参数（`DeviceInfor.setURL` 构建）：`pc=10&p1=<指纹>&p2=<渠道>&p3=<版本>&p4&p5&p7=<设备ID>&p9&p16=<机型>&p21&p22=<安卓版本>&p25=<版本码>&p28&p29=zye5b814&p31=<androidId>&p33=<包名>&p34=<品牌>`。模拟器实测值：`p2=116298`、`p3=18080103`（8.8.1）、`p4=501603`、`p7=__5a10c5b990da8855`。
- 排查中解密模拟器 MMKV 的方法有复用价值：MMKV 明文存储登录 blob，`AT@6 {"AesKey":…,"Data":…}` 用登录同款 `rsa_public_decrypt(AesKey)` + `aes_decrypt(Data)` 可还原 `session_id` 与 `device_list`——**等于免抓包拿到 App 的会话与设备信息**。
- MITM 不可行的原因（记录备查）：App API 域流量走字节 TTNet/Cronet（`libtnet-3.1.14.so`），自带证书校验与锁定（系统 CA 对 CDN 域生效、对 ah2 被拒）；frida 注入被反调试杀进程（改名换端口也不行）。

### 10b.5 旧通道（`webintf/api/cartAdd`，供参考）

```http
GET https://ah2.zhangyue.com/webintf/api/cartAdd?bid=<bookId>&pk=client_shopCart&usr=&zysid=&p29=…&p2=…&p3=…&p4=…&p33=…
```

- **必须带设备参数（p2/p3/p4/p33/p29）**，缺了直接 404（tengine 路由依赖）。无需签名。返回 `{"code":0,"msg":"ok","body":<加购后旧购物车总数>}`。
- 写入的是**旧版购物车**（`app.php?ca=Cart.Num` 计数那套）：App 购物车页面看不到、旧购物车页 `Cart.Index` 已废弃（返回空）、不会同步进新版购物车。**对用户无使用价值。**
- 宿主域名曾试过 `uc.ireader.com`（同路径返回 -99999 系统错误，整族 webintf 在该宿主已死）。

### 10b.6 旧版购物车的残迹（已废弃，勿追）

主 dex 里还有旧通道痕迹：`app.php?ca=Cart.Index&key=GW1`（购物车页，真凭证也返回空=已废弃）、`ca=Cart.Num`（数量接口，**仍可用**，返回 `{"num":N,"status":0}`）、`ca=Order_Batch.Index&from=client`（旧批量结算页，未带版本参数时跳升级页）。旧购物车与新购物车互不相通（实测：旧通道加购后新列表不变）。

## 11. 书单（`/zyus/booklist/*` 原生 + `ca=Booklist.*` H5）★

「我的 - 我的书单」这套功能有两条通道：**读/删/收藏走 App 原生 `/zyus/booklist/*`（要签名）**，**加书/改书单走 H5 `app.php?ca=Booklist.*`（不要签名，但要带页面参数）**。结论来自 APK 逆向（`classes6.dex` 的 `online/ui/booklist/detail/m`、`edit/a`、`ActivityMyBookList`、`lh/a`）加 2026-11-16 全量实测。

### 11.1 端点与签名（★ 每个接口签的东西不一样）

```http
GET  https://ah2.zhangyue.com/zyus/booklist/myList?zysid=<zysid>&<参数>
POST https://ah2.zhangyue.com/zyus/booklist/add?zysid=<zysid>       （参数全在 body）
POST https://ah2.zhangyue.com/zyus/booklist/update?zysid=<zysid>
POST https://ah2.zhangyue.com/zyus/booklist/operate?zysid=<zysid>
POST https://ah2.zhangyue.com/zyus/booklist/book/operate?zysid=<zysid>
GET  https://ah2.zhangyue.com/zyus/booklist/info?<参数>
```

**签名算法**与购物车同源（`PluginRely.addSignParam` → `account/d.a`）：

```text
待签串 = "<k=v 按 key 字典序>"        ← 用 & 连接，跳过空值
sign   = BASE64( SHA1withRSA(待签串) ) ← native_keys.json 第 4 把私钥
```

但**每个接口签哪些 key 不同**，这是整套接口最容易踩的坑（多签一个或少签一个都返回 `53001 签名错误`）：

| 接口 | 参与签名的 key | 备注 |
|------|---------------|------|
| `myList` | `timestamp` `usr` | `listType`/`start`/`size` **不签** |
| `info` | 全部 query 参数 | `bookListId` `isEdit` `page` 都要签 |
| `operate` | `operate` `bookListId` | 两个都要签 |
| `book/operate` | `operate` `bookListId` `bookId` | 三个都要签 |
| `add` | 全部 | `addBooks` 也签（但它本身解析不过，见 11.4） |
| `update` | `bookListId` `name` `desc` | **`addBooks`/`updateBooks` 必须排除**，签了就 53001 |

铁律（全部实测）：

- **`zysid` 一律放 query、绝不参与签名**。缺了返回 `50000 未登录`，签进待签串则 `53001`。
- **POST 接口的业务参数要放 body**，不是 query。`add`/`update` 把参数塞 query 会返回 `53003 参数不正确` 或 `53001`。
- GET 接口（`myList`/`info`）参数放 query。`info` 缺 `page` 也返回 `53003`。
- 待签串里的值**不做 URL 编码**（与购物车一致，直接拼原文）。
- `timestamp` 是毫秒。

### 11.2 接口清单

| 接口 | 方法 | 参数 | 作用 | 实测 |
|------|------|------|------|------|
| `/zyus/booklist/myList` | GET | `listType`(1我建的/2我收藏的) `start`(页码,从1起) `size`(≤20) | 我的书单列表 | ✅ |
| `/zyus/booklist/info` | GET | `bookListId` `isEdit`(0/1) `page`(从1起,每页10本) | 书单详情 + 书目 | ✅ |
| `/zyus/booklist/add` | POST | `bookType`(1晒/2求) `name` `desc` `addBooks` | 建书单 | ⚠️ 见 11.4 |
| `/zyus/booklist/update` | POST | `bookListId` `name` `desc` `addBooks` `updateBooks` | 改名/改描述 | ✅ |
| `/zyus/booklist/operate` | POST | `operate` `bookListId` | 删单/收藏/取消收藏 | ✅ |
| `/zyus/booklist/book/operate` | POST | `operate` `bookListId` `bookId` | 移出书单 | ✅（仅 delete） |

`operate` 的取值（逆向 `ui/presenter/e` + 实测）：

| `operate` | 作用 | 实测 |
|-----------|------|------|
| `delete` | 删除书单 | ✅ |
| `addFavorite` | 收藏别人的书单 | ✅ |
| `deleteFavorite` | 取消收藏 | ✅ |
| `check` | 收藏前检查 | 未测 |
| `like` / `dislike` | 书单点赞/踩 | 未测（在 `book/operate` 下实测返回成功但书目被清空，勿用） |

`book/operate` 的 `operate`：**只有 `delete` 可用**。`add`/`del` 返回 `53002 获取数据错误`；`update`/`edit`/`modify` 同。加书只能走 H5（11.3）。

### 11.3 H5 通道（加书 / 改推荐理由）

```http
POST https://ah2.zhangyue.com/zybook3/app/app.php
     ?ca=Booklist.AddOneBook&usr=<usr>&zysid=<zysid>&p29=zye5b814&p2=104583
     &p3=18070403&p4=501603&p33=com.chaozh.iReaderFree
body: id=<书单id>&bid=<book_id 或 ISBN:xxx>&type=<1在售/0 ISBN>&name=&author=&pic=&desc=&timestamp=
```

- **不要签名**，但要带全 5 个页面参数（`p29`/`p2`/`p3`/`p4`/`p33`），缺了返回 `1 参数不正确`。
- `desc` 就是「推荐理由」，`name`/`author`/`pic` 会被服务端覆盖成真实书目信息，传空也可以。
- 重复加同一本书返回 `31206 该图书已存在`（不是 upsert）。
- `Booklist.DeleteBook` 用 `id`+`bid`+`user_name`（**不是** `bklist_id`，那个会报 `'user_name'` KeyError）。
- `Booklist.UpdateOneBook`（改推荐理由）实测恒返回 `1 无数据返回`，**不可用**；要改理由只能删了重加。
- `Booklist.Suggest`（加书联想）是 GET，参数 `ca=Booklist.Suggest&keyword=<词>&id=<书单id>`，返回 `[{id,type,name,author,pic}]`；`type=1` 在售（`id` 是数字 book_id）、`type=0` 豆瓣 ISBN（`id` 形如 `ISBN:9787...`）。

### 11.4 建书单：`addBooks` 是坏的，必须分两步

`/zyus/booklist/add` 的 `addBooks` **无论传什么结构都报** `code=2 invalid literal for int() with base 10: ''`——服务端拿书单 id（新建时为空）去做 `int()` 转换。试过的全部结构均失败：

```text
[]                                 → 成功（唯一能过的值）
[{"bookId":"10881716"}]            → invalid literal for int()
[{"n":"10881716","o":"理由"}]      → invalid literal for int()   ← lh/a 的字段名也不行
[{"id":10881716,"name":"x",...}]   → invalid literal for int()
["10881716"]                       → 'str' object does not support item assignment
```

逆向出的结构确实是 `[{"n":"<bookId>","o":"<推荐理由>"}]`（`edit/a.g5` 把 `jh/b.o`→`lh/a.n`、`jh/b.r`→`lh/a.o`，`lh/a` 只有 `n`/`o` 两个字段），但服务端这条链路已坏。**正确做法：先建空单（`addBooks=[]`），再逐本 `Booklist.AddOneBook`**。脚本 `blnew --add` 就是这么实现的。

### 11.5 字段与限制

`/zyus/booklist/info` 的 body：

```json
{
  "info": {
    "name": "科幻", "desc": "…", "count": 2, "tags": ["科幻","银河奖"],
    "isPublic": "public", "favNum": "0", "fav_num": 0, "favable": true,
    "canAdd": "yes", "status": "normal", "updateTime": "刚刚",
    "all_book_ids": ["10881716","11550952"],
    "urlEdit": "…ca=Booklist.Edit&id=…",
    "shareAction": {"Action":"share","Data":{…}}
  },
  "books": [{
    "id": 10881716, "name": "…", "author": "刘慈欣", "bookRating": "9.1",
    "book_desc": "创建人写的推荐理由", "description": "书籍内容简介",
    "cover": "…", "category": "小说", "readable": true,
    "is_removed": true, "like": "0", "dislike": "0", "adder": "i…"
  }],
  "user": {"name": "Dragon水魅", "avatar": "…"}
}
```

- `book_desc` = 推荐理由（创建人手写），`description` = 书籍内容简介。**两者别混**，用户问"为什么推荐"看前者。
- `is_removed: true` 表示该书在掌阅已下架（书单里仍保留条目）。**书单里下架书比例实测普遍 30%~67%**（如书单 129684 是 26/44）；此类书 `info` 查不到详情与价格、无法购买。`readable` 实测恒为 true，**不能**当在售判据，唯一可靠的判据就是 `is_removed`。脚本 `booklist` 人读输出已打 `[已下架]` 标，`--sale` 只显示在售书。
- `count` 是真实书目数；每页 10 本，`page` 翻到空为止。
- `listType=2`（我收藏的）每条多一个 `favorite_time`（日期，如 `2026-11-16`）。
- **`myList` 里的 `books` 只是预览**：通常只回 1 本，且 `description` 是书籍内容简介而不是推荐理由。要列全书目/推荐理由必须另外调 `info`（`mybl --books` 就是这么做的）。
- `status`：`normal` 正常、`check` 审核中（此时 `info` 返回 53002）。

限制：

| 项 | 限制 | 错误码 |
|----|------|--------|
| 名称 | 1~40 字 | 空 → `53003`；超长/敏感词 → `31215 文字内容违规` |
| 描述 | 1~200 字 | 同上（**错误码不指明是哪个字段**） |
| 单书单书目 | 100 本 | 客户端限制（`edit/a` 里硬编码） |
| 我的书单分页 | `size` ≤ 20，`start` 从 1 起 | 超了返回 `2 size is greater than 20` |

### 11.6 实测记录（2026-11-16）

- 建单 → 加书 2 本 → 改名 → 移出 1 本 → 删单：全链路通过，`count` 每次都对得上。
- `myList` 的 `start` 是**页码**不是 offset：`start=1` 返回第 1~size 条，`start=2` 从第 size+1 条开始。
- `operate=like`/`dislike` 在 `book/operate` 下会返回成功但**把书目清空**，不要用。
- 收藏/取消收藏别人的书单往返正常，`mybl --fav` 的 `total` 随之增减。
- 加书后服务端会补全 `name`/`author`/`cover`（即使传空），所以加完回读一次能拿到真实书名。
- **`update` 有两个副作用**（都实测复现）：
  1. 书单被置为审核态 `status=check`，此状态下 `/zyus/booklist/info` **恒返回 `53002 获取数据错误`**（`myList` 仍可读）。等审核结束（本次约 1~2 分钟）才恢复。
  2. 自动生成的 `tags` 被清空。`tags` 由书目分类汇总而来，`update` 不接收 `tags` 参数（传 `tags` 也照样清空），**只有重新加书才会重算回来**。
  因此 `bledit` 只应在用户确实要改名称/描述时调用，不要顺手"统一"一下描述。
- **审核态判定**：`myList` 里该条 `status` 字段为 `check`（正常是 `normal`）；此时 `info` 的 53002 不是故障。

### 11.7 搜索翻页（searchMultiple 的 `type=bkList` / `type=book` 模式）★

书城搜索结果页的「书单」「书籍」两个页签各有**两种请求形态**，对应 App 里「首屏」和「加载更多」两个动作。结论来自 APK 逆向（`classes6.dex` 的 `ih/b` 类，URL 拼接方法 `j`=书单 tab / `n`=书籍 tab）加 2026-11-16 实测。

```http
# 首屏（无 type）：书单第一屏 3 条 + 作者卡 + 同页书籍 + relatedSearch
GET https://ah2.zhangyue.com/zybook3/u/p/api.php?Act=searchMultiple&keyWord=<关键词>&usr=&zysid=&p29=zye5b814&p2=104583&p3=18070403&p4=501603&p33=com.chaozh.iReaderFree

# 加载更多（带 type）：只返回 bkList（书单列表），book/relatedSearch 节点不返回
GET https://ah2.zhangyue.com/zybook3/u/p/api.php?Act=searchMultiple&keyWord=<关键词>&type=bkList&pageSize=<n>&currentPage=<m>&suggestType=0
```

- **翻页三件套是 `type=bkList` + `pageSize` + `currentPage`**。只传 `currentPage` 不传 `type` 无效（实测 `pageNo`/`page`/`pn` 等也全部无效，返回第 1 页）——这是此前"分页参数未公开"的原因，缺的不是页码参数而是 `type` 开关。
- App 原生拼法里书单 tab 加 `type=bkList&pageSize=N&currentPage=M&suggestType=S`（逆向 `ih/b.j`）；书籍 tab 是 `type=book&pageSize=N&currentPage=M&filterAuthor=1&suggestType=S`（`ih/b.n`）。`suggestType` 传 0 实测有效，省略也可。
- 书籍 tab 的 `filterAuthor=1` 会滤掉作者卡条目（data_type=1）；不传时第 1 页会多出一条 `data_type=1` 的作者卡。响应 body 只有 `book` 节点，`book.page` 结构与 `bkList.page` 相同。书籍条目的 `completeState` 是 **`Y`/`N` 字符串**（已完结/连载中），不是 0/1；`bookRating` 为 0 表示无评分。脚本命令 `bsearch`。
- `/zybook3/u/p/api.php` 与 `/zybook/u/p/api.php` 两个路径实测行为一致，脚本统一用 App 真实的 `zybook3`。
- **未登录（usr/zysid 空）可用**；`p2x` 渠道参数也可省（精简形态 `Act+keyWord+type+pageSize+currentPage` 即可）。
- `pageSize` 实测 100 有效（`totalPage` 相应变为 1）；`currentPage` 超界**不报错**，返回空 `datas`，`page.currentPage` 被服务端钳制为最后实际页。
- `bkList.page` 结构：`{"currentPage": 1, "totalPage": 12, "totalRecord": 36, "pageSize": 3}`（首屏固定 pageSize=3）。同一关键词 totalRecord 不随 pageSize 变。
- 举例：`南派三叔` 共 36 个书单，`pageSize=50&currentPage=1` 一次拿全；`东野圭吾` 共 351 个，需按页翻。
- `--all` 聚合上限 200 条是脚本本地防呆（防敏感词返回大结果时跑飞），不是服务端限制。

## 12. 速率与并发

- 分类页抓取：并发 8 稳定，无明显限流
- 详情页查价：并发 8 稳定；全量约 9200 本耗时约 10 分钟
- 建议所有请求 3 次重试 + 递增退避
- 搜索翻页之间加 0.1~0.2 秒间隔
- 下单/加书架/移书/建删文件夹都是写操作，**串行执行、不要并发**；下单成功后 sleep 2 秒再校验
- 书架类写操作之间留 1 秒并重取 `current_version`，避免乐观锁冲突
- 书单写操作同样串行：`bladd` 逐本加、`blrm` 逐本删，脚本已内置 `delay`（默认 0.15s）

## 13. 淘书市活动页（`taoshu` 命令，读操作）★

> 完整逆向（含领券的 X-Nonce/X-Sign 双头签名）在姊妹仓库 `ireader_welfare/docs/掌阅逆向笔记.md` 第二十一节。本节只记 `ireader-picker` 用到的**读**部分：找活动 → 解析券与书目 → 查价推荐。

### 13.1 活动入口：频道页滚动 banner（匿名）

```http
GET https://ah2.zhangyue.com/zybk/channel/ajaxrequest?page=1&key=ch_publish&index=0
```

返回 `{"code":0,"blockData":"<div class='slider-banner'>..."}`。每个 `li.slider-item` 一张 banner：

| 抓取项 | 位置 |
|--------|------|
| 跳转地址 | `data-url`（淘书市那期是 `https://h5.zhangyue.com/opr/<act_id>.html?act_id=...`） |
| banner 名称 | `data-point` JSON 的 `name`（如「淘书市180期」） |

出版（`ch_publish`）/ 精选（`ch_feature`）两个频道都实测挂过同一期。同一 `data-url` 在两个频道重复出现，需按 act_id 去重。

**识别三级判定**（为换期自适应，不写死 act_id）：① banner 名称含「淘书」→ 直接认定；② 名称不含 → 抓活动页正文确认含「淘书」；③ 全不含 → 页面含 `amp_coupon` 券组件的 opr 活动页兜底认定。未换期时滚动栏里没有 opr 链接，返回空列表（不是错误）。

### 13.2 活动页：券与书目的数据结构（匿名）

```http
GET https://h5.zhangyue.com/opr/<act_id>.html?act_id=<act_id>&launch=inside
```

Vue SSR，带不带 usr/zysid 渲染结果一致。券与书目的 **id 都不在 HTML 里**，在每期一个的 JS bundle：

```html
<script src="https://static-tos-front-h.zhangyuecdn.com/opr/js/<act_id>.<hash>.js">
```

| 数据 | bundle 里的形态 | HTML 里的对应 |
|------|----------------|---------------|
| 满减券 product_id | `req_params:{ids:["31226",...]},req_type:"coupon"` | `amp_coupon_*` 块（面额 `<b>200</b>阅饼`、门槛 `满500阅饼使用`、有效期 `class="time"`） |
| 活动书目 book_id | `req_params:{cart_id:"33484",ids:[...]},req_type:"book"`（56 个组件、约 150 本，去重保序） | SSR 有书名/作者/简介但**没有价格与 book_id** |

配对规则：券的 HTML 块与 bundle ids 都是自上而下的组件顺序，直接顺序配对；数量对不上以 ids 为准、面额留空。书目 id 无需与 SSR 配对——价格回 `book.php` 详情页查（3 节），SSR 里的书名只作展示参考。

**本期实测（180 期，2026-11-09 ~ 11-23）**：act_id `78nah1ma6g0`，券 4 张（200/满500、800/满2000、2400/满5000、5000/满10000），书目 151 本，特价为主（500~1500 阅饼居多）。

### 13.3 与领券的分工

领券（`POST /operation/wap/coupon_receive` + 签名）在 `ireader_welfare/src/ireader_welfare/taoshushi.py` 的 `claim_all()`，幂等（重复领取返回 200003 视为成功）。`ireader-picker` 不做领券——选书工具只读，写（入账）统一归福利工具。领完的券出现在 `/zyuc/coupon/ajaxrequest?index=1`（`Client.coupons("book")`），`buy` 新版通道自动抵扣。

`taoshu` 的推荐口径与 `afford --coupon` 一致：门槛 ≤ 自付上限 + 面额才启用选券，券后自付 = max(价 − 面额, 0)，且要求 ≤ 自付上限。差异点：淘书市券与普通满减券是同一套 `/zyuc/coupon` 账目，`buy` 不区分来源、达到门槛即用。
