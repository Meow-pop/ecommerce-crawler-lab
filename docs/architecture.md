# 架构说明

## 目标

项目将“目标站”和“采集器”完全隔离。目标站用于安全复现动态加载、会话签名与限流；采集器只通过公开的 HTTP 边界工作，不导入目标站的 Python 代码。

```text
┌──────────────────────────┐
│ target: FastAPI          │
│                          │
│ /                        │
│ /api/bootstrap           │
│ /api/products            │
│ /health                  │
└────────────┬─────────────┘
             │ HTTP + Cookie + HMAC headers
┌────────────▼─────────────┐
│ crawler: Python stdlib   │
│                          │
│ bootstrap/session        │
│ canonical signing        │
│ retry/backoff            │
│ validation/deduplication │
│ JSON + CSV               │
└──────────────────────────┘
```

## 请求协议

`POST /api/bootstrap` 创建临时会话，通过 `HttpOnly` Cookie 标识会话，同时返回只在当前实验会话中使用的客户端令牌。商品请求需要三个请求头：

- `X-Lab-Timestamp`：Unix 秒时间戳；
- `X-Lab-Nonce`：一次性随机字符串；
- `X-Lab-Signature`：对规范字符串计算的 HMAC-SHA256。

规范字符串：

```text
timestamp\nnonce\nquery\npage\npage_size
```

服务端拒绝过期时间戳、重复 nonce、错误签名和超过速率限制的请求。这个协议只属于本地实验站，不代表任何真实电商平台实现。

## 数据质量

采集器对每件商品执行以下检查：

1. 必须包含商品 ID 和标题；
2. 价格必须可以转换为非负小数；
3. 销量、评论数和库存必须是非负整数；
4. 同一运行内按商品 ID 去重；
5. 输出记录查询条件、来源地址和 UTC 采集时间；
6. CSV 中以 `= + - @` 开头的字符串会被转义。

## 威胁边界

签名令牌可以被运行在页面里的 JavaScript 使用，因此不是服务端机密。它的作用是提供一个可观测、可测试的逆向分析练习，而不是安全认证方案。真实系统不应把长期密钥放入浏览器代码。

## 国内公开来源链路

```text
苏宁公开关键词 URL
    ↓ URL 白名单 + robots.txt 运行时检查
公开 HTML 解析商品字段 + Microsoft Edge 渲染展示价
    ↓ 发现验证立即停止
公开商品卡片 → 字段校验 → 去重
    ↓
价格/评价/店铺/材质/容量 → 完整率报告 → JSON + CSV
```

公开来源采集器与本地实验站采集器相互独立，前者用于真实市场洞察，后者用于安全展示协议分析和反爬工程能力。什么值得买解析器作为“访问受限时停止”的实验案例保留，不伪装成可用数据源。
