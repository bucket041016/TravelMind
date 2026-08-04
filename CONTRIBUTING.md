# 协作规范

本文档规定了所有贡献者修改本仓库时应遵循的流程和规范。

## 分支规则

| 分支 | 用途 | 谁可以推送 |
|------|------|-----------|
| `main` | 稳定版本，对应 Release | 仅通过 PR 合并，不直接推送 |
| `develop` | 开发主线 | 所有人可以推送 |
| `feature/*` | 功能开发 | 创建者 |
| `fix/*` | Bug 修复 | 创建者 |

## 提交规范

### Commit Message 格式

```
<类型>: <简短描述>
```

### 类型

- `feat`: 新功能
- `fix`: 修复 bug
- `style`: 样式/UI 调整（不影响逻辑）
- `refactor`: 代码重构
- `docs`: 文档更新
- `test`: 测试相关
- `chore`: 构建/配置/依赖

### 示例

```
feat: 新增拖拽排序行程功能
fix: 修复高德地图 marker 超过 9 个时报错
style: 重设计首页表单布局
docs: 完善 README 启动说明
```

## 推送前必做检查

每次 push 之前，请确认以下检查全部通过：

```powershell
# 后端语法检查
.\.venv\Scripts\python.exe -m py_compile .\sync\travel_web_app.py
.\.venv\Scripts\python.exe -m py_compile .\sync\multi_agent\structured_planner.py
.\.venv\Scripts\python.exe -m py_compile .\sync\fastmcp_server_streamhttp.py

# 前端语法检查
node --check .\web\app.js

# 如果改了后端逻辑，运行测试
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
```

## 日常流程

1. **开始前**：`git pull origin develop` 拿最新代码
2. **开发中**：频繁 `git commit`，保存进度
3. **完成后**：确认检查通过，`git push`
4. **通知**：告知协作者已推送

## 安全规则

- **绝不**提交 `.env` 文件（API Key 等敏感信息）
- **绝不**在代码、文档、终端输出中暴露 Key
- 新增环境变量时，同步更新 `.env.example`

## 发布流程

1. `develop` 上的代码测试通过
2. 合并到 `main`
3. 打版本标签：`git tag -a v0.X.0 -m "描述"`
4. 推送：`git push origin main && git push origin v0.X.0`
5. 在 GitHub 上创建 Release
