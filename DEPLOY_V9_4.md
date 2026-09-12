# WaterPulse V9.4 部署说明

本版专门修复 Railway 因 QA 黄金样例文件未上传而导致整个服务启动失败的问题。

- `example_*_input/output.json` 现在属于 **可选 QA 夹具**，不再是网站运行依赖。
- 即使 GitHub/Railway 没有这些文件，主页、DeepSeek、文件上传、参考数据分析、风险计算和导出仍可正常启动。
- `/api/qa` 在 QA 文件缺失时会返回 `status=unavailable`，而不是让服务崩溃。
- 真正运行必需的程序或数据文件若缺失，仍会明确列出缺失文件，避免静默运行错误。

部署后先访问 `/api/health`，确认 `version` 为 `9.4`。
