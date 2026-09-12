# 2026-09-10 会议要求对照｜V6

- ✅ 前台不展示 12 步 Workflow / 技术侧栏
- ✅ 单一聊天界面：新聊天、消息输入、文件上传、模板下载
- ✅ 支持 PDF / DOCX / XLSX / XLS / CSV
- ✅ 非标准字段/报告抽取采用对话内确认，不跳转流程页面
- ✅ 标准模板识别后自动进入数据检查与 Baseline
- ✅ 数据完整性自动判断；阻断字段不足时停止，不伪造分数
- ✅ 按注册数据源匹配 WS/DR/SV 与 BWD/DYS/CTS/OA
- ✅ 自动调用 D 组确定性 Baseline
- ✅ Baseline 后通过自然对话按钮继续四类 Scenario
- ✅ DeepSeek API 用于意图理解、报告候选抽取、Baseline/Scenario 结果解释与管理建议
- ✅ DeepSeek 不重新计算 PRWI / Coverage / Scenario 数字
- ✅ 后台执行过程默认隐藏，仅“查看分析过程”折叠展开工具/状态/版本信息
- ✅ 对话内生成并下载 Word 分析报告
- ✅ 支持浏览器语音转文字（浏览器支持时）
- ✅ Railway 环境变量保存 DeepSeek Key，不写入前端或仓库

## 仍需团队最终冻结

- B/C 正式数据查询 kernel / 最新数据快照
- E 最终 Scenario 冻结版本与 D Baseline 一致性
- DeepSeek API Key（部署环境配置）
