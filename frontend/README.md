# 跨端前端共用层

该目录只维护 Web 与微信小程序真正适合共享的稳定输入。目前包括语义颜色令牌；API 契约仍以服务端 OpenAPI 为唯一事实源。

微信小程序目前暂停功能开发，但不允许架构漂移。`test_frontend_contracts.py` 会确认两端各自只有一个网络请求网关，并验证现有调用仍属于服务端 OpenAPI；`test_design_tokens.py` 继续验证跨端颜色同步。

修改 `design-tokens.json` 后执行：

```powershell
python scripts/generate_design_tokens.py
python scripts/generate_design_tokens.py --check
```

生成器同步 `web/design-tokens.css`、`miniapp/styles/design-tokens.wxss`，以及小程序导航和 Tab 的四个颜色字段。两个样式输出不能手工修改；`app.json` 的页面、标题和其他平台配置仍正常维护。

两端不直接共用 CSS 布局：Web 使用 px、响应式网格和鼠标交互；小程序使用 rpx、原生组件和触控交互。间距、字号、组件结构与平台反馈应分别维护。未来迁移 Vue/uni-app 时，可继续复用此令牌源和 OpenAPI 客户端，而不把平台视图强耦合在一起。
