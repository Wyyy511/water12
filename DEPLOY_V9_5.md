# WaterPulse V9.5 最终 MVP 部署说明

## 1. 上传
解压本 ZIP，把里面所有文件直接上传 GitHub 仓库根目录。V9.5 仍兼容 GitHub 网页上传被压平的情况。

## 2. Railway Variables
至少配置：
- DEEPSEEK_API_KEY = 你的 DeepSeek Key
- DEEPSEEK_MODEL = deepseek-v4-flash

API Key 不要写入 GitHub。

## 3. 部署后检查
依次访问：
- /api/health -> version 必须是 9.5
- /api/agent/status -> deepseek_configured=true
- /api/deepseek/test -> ok=true 才代表真实 AI 已连通
- /api/data-contract -> 51 fields / 10 gaps
- /api/supported-locations -> 当前登记节点范围

## 4. 最终 MVP 稳定演示路径
标准 Excel/CSV -> 数据确认 -> 当前风险 -> 最大贡献供应地 -> 主要风险来源 -> 主要供应地中断 -> AI 完整解释 -> Word 报告 -> 运行记录 JSON。

推荐固定使用 MVP_Demo_Sugarcane_40_60.csv。

## 5. 当前稳定范围
- 自然语言问答
- 标准 Excel/CSV 采购输入
- 甘蔗核心案例
- 项目登记的 16 个供应节点
- 主要供应地中断压力测试
- DeepSeek 解释
- Word 报告和运行记录

PDF/Word 抽取、其他未来情景、全球任意地点匹配均保留为试验/扩展能力，不作为最终 MVP 必过项。
