# WebUI UX 优化测试指南

## 快速测试步骤

### 1. 启动开发服务器

```bash
cd /Users/dex/YDEX/INPORTANT WORK/外链/backlink-publisher-69/backlink-publisher
python webui.py
```

服务器将在 `http://localhost:8888` 启动。

### 2. 测试功能

#### 测试深色模式
1. 打开浏览器访问 `http://localhost:8888`
2. 点击导航栏右侧的月亮图标（主题切换按钮）
3. 验证：
   - 页面背景变为深色
   - 文字变为浅色
   - 卡片、表单等元素适配深色主题
   - 刷新页面后主题保持（localStorage持久化）

#### 测试导航
1. **桌面端**：验证导航栏显示分组（核心/监控/配置）
2. **移动端**（Chrome DevTools模拟）：
   - 点击汉堡菜单图标
   - 验证侧边栏抽屉滑出
   - 点击导航项跳转
   - 点击遮罩层关闭

#### 测试搜索
1. 按 `Ctrl+K`（或 `Cmd+K`）
2. 验证搜索模态框打开
3. 输入关键词（如"发布"、"设置"）
4. 验证搜索结果显示
5. 点击结果或按 `Enter` 跳转
6. 按 `ESC` 关闭

#### 测试通知中心
1. 点击导航栏的通知铃铛图标
2. 验证通知面板打开
3. 执行一个操作（如发布任务）
4. 验证toast通知显示
5. 验证通知面板中有新通知

#### 测试无障碍
1. 使用 `Tab` 键导航整个页面
2. 验证所有交互元素有焦点指示器
3. 验证skip-nav链接工作（按Tab第一次出现"跳转到主要内容"）

### 3. 运行自动化测试

```bash
# 运行JavaScript单元测试
make test-js

# 运行Python测试
PYTHONHASHSEED=0 pytest tests/ -v --timeout=30

# 运行lint检查
make lint

# 运行类型检查
make type-check
```

### 4. 检查浏览器控制台

打开浏览器开发者工具（F12），检查：
- 无JavaScript错误
- 无CSS警告
- 无404资源加载失败

### 5. 响应式测试

使用Chrome DevTools的设备模拟器测试：
- iPhone SE (375px)
- iPhone 12 (390px)
- iPad (768px)
- iPad Pro (1024px)
- Desktop (1200px+)

验证：
- 导航在移动端显示汉堡菜单
- 表单在小屏幕单列布局
- 卡片适当堆叠
- 触摸目标足够大（44px）

## 测试清单

- [ ] 深色模式切换正常
- [ ] 深色模式在所有页面一致
- [ ] 导航分组清晰
- [ ] 移动端汉堡菜单工作
- [ ] 搜索模态框打开/关闭
- [ ] 搜索结果正确显示
- [ ] 键盘快捷键工作（Ctrl+K, ESC）
- [ ] 通知中心显示通知
- [ ] Toast通知自动消失
- [ ] 所有按钮有aria-label
- [ ] Skip-nav链接工作
- [ ] 焦点指示器可见
- [ ] 响应式布局在各断点正常
- [ ] 无JavaScript错误
- [ ] 无CSS警告

## 常见问题

### 主题不切换
- 检查localStorage是否启用
- 检查控制台是否有theme.js错误

### 导航不显示分组
- 检查屏幕宽度是否>1024px
- 检查lite_edition变量是否正确

### 搜索不工作
- 检查nav.js是否加载
- 检查控制台是否有错误

### 通知不显示
- 检查notifications.js是否加载
- 检查localStorage是否可用

## 回滚更改

如需回滚，可以恢复原始文件：

```bash
cd /Users/dex/YDEX/INPORTANT WORK/外链/backlink-publisher-69/backlink-publisher
git checkout -- webui_app/static/css/tokens.css
git checkout -- webui_app/static/css/global_nav.css
git checkout -- webui_app/templates/base.html
# ... 其他修改的文件
```

或删除新创建的JS文件：

```bash
rm webui_app/static/js/theme.js
rm webui_app/static/js/nav.js
rm webui_app/static/js/notifications.js
```