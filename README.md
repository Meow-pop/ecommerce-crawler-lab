# 苏宁公开商品采集与 AI 市场调研作品集

这是一个面向爬虫开发、数据工程和 AI 市场调研岗位的中文作品集项目。当前已经实现并验证的真实数据源是苏宁公开搜索首屏；项目还包含一个完全运行在本地的模拟电商实验站。它展示如何在安全与合规边界内完成公开商品数据采集、数据清洗、质量校验、统计分析和 AI 应用扩展。

项目目前包含三条互相独立的能力链路：

- 自有动态电商实验站：安全演示会话、签名、限流、重试和数据去重；
- 苏宁公开商品采集：自动读取苏宁公开搜索首屏并生成结构化数据；
- 市场调研报告：根据采集结果生成价格带、店铺集中度、商品属性和证据链接报告。

## 项目技术栈

- **采集与解析**：Python、Playwright、Microsoft Edge、HTML 解析；
- **实验服务**：FastAPI、Docker Compose；
- **数据输出**：JSON、CSV、Markdown；
- **质量保障**：字段完整率、数据校验、去重、单元测试；
- **AI 扩展方向**：Dify、DeepSeek、本地嵌入模型和知识库检索。

## 为什么使用自有实验站

真实电商平台会持续更新访问控制，未经许可的批量采集还涉及平台条款、账号安全和合规风险。本项目不破解验证码、不伪造设备、不使用代理池，也不调用第三方私有接口。

自有实验站复现工程问题，允许在明确授权的环境中展示同类能力：

- JavaScript 动态加载商品；
- Cookie 会话和短期请求令牌；
- HMAC-SHA256 请求签名；
- 时间戳与一次性 nonce 校验；
- HTTP 429 限流和 `Retry-After`；
- 分页、去重、字段校验与证据元数据；
- JSON/CSV 导出和电子表格公式注入防护。

## 当前里程碑

- [x] 建立本地动态电商实验站
- [x] 实现签名校验、会话、nonce 和限流
- [x] 实现标准库采集器及 JSON/CSV 导出
- [x] 添加单元测试和 PowerShell 脚本
- [x] 增加苏宁公开搜索商品与价格适配器
- [x] 增加什么值得买公开分类解析器与访问限制诊断
- [ ] 增加选择器变更与多版本页面
- [ ] 增加 Redis 任务队列和 PostgreSQL
- [ ] 增加采集质量看板与告警
- [ ] 增加第二个经确认允许采集的国内公开来源适配器

## 快速开始

要求：Windows 10/11、Docker Desktop 和 Docker Compose。

启动实验站：

```powershell
.\scripts\Start-Lab.ps1
```

浏览器访问：<http://127.0.0.1:8081>

采集三页“保温杯”并导出：

```powershell
.\scripts\Run-Collector.ps1 -Keyword "保温杯" -Pages 3
```

结果写入 `data/`。停止实验站：

```powershell
.\scripts\Stop-Lab.ps1
```

## 国内真实商品采集

苏宁公开搜索页是第一条可自动运行的国内数据链路。首次安装浏览器渲染依赖：

```powershell
.\scripts\Install-Browser-Collector.ps1
```

采集最多 30 件“保温杯”商品：

```powershell
.\scripts\Run-Suning-Collector.ps1 -Keyword "保温杯"
```

采集器先读取并校验 `robots.txt`，再获取公开 HTML；价格由本机 Edge 正常渲染后读取。它不登录、不翻页、不并发，也不调用账户或订单接口。

一键完成采集、质量检查和市场报告：

```powershell
.\scripts\Run-Domestic-Research.ps1 -Keyword "保温杯" -MaxItems 30
```

结果目录中会同时生成原始 JSON、便于查看的 CSV，以及包含价格带、店铺集中度、材质/容量、广告占比、热门商品和证据链接的 Markdown 报告。

## 实验性消费者洞察快照

该实验适配器读取什么值得买的公开分类页。它不等同于任何电商平台的完整商品库，而是尝试汇总消费者文章中的价格、渠道、材质、容量和互动信号，适合用于研究需求痛点、价格认知和竞品讨论。

什么值得买页面在普通浏览器中可访问，但当前会拦截独立 Playwright 自动化环境。因此下面的命令目前用于验证“遇到限制即停止”的行为，不作为无人值守数据源：

```powershell
.\scripts\Run-SMZDM-Insights.ps1
```

脚本使用电脑现有的 Microsoft Edge，不登录、不翻页、不解决验证码。其他分类必须传入已核对的 `https://www.smzdm.com/fenlei/.../` 地址：

```powershell
.\scripts\Run-SMZDM-Insights.ps1 -Category "分类名称" -Url "https://www.smzdm.com/fenlei/分类路径/"
```

运行单元测试：

```powershell
.\scripts\Test-Lab.ps1
```

## 采集链路

```text
模拟商城页面
    ↓ POST /api/bootstrap
获得 Cookie 会话 + 临时签名令牌
    ↓ HMAC(timestamp + nonce + query + page)
GET /api/products
    ↓ 401/409/429 分类处理
字段校验 → 去重 → JSON/CSV
```

## 输出字段

`rank`、`product_id`、`title`、`brand`、`price`、`monthly_sales`、`rating`、`review_count`、`capacity_ml`、`material`、`stock`、`product_url`、`source_url`、`collected_at`。

苏宁来源输出 `product_id`、`sku_id`、`title`、`price_cny`、`review_count_lower_bound`、`store_name`、`selling_point`、`is_sponsored`、`mentioned_materials`、`capacity_ml`、`product_url`、`source_url` 和 `collected_at`。还会报告价格、店铺和评价字段完整率。

## 安全与合规边界

- 只对仓库自带实验站或明确允许自动访问的目标运行采集器。
- 遇到验证码、安全验证、账号限制或明确禁止自动化访问时停止。
- 不将这个实验站的令牌算法描述成真实平台算法。
- 真实网站适配器必须单独记录来源、访问条件、速率和数据用途。
- 不提交 Cookie、账号、API 密钥、代理凭证或真实个人数据。
- 什么值得买搜索子域明确禁止自动访问，本项目只处理核对过的公开分类页。

架构说明见 [docs/architecture.md](docs/architecture.md)，真实来源边界见 [docs/public-source-policy.md](docs/public-source-policy.md)，后续路线见 [docs/roadmap.md](docs/roadmap.md)。
